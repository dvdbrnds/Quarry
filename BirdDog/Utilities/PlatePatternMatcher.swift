import Foundation
import CoreGraphics

enum PlatePatternMatcher {

    private static let broadPattern = try! NSRegularExpression(pattern: "^[A-Z0-9]{5,7}$")
    private static let paPattern = try! NSRegularExpression(pattern: "^[A-Z]{3}[0-9]{4}$")

    /// Plates from PA and nearby states (NJ, NY, DE, MD, CT) -- instant confirm
    private static let localFormats = [
        try! NSRegularExpression(pattern: "^[A-Z]{3}[0-9]{4}$"),      // PA, NY, OH: ABC1234
        try! NSRegularExpression(pattern: "^[A-Z][0-9]{2}[A-Z]{3}$"), // NJ: A12BCD
        try! NSRegularExpression(pattern: "^[A-Z]{2}[0-9]{3}[A-Z]$"), // NJ alt: AB123C
        try! NSRegularExpression(pattern: "^[0-9]{6}$"),              // DE: 123456 (digits only)
        try! NSRegularExpression(pattern: "^[0-9][A-Z]{2}[0-9]{4}$"), // MD: 1AB2345
        try! NSRegularExpression(pattern: "^[A-Z]{2}[0-9]{5}$"),      // CT: AB12345
        try! NSRegularExpression(pattern: "^[A-Z]{3}[0-9]{3}$"),      // many states: ABC123
    ]

    /// All known North American plate formats (local + distant)
    private static let naFormats: [[NSRegularExpression]] = [localFormats, [
        try! NSRegularExpression(pattern: "^[0-9][A-Z]{3}[0-9]{3}$"), // CA: 1ABC234
        try! NSRegularExpression(pattern: "^[A-Z]{2}[0-9]{4}$"),      // some states: AB1234
        try! NSRegularExpression(pattern: "^[0-9]{3}[A-Z]{3}$"),      // some states: 123ABC
        try! NSRegularExpression(pattern: "^[0-9]{3}[A-Z]{4}$"),      // some states: 123ABCD
        try! NSRegularExpression(pattern: "^[A-Z]{4}[0-9]{3}$"),      // ON, QC: ABCD123
        try! NSRegularExpression(pattern: "^[0-9]{2}[A-Z]{3}[0-9]$"), // some states: 12ABC3
        try! NSRegularExpression(pattern: "^[A-Z][0-9]{3}[A-Z]{2}$"), // some states: A123BC
        try! NSRegularExpression(pattern: "^[0-9]{2}[A-Z]{2}[0-9]{2}$"), // some: 12AB34
    ]]

