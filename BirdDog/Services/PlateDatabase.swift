import Foundation
import SwiftData

@MainActor
final class PlateDatabase {
    static let shared = PlateDatabase()

    let container: ModelContainer

    var context: ModelContext {
        container.mainContext
    }

    private static let seedVersionKey = "PlateDatabase.seedVersion"

    private init() {
        do {
            let schema = Schema([PermitRecord.self, ParkingLotRecord.self])
            let config = ModelConfiguration(schema: schema)
            container = try ModelContainer(for: schema, configurations: [config])
        } catch {
            print("Database init failed, deleting corrupt store and retrying: \(error)")
            Self.deleteStoreFiles()
            do {
                let schema = Schema([PermitRecord.self, ParkingLotRecord.self])
                let config = ModelConfiguration(schema: schema)
                container = try ModelContainer(for: schema, configurations: [config])
            } catch {
                fatalError("Failed to create permit database after store reset: \(error)")
            }
        }
        seedIfNeeded()
    }

    private static func deleteStoreFiles() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        guard let dir = appSupport else { return }
        let extensions = ["store", "store-shm", "store-wal"]
        for ext in extensions {
            let url = dir.appendingPathComponent("default.\(ext)")
            try? FileManager.default.removeItem(at: url)
        }
    }

    func seedIfNeeded() {
        let url: URL? = LocalDataProvider.shared.permitDataURL()
        guard let url else { return }

        let fileDate = (try? FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as? Date)?
            .timeIntervalSince1970 ?? 0
        let seedVersion = String(format: "%.0f", fileDate)

        let lastSeed = UserDefaults.standard.string(forKey: Self.seedVersionKey) ?? ""
        guard lastSeed != seedVersion else { return }

        do {
            let data = try Data(contentsOf: url)
            let payload = try JSONDecoder().decode(PermitPayload.self, from: data)

            try deleteAll()
            _ = try seedFromPayload(payload)
            UserDefaults.standard.set(seedVersion, forKey: Self.seedVersionKey)
        } catch {
            print("Failed to seed database: \(error)")
        }
    }

    struct SeedResult {
        let inserted: Int
        let skippedEmpty: Int
        let skippedDuplicate: Int
    }

    @discardableResult
    func seedFromPayload(_ payload: PermitPayload) throws -> Int {
        let result = try seedFromPayloadDetailed(payload)
        return result.inserted
    }

    func seedFromPayloadDetailed(_ payload: PermitPayload) throws -> SeedResult {
        var inserted = 0
        var skippedEmpty = 0
        var skippedDuplicate = 0
        var seenPlates = Set<String>()

        for permit in payload.permits {
            let normalized = permit.plateNormalized.trimmingCharacters(in: .whitespaces)
            if normalized.isEmpty {
                skippedEmpty += 1
                continue
            }
            if seenPlates.contains(normalized) {
                skippedDuplicate += 1
                continue
            }
            seenPlates.insert(normalized)

            let record = PermitRecord(
                plateNormalized: normalized,
                plateRaw: permit.plateRaw,
                plateState: permit.plateState,
                ownerName: permit.ownerName,
                permitNumber: permit.permitNumber,
                permitType: permit.permitType,
                permitStatus: permit.permitStatus,
                lotZone: permit.lotZone,
                vehicleDescription: permit.vehicleDescription,
                issuedDate: permit.parsedIssuedDate,
                expirationDate: permit.parsedExpirationDate
            )
            context.insert(record)
            inserted += 1
        }
        try context.save()

        recordsByLengthCache.removeAll()

        if skippedEmpty > 0 || skippedDuplicate > 0 {
            print("Import: \(inserted) inserted, \(skippedEmpty) empty plates skipped, \(skippedDuplicate) duplicates skipped")
        }

        return SeedResult(inserted: inserted, skippedEmpty: skippedEmpty, skippedDuplicate: skippedDuplicate)
    }

    func lookup(normalizedPlate: String) -> PermitRecord? {
        let plate = normalizedPlate
        var descriptor = FetchDescriptor<PermitRecord>(
            predicate: #Predicate<PermitRecord> { record in
                record.plateNormalized == plate
            }
        )
        descriptor.fetchLimit = 1
        return try? context.fetch(descriptor).first
    }

    func fuzzyLookup(normalizedPlate: String) -> PermitRecord? {
        for (i, char) in normalizedPlate.enumerated() {
            guard let alts = PlatePatternMatcher.confusables[char] else { continue }
            for alt in alts {
                var chars = Array(normalizedPlate)
                chars[i] = alt
                let variant = String(chars)
                if let record = lookup(normalizedPlate: variant) {
                    return record
                }
            }
        }

        if normalizedPlate.count >= 5 {
            let chars = Array(normalizedPlate)
            for i in 0..<chars.count {
                guard let alts = PlatePatternMatcher.confusables[chars[i]] else { continue }
                for alt1 in alts {
                    for j in (i+1)..<chars.count {
                        guard let alts2 = PlatePatternMatcher.confusables[chars[j]] else { continue }
                        for alt2 in alts2 {
                            var modified = chars
                            modified[i] = alt1
                            modified[j] = alt2
                            let variant = String(modified)
                            if let record = lookup(normalizedPlate: variant) {
                                return record
                            }
                        }
                    }
                }
            }
        }

        return nil
    }

    /// Aggressive lookup that tries transpositions, substring extraction,
    /// and truncation recovery. Called after exact + fuzzyLookup both fail.
    func smartLookup(normalizedPlate: String) -> PermitRecord? {
        let plate = normalizedPlate
        let chars = Array(plate)

        // 1. Transposition: swap each adjacent pair and try exact + fuzzy
        if chars.count >= 5 {
            for i in 0..<(chars.count - 1) {
                var swapped = chars
                swapped.swapAt(i, i + 1)
                let variant = String(swapped)
                if let record = lookup(normalizedPlate: variant) { return record }
                if let record = fuzzyLookup(normalizedPlate: variant) { return record }
            }
        }

        // 2. Substring extraction: if 8+ chars, try every 7-char then 6-char then 5-char window
        if chars.count >= 8 {
            for targetLen in stride(from: 7, through: 5, by: -1) {
                for start in 0...(chars.count - targetLen) {
                    let sub = String(chars[start..<(start + targetLen)])
                    if let record = lookup(normalizedPlate: sub) { return record }
                }
            }
            // Also try fuzzy on substrings (more expensive, limit to 7-char)
            for start in 0...(chars.count - 7) {
                let sub = String(chars[start..<(start + 7)])
                if let record = fuzzyLookup(normalizedPlate: sub) { return record }
            }
        }

        // 3. Truncation recovery: if 5-6 chars, try prepending/appending common leading chars
        if chars.count >= 5 && chars.count <= 6 {
            let prefixes: [Character] = ["L", "M", "K", "N", "H", "Z", "1", "I"]
            let suffixes: [Character] = ["1", "7", "0", "8", "4"]
            for prefix in prefixes {
                let variant = String(prefix) + plate
                if let record = lookup(normalizedPlate: variant) { return record }
                if let record = fuzzyLookup(normalizedPlate: variant) { return record }
            }
            for suffix in suffixes {
                let variant = plate + String(suffix)
                if let record = lookup(normalizedPlate: variant) { return record }
                if let record = fuzzyLookup(normalizedPlate: variant) { return record }
            }
        }

        // 4. Edit-distance scan: scan all DB plates of the same length (5-7 chars).
        //    Require confusableDistance <= 1.5 to catch multi-char OCR errors
        //    (H/M, P/R, N/M, 5/S combos) while avoiding false positives.
        if chars.count >= 5 && chars.count <= 7 {
            let plateDigits = plate.filter(\.isNumber)
            let allPlates = allRecordsOfLength(chars.count)
            var bestRecord: PermitRecord?
            var bestDist: Float = 1.6
            for record in allPlates {
                let recDigits = record.plateNormalized.filter(\.isNumber)
                let digitDiffs: Int
                if recDigits.count == plateDigits.count {
                    digitDiffs = zip(plateDigits, recDigits).filter { $0 != $1 }.count
                } else {
                    digitDiffs = abs(recDigits.count - plateDigits.count)
                }
                guard digitDiffs <= 2 else { continue }
                let dist = PlatePatternMatcher.confusableDistance(plate, record.plateNormalized)
                if dist < bestDist {
                    bestDist = dist
                    bestRecord = record
                }
            }
            if let bestRecord, bestDist <= 1.5 {
                return bestRecord
            }
        }

        return nil
    }

    private var recordsByLengthCache: [Int: [PermitRecord]] = [:]

    /// Fetch all permit records whose plate has exactly the given length.
    /// Results are cached until the next deleteAll/seed cycle.
    private func allRecordsOfLength(_ length: Int) -> [PermitRecord] {
        if let cached = recordsByLengthCache[length] { return cached }
        let descriptor = FetchDescriptor<PermitRecord>()
        let all = (try? context.fetch(descriptor)) ?? []
        let grouped = Dictionary(grouping: all, by: { $0.plateNormalized.count })
        recordsByLengthCache = grouped
        return grouped[length] ?? []
    }

    func deleteAll() throws {
        try context.delete(model: PermitRecord.self)
        try context.save()
        recordsByLengthCache.removeAll()
    }

    func totalCount() -> Int {
        (try? context.fetchCount(FetchDescriptor<PermitRecord>())) ?? 0
    }

    func validCount() -> Int {
        let predicate = #Predicate<PermitRecord> { $0.permitStatus == "Valid" }
        return (try? context.fetchCount(FetchDescriptor<PermitRecord>(predicate: predicate))) ?? 0
    }

    func expiredCount() -> Int {
        let predicate = #Predicate<PermitRecord> { $0.permitStatus == "Expired" }
        return (try? context.fetchCount(FetchDescriptor<PermitRecord>(predicate: predicate))) ?? 0
    }

    var isEmpty: Bool {
        totalCount() == 0
    }

    func allRecords(matching search: String = "") -> [PermitRecord] {
        var descriptor = FetchDescriptor<PermitRecord>(
            sortBy: [SortDescriptor(\.issuedDate, order: .reverse)]
        )
        if !search.isEmpty {
            let term = search.uppercased()
            descriptor.predicate = #Predicate<PermitRecord> { record in
                record.plateNormalized.contains(term) ||
                record.ownerName.localizedStandardContains(term) ||
                record.permitNumber.localizedStandardContains(term)
            }
        }
        return (try? context.fetch(descriptor)) ?? []
    }
}

struct PermitPayload: Decodable {
    let permits: [PermitEntry]
}

struct PermitEntry: Decodable {
    let plateNormalized: String
    let plateRaw: String
    let plateState: String
    let ownerName: String
    let permitNumber: String
    let permitType: String
    let permitStatus: String
    let lotZone: String
    let vehicleDescription: String
    let issuedDate: String
    let expirationDate: String?

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    var parsedIssuedDate: Date {
        Self.dateFormatter.date(from: issuedDate) ?? .distantPast
    }

    var parsedExpirationDate: Date? {
        guard let exp = expirationDate, !exp.isEmpty else { return nil }
        return Self.dateFormatter.date(from: exp)
    }
}