    private static let rejectList: Set<String> = [
        // Signs and infrastructure
        "POLICE", "PARKING", "SPEED", "LIMIT", "ENTER",
        "EXIT", "NORTH", "SOUTH", "EAST", "WEST",
        "TRUCK", "LEASE", "PLATE", "STATE", "STREET",
        "TOWAWAY", "RESERVED", "VISITOR", "PERMIT",
        "LOADING", "NOTICE", "VIOLAT", "YIELD", "MERGE",
        "CAUTION", "DANGER", "SCHOOL", "CAMPUS",
        "OFFICE", "CENTER", "CHURCH", "CHAPEL",
        // State names/slogans that OCR reads off plates
        "JERSEY", "GARDEN", "SHORE", "OCEAN", "EMPIRE",
        "LIBERTY", "ALOHA", "PEACH", "GOLDEN", "GRAND",
        "ISLAND", "VERDE", "FIRST", "TRUST", "SCENIC",
        "FOREVER", "FAMOUS", "SPIRIT", "NATURE",
        "VISIT", "PLACE", "YOURS", "ENJOY", "GREAT",
        "WONDER", "EXPLORE", "DISCOVER",
        // Car makes
        "ACURA", "BUICK", "CHEVY", "DODGE", "HONDA",
        "LEXUS", "MAZDA", "SCION", "SMART", "TESLA",
        "VOLVO", "ROVER", "TOYOTA", "NISSAN", "SUBARU",
        "SUZUKI", "GENESIS", "LINCOLN", "PONTIAC",
        "PORSCHE", "HYUNDAI", "SATURN", "ISUZU",
        "PAGANI", "BENTLEY", "MCLAREN", "MAYBACH",
        // Car models -- the main noise source
        "CIVIC", "CAMRY", "ACCORD", "ALTIMA", "SENTRA",
        "ROGUE", "ESCAPE", "FOCUS", "FUSION", "MALIBU",
        "CRUZE", "IMPALA", "SONATA", "ELANTRA", "TUCSON",
        "SANTA", "TIGUAN", "JETTA", "PASSAT", "ATLAS",
        "OUTBACK", "LEGACY", "PILOT", "ODYSSEY", "PRIUS",
        "SUPRA", "MIATA", "BRONCO", "RANGER", "TACOMA",
        "TUNDRA", "SIENNA", "AVALON", "DURANGO", "CHARGER",
        "PATRIOT", "COMPASS", "TERRAIN", "EQUINOX",
        "BLAZER", "TAHOE", "ENCORE", "ENVISION", "ENCLAVE",
        "KICKS", "MAXIMA", "MURANO", "VERSA", "ARMADA",
        "TITAN", "FORTE", "STINGER", "SELTOS", "TELLURIDE",
        "VENUE", "KONA", "IONIQ", "NIRO",
        "REGAL", "COUPE", "SEDAN", "TRUCK", "SPORT",
        "COBALT", "TIBURON", "INSIGHT", "CLARITY",
        "ELEMENT", "MAVERICK", "RAPTOR", "MUSTANG",
        "CROSSTREK",
        // Car model badges (alphanumeric)
        "ES350", "ES300", "IS350", "IS300", "IS250", "IS200",
        "GS350", "GS300", "LS500", "LS460", "RX350", "RX450",
        "NX350", "NX300", "UX250", "UX200", "GX460", "GX550",
        "LX600", "LX570", "LC500", "RC350", "RC300",
        "RAV4X", "CR1V2", "CRV12",
        "X5M50", "X3M40", "X7M60", "M340I", "M240I",
        "530I1", "540I1", "330I1", "340I1", "740I1",
        "AMG63", "AMG53", "AMG43",
        "RS500", "RS700", "GT500", "GT350", "GT40X",
        "SRT10", "SRT04",
        "TRD01", "NISMO",
        "TURBO", "SUPER", "POWER",
        "HYBRID", "ELECT",
        "4MATIC", "XDRIVE", "QUATTRO",
        "LIMIT1", "LIMIT2", "LIMIT3",
        // OCR misreads of model badges
        "6S330", "6S350", "6S300",
        "ES330",
        // Dealer/sticker/business text
        "10CCA", "1OCCA",
        "GR8UP", "GR8UE", "GR8UF",
        "DEALER",
        // OCR noise from specific vehicles/stickers at Moravian
        "TYLER", "TVLER", "TYLEI", "TVLEI", "IYLEI",
        "PTVLEI", "PTVLER", "TILEI",
        "PNLER", "FIIEI",
        "THOTHOR", "THORHOR", "THCTHOR", "THTHOR",
        "THORIOR", "OTHOR",
        // Car model names that are 5-7 letters (vanity-plate length)
        "FORESTER", "IMPREZA", "OUTBACK", "LEGACY",
        "WRANGLER", "COMPASS", "CHEROKEE",
        "COROLLA", "TUNDRA", "SIENNA",
        "SIERRA", "DENALI", "CANYON", "SAVANA",
        "ENCORE", "REGAL",
        // Dealer/sticker text that appears as 5-7 letters
        "CIOCCA", "IOCCA", "CLOCCA",
        "DUNKIN", "PROBARLY",
        // Common words
        "BLACK", "WHITE", "PEARL", "STEEL", "SILVER",
        "COLOR", "PRICE", "MODEL", "GRADE", "TOTAL",
        "MILES", "DRIVE", "BRAKE", "WHEEL", "MOTOR",
        "PARTS", "GLASS", "FLOOR", "POWER", "LIGHT",
        "HOURS", "HOURSOF", "BETWEEN", "PROHIBITED",
        "PRIVATE", "PRIVAT", "PRIVA", "PROPERTY", "TOWING",
        "MORAVIA", "MORAVAN", "MORAVIAN", "MOHAK", "MORAI",
        "UNIVERSITY", "INFORMATION",
        "DONOT", "IDONO", "RESUME",
        "ONEWAY", "ONEWWAY", "ONEWAYI", "ONEHAI", "ONEWAI",
        "CORNER", "SNOWLOT",
        "NOPARKING", "TOWAWAY",
        "WELCOME", "THANKS",
        "RECAL", "RRECAL", "FREGAI", "RRECAI",
        "PROBABL", "PROBAB",
        "VISITPA", "PENNSYL",
        "ISPROHI", "ETWEENT", "BETWEE",
        "KEYSTAR", "PAKAUNG", "PAKAINU",
        "LEICO", "ADASEULOT",
        "ARAING", "ENGORE",
        "FRAVA", "PRAVA", "RRALA", "FRALA",
        "DOUNKIN", "DDUNKN",
        "THOFHOR",
        "RREGAL",
        "LCURD", "VEMFA", "LVEHE", "UEAXD", "SESXO",
        "SBJBABU", "SISUBARU", "SISUBABU", "SISUSARU",
        "NOASTER", "NOAST", "SOBARD", "CAUEE", "RAGAL",
        "RAAVA", "THOROR", "THOKOR", "PRILOT", "LOUTTEN",
        "SUDARUS", "ICORITH", "LOORIT",
        "11000PM", "11100PM", "111000P", "770DAM",
        // Common OCR garbles of car badge text
        "SUBAAIU", "SBUBABL", "SBUBAR", "SSUBARU",
        "RREGAI", "FREGAI",
        "MYWAYTO", "MYWAITO",
    ]

    enum RejectionReason: String {
        case tooShort = "too_short"
        case tooLong = "too_long"
        case invalidChars = "invalid_chars"
        case noLetters = "no_letters"
        case noDigits = "no_digits"
        case tooFewLetters = "too_few_letters"
        case tooFewDigits = "too_few_digits"
        case noFormatMatch = "no_format_match"
        case rejectList = "reject_list"
        case badAspectRatio = "bad_aspect_ratio"
        case lowConfidence = "low_confidence"
    }

    static func looksLikePlate(_ text: String) -> Bool {
        return evaluatePlate(text) == nil
    }

    /// Returns nil if text looks like a plate, or the rejection reason if not.
    static func evaluatePlate(_ text: String) -> RejectionReason? {
        let cleaned = normalize(text)

        guard cleaned.count >= 5 else { return .tooShort }
        guard cleaned.count <= 7 else { return .tooLong }

        let range = NSRange(cleaned.startIndex..., in: cleaned)
        guard broadPattern.firstMatch(in: cleaned, range: range) != nil else { return .invalidChars }

        let letterCount = cleaned.filter(\.isLetter).count
        let digitCount = cleaned.filter(\.isNumber).count

        let isAllDigit = letterCount == 0 && digitCount == 6
        let isAllLetter = digitCount == 0 && letterCount >= 5

        if !isAllDigit && !isAllLetter {
            guard letterCount >= 2 else {
                return letterCount == 0 ? .noLetters : .tooFewLetters
            }
            guard digitCount >= 1 else {
                return .noDigits
            }
        }

        if rejectList.contains(cleaned) { return .rejectList }

        if cleaned.hasPrefix("ONE") || cleaned.hasPrefix("0NE") {
            return .rejectList
        }

        if cleaned.hasSuffix("AM") || cleaned.hasSuffix("PM") {
            let prefix = String(cleaned.dropLast(2))
            if prefix.allSatisfy(\.isNumber) { return .noFormatMatch }
        }

        if isAllLetter {
            return .noDigits
        }

        if !matchesAnyNAFormat(cleaned) {
            return .noFormatMatch
        }

        return nil
    }

    /// Returns true for all-letter plates (vanity). Currently disabled:
    /// non-format plates are rejected by evaluatePlate() before this matters.
    static func isVanityPlate(_ text: String) -> Bool {
        return false
    }

    static func matchesAnyNAFormat(_ text: String) -> Bool {
        let range = NSRange(text.startIndex..., in: text)
        return naFormats.flatMap { $0 }.contains { $0.firstMatch(in: text, range: range) != nil }
    }

    /// Returns true if the plate matches a PA/NJ/NY/DE/MD/CT format.
    /// Used to fast-track confirmation (1 frame instead of 2).
    static func isLocalFormat(_ text: String) -> Bool {
        let cleaned = normalize(text)
        let range = NSRange(cleaned.startIndex..., in: cleaned)
        return localFormats.contains { $0.firstMatch(in: cleaned, range: range) != nil }
    }

    static func isPennsylvaniaPlate(_ text: String) -> Bool {
        let cleaned = normalize(text)
        let range = NSRange(cleaned.startIndex..., in: cleaned)
        return paPattern.firstMatch(in: cleaned, range: range) != nil
    }

    /// Bounding box sanity check: plates are wider than tall.
    /// Relaxed lower bound (1.2) to handle angled reads from street parking.
    static func hasPlateAspectRatio(_ box: CGRect) -> Bool {
        guard box.height > 0 else { return false }
        let aspect = box.width / box.height
        return aspect > 1.2 && aspect < 10.0
    }

    static func normalize(_ text: String) -> String {
        var result = text.uppercased()
        for char: Character in [" ", "-", ".", "•", "·", "●", "°",
                                 "*", "#", "@", "©", "®", "™",
                                 "(", ")", "[", "]", "{", "}",
                                 ";", ":", "'", "\"", ",",
                                 "=", "+", "|", "!", "?",
                                 "$", "&", "~", "^", "<", ">",
                                 "/", "\\", "`", "→", "»", "«"] {
            result = result.replacingOccurrences(of: String(char), with: "")
        }
        result = transliterateCyrillic(result)
        return result
    }

    /// Characters that OCR commonly confuses with each other.
    static let confusables: [Character: Set<Character>] = [
        "K": ["N", "H", "X", "R"],
        "N": ["K", "H", "M"],
        "H": ["K", "N", "M", "A"],
        "M": ["W", "N", "L", "H"],
        "1": ["7", "I", "L"],
        "7": ["1", "T", "2"],
        "I": ["1", "L", "T"],
        "L": ["1", "I", "M", "C"],
        "0": ["O", "D", "Q"],
        "O": ["0", "D", "Q"],
        "D": ["0", "O", "P"],
        "Q": ["0", "O"],
        "8": ["B", "6", "3", "9"],
        "B": ["8", "6", "R", "D"],
        "3": ["8", "9"],
        "9": ["8", "3"],
        "5": ["S", "6"],
        "S": ["5", "X"],
        "2": ["Z", "7"],
        "Z": ["2"],
        "R": ["P", "B", "K", "A"],
        "P": ["R", "D", "F"],
        "W": ["M", "H"],
        "G": ["6", "C"],
        "6": ["G", "8", "B", "5"],
        "C": ["L", "G", "O"],
        "E": ["F", "W"],
        "F": ["E", "V", "P"],
        "V": ["Y", "F", "U"],
        "Y": ["V"],
        "X": ["K", "S"],
        "4": ["A"],
        "A": ["4", "H", "R"],
        "J": ["U"],
        "U": ["J", "V"],
        "T": ["7", "I"],
    ]

    /// Returns true if two characters are OCR-confusable.
    static func areConfusable(_ a: Character, _ b: Character) -> Bool {
        if a == b { return true }
        return confusables[a]?.contains(b) ?? false
    }

    /// Edit distance that treats confusable character swaps as half-cost.
    static func confusableDistance(_ a: String, _ b: String) -> Float {
        let ac = Array(a), bc = Array(b)
        let m = ac.count, n = bc.count
        var prev = (0...n).map { Float($0) }
        var curr = [Float](repeating: 0, count: n + 1)
        for i in 1...m {
            curr[0] = Float(i)
            for j in 1...n {
                if ac[i-1] == bc[j-1] {
                    curr[j] = prev[j-1]
                } else {
                    let subCost: Float = areConfusable(ac[i-1], bc[j-1]) ? 0.3 : 1.0
                    curr[j] = min(prev[j-1] + subCost, min(prev[j] + 1, curr[j-1] + 1))
                }
            }
            prev = curr
        }
        return prev[n]
    }

    /// OCR sometimes produces Cyrillic characters that look like Latin letters.
    private static let cyrillicToLatin: [Character: Character] = [
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H",
        "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
        "У": "Y", "Х": "X",
    ]

    private static func transliterateCyrillic(_ text: String) -> String {
        String(text.map { cyrillicToLatin[$0] ?? $0 })
    }
}
