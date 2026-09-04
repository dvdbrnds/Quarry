import Foundation
import SwiftData

@MainActor
final class PlateDatabase {
    private static var _shared: PlateDatabase?

    static var isReady: Bool { _shared != nil }

    static var shared: PlateDatabase {
        if let existing = _shared { return existing }
        let db = PlateDatabase(container: createContainer())
        _shared = db
        return db
    }

    /// Pre-warm the shared instance with a container built on a background thread.
    static func warmUp(container: ModelContainer) {
        guard _shared == nil else { return }
        _shared = PlateDatabase(container: container)
    }

    let container: ModelContainer

    var context: ModelContext {
        container.mainContext
    }

    nonisolated static func createContainer() -> ModelContainer {
        do {
            let schema = Schema([PermitRecord.self, ParkingLotRecord.self, ParkingSpotRecord.self, PendingTicket.self])
            let config = ModelConfiguration(schema: schema)
            return try ModelContainer(for: schema, configurations: [config])
        } catch {
            print("Database init failed, deleting corrupt store and retrying: \(error)")
            deleteStoreFiles()
            do {
                let schema = Schema([PermitRecord.self, ParkingLotRecord.self, ParkingSpotRecord.self, PendingTicket.self])
                let config = ModelConfiguration(schema: schema)
                return try ModelContainer(for: schema, configurations: [config])
            } catch {
                fatalError("Failed to create permit database after store reset: \(error)")
            }
        }
    }

    private init(container: ModelContainer) {
        self.container = container
    }

    private static let retentionYears = 10

    func pruneExpiredPermits() {
        let calendar = Calendar.current
        guard let cutoff = calendar.date(byAdding: .year, value: -Self.retentionYears, to: Date()) else { return }
        let predicate = #Predicate<PermitRecord> { record in
            record.expirationDate != nil && record.expirationDate! < cutoff
        }
        var descriptor = FetchDescriptor<PermitRecord>(predicate: predicate)
        descriptor.fetchLimit = 500
        guard let expired = try? context.fetch(descriptor), !expired.isEmpty else { return }
        for record in expired {
            context.delete(record)
        }
        try? context.save()
        recordsByLengthCache.removeAll()
        print("Pruned \(expired.count) permits expired before \(cutoff)")
    }

    nonisolated private static func deleteStoreFiles() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        guard let dir = appSupport else { return }
        let extensions = ["store", "store-shm", "store-wal"]
        for ext in extensions {
            let url = dir.appendingPathComponent("default.\(ext)")
            try? FileManager.default.removeItem(at: url)
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
                expirationDate: permit.parsedExpirationDate,
                hcStatus: permit.hcStatus ?? "none",
                hcExpiry: permit.parsedHcExpiry
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

        // 1. Transposition: swap each adjacent pair and try exact only.
        //    (Transposition + fuzzy = 3 cumulative changes, too loose.)
        if chars.count >= 5 {
            for i in 0..<(chars.count - 1) {
                var swapped = chars
                swapped.swapAt(i, i + 1)
                let variant = String(swapped)
                if let record = lookup(normalizedPlate: variant) { return record }
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
            // Fuzzy on substrings — limit to first and last 7-char windows only
            if chars.count >= 7 {
                let first7 = String(chars[0..<7])
                if let record = fuzzyLookup(normalizedPlate: first7) { return record }
                let last7 = String(chars[(chars.count - 7)...])
                if last7 != first7, let record = fuzzyLookup(normalizedPlate: last7) { return record }
            }
        }

        // 3. Truncation recovery: if 5-6 chars, try prepending/appending common leading chars.
        //    The 40-degree camera angle often clips the first or last character.
        //    Only use exact lookup here — fuzzyLookup per variant is too expensive
        //    (33 variants × ~200 queries each = 6,600 DB queries on main thread).
        if chars.count >= 5 && chars.count <= 6 {
            let prefixes: [Character] = ["L", "M", "K", "N", "H", "Z", "J", "A",
                                          "G", "V", "W", "R", "B", "C", "D", "E",
                                          "F", "S", "T", "P", "1", "I", "0"]
            let suffixes: [Character] = ["1", "7", "0", "8", "4", "3", "9", "2", "6", "5"]
            for prefix in prefixes {
                let variant = String(prefix) + plate
                if let record = lookup(normalizedPlate: variant) { return record }
            }
            for suffix in suffixes {
                let variant = plate + String(suffix)
                if let record = lookup(normalizedPlate: variant) { return record }
            }
            // Only try fuzzy on the most likely truncation candidates (first 5 prefixes)
            for prefix in prefixes.prefix(5) {
                let variant = String(prefix) + plate
                if let record = fuzzyLookup(normalizedPlate: variant) { return record }
            }
        }

        // 4. Edit-distance scan: scan cached DB plates of the same length (5-7 chars).
        //    Tight threshold: confusableDistance <= 0.7 means at most 2 confusable
        //    character swaps (2 × 0.3 = 0.6). Combined with max 1 digit difference,
        //    this catches genuine OCR errors without matching unrelated plates.
        //    Only runs if the cache is already warm (avoids fetching all records
        //    on the main thread during active scanning).
        if chars.count >= 5 && chars.count <= 7, !recordsByLengthCache.isEmpty {
            let plateDigits = plate.filter(\.isNumber)
            let allPlates = recordsByLengthCache[chars.count] ?? []
            var bestRecord: PermitRecord?
            var bestDist: Float = 0.71
            for record in allPlates {
                let recDigits = record.plateNormalized.filter(\.isNumber)
                let digitDiffs: Int
                if recDigits.count == plateDigits.count {
                    digitDiffs = zip(plateDigits, recDigits).filter { $0 != $1 }.count
                } else {
                    digitDiffs = abs(recDigits.count - plateDigits.count)
                }
                guard digitDiffs <= 1 else { continue }
                let dist = PlatePatternMatcher.confusableDistance(plate, record.plateNormalized)
                if dist < bestDist {
                    bestDist = dist
                    bestRecord = record
                }
            }
            if let bestRecord, bestDist <= 0.7 {
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

    /// Pre-warm the length cache so smartLookup's edit-distance scan
    /// doesn't trigger a full DB fetch during active scanning.
    func warmLengthCache() {
        guard recordsByLengthCache.isEmpty else { return }
        _ = allRecordsOfLength(7)
    }

    /// Upsert a single `PermitRecord` keyed on `entry.plateNormalized`.
    /// Updates all fields if a record already exists; inserts otherwise.
    func upsertRecord(_ entry: PermitEntry) throws {
        let plate = entry.plateNormalized.trimmingCharacters(in: .whitespaces)
        guard !plate.isEmpty else { return }

        if let existing = lookup(normalizedPlate: plate) {
            existing.plateRaw = entry.plateRaw
            existing.plateState = entry.plateState
            existing.ownerName = entry.ownerName
            existing.permitNumber = entry.permitNumber
            existing.permitType = entry.permitType
            existing.permitStatus = entry.permitStatus
            existing.lotZone = entry.lotZone
            existing.vehicleDescription = entry.vehicleDescription
            existing.issuedDate = entry.parsedIssuedDate
            existing.expirationDate = entry.parsedExpirationDate
            existing.beaconId = entry.beaconId
            existing.hcStatus = entry.hcStatus ?? "none"
            existing.hcExpiry = entry.parsedHcExpiry
            existing.importedAt = Date()
        } else {
            let record = PermitRecord(
                plateNormalized: plate,
                plateRaw: entry.plateRaw,
                plateState: entry.plateState,
                ownerName: entry.ownerName,
                permitNumber: entry.permitNumber,
                permitType: entry.permitType,
                permitStatus: entry.permitStatus,
                lotZone: entry.lotZone,
                vehicleDescription: entry.vehicleDescription,
                issuedDate: entry.parsedIssuedDate,
                expirationDate: entry.parsedExpirationDate,
                beaconId: entry.beaconId,
                hcStatus: entry.hcStatus ?? "none",
                hcExpiry: entry.parsedHcExpiry
            )
            context.insert(record)
        }
        try context.save()
        recordsByLengthCache.removeAll()
    }

    /// Delete a record by normalised plate, if it exists.
    func deleteRecord(normalizedPlate: String) {
        guard let record = lookup(normalizedPlate: normalizedPlate) else { return }
        context.delete(record)
        try? context.save()
        recordsByLengthCache.removeAll()
    }

    func deleteAll() throws {
        try context.delete(model: PermitRecord.self)
        try context.save()
        recordsByLengthCache.removeAll()
    }

    /// Find all records belonging to a given permit (by permitNumber).
    func recordsForPermitNumber(_ permitNumber: String) -> [PermitRecord] {
        let target = permitNumber
        var descriptor = FetchDescriptor<PermitRecord>(
            predicate: #Predicate<PermitRecord> { record in
                record.permitNumber == target
            }
        )
        descriptor.fetchLimit = 50
        return (try? context.fetch(descriptor)) ?? []
    }

    func totalCount() -> Int {
        (try? context.fetchCount(FetchDescriptor<PermitRecord>())) ?? 0
    }

    func validCount() -> Int {
        let all = (try? context.fetch(FetchDescriptor<PermitRecord>())) ?? []
        return all.filter {
            let s = $0.permitStatus.trimmingCharacters(in: .whitespaces).lowercased()
            return s == "valid" || s == "active"
        }.count
    }

    func expiredCount() -> Int {
        let all = (try? context.fetch(FetchDescriptor<PermitRecord>())) ?? []
        return all.filter {
            let s = $0.permitStatus.trimmingCharacters(in: .whitespaces).lowercased()
            return s == "expired" || s == "revoked" || s == "suspended"
        }.count
    }

    var isEmpty: Bool {
        totalCount() == 0
    }

    // MARK: - Pending Ticket Queue

    func saveContext() throws {
        try context.save()
    }

    func savePendingTicket(_ ticket: PendingTicket) throws {
        context.insert(ticket)
        try context.save()
    }

    func pendingTickets() -> [PendingTicket] {
        let descriptor = FetchDescriptor<PendingTicket>(
            predicate: #Predicate<PendingTicket> { !$0.uploaded }
        )
        return (try? context.fetch(descriptor)) ?? []
    }

    func markTicketUploaded(_ ticket: PendingTicket) {
        ticket.uploaded = true
        try? context.save()
    }

    func deletePendingTicket(_ ticket: PendingTicket) {
        context.delete(ticket)
        try? context.save()
    }

    /// Number of tickets already issued for a given plate (uploaded + pending).
    func offenseCount(forPlate plate: String) -> Int {
        let normalized = plate.uppercased().replacingOccurrences(of: " ", with: "")
        let descriptor = FetchDescriptor<PendingTicket>(
            predicate: #Predicate<PendingTicket> { $0.plate == normalized }
        )
        return (try? context.fetchCount(descriptor)) ?? 0
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
    let beaconId: String?
    let hcStatus: String?
    let hcExpiry: String?

    private static let dateFormatters: [DateFormatter] = {
        let formats = [
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm:ssZ",
            "yyyy-MM-dd'T'HH:mm:ssXXXXX",
            "yyyy-MM-dd",
        ]
        return formats.map { format in
            let f = DateFormatter()
            f.dateFormat = format
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone.current
            return f
        }
    }()

    private static func parseDate(_ value: String) -> Date? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        for formatter in dateFormatters {
            if let date = formatter.date(from: trimmed) { return date }
        }
        // ISO8601 with fractional seconds
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: trimmed) { return date }
        iso.formatOptions = [.withInternetDateTime]
        return iso.date(from: trimmed)
    }

    var parsedIssuedDate: Date {
        Self.parseDate(issuedDate) ?? .distantPast
    }

    var parsedExpirationDate: Date? {
        guard let exp = expirationDate else { return nil }
        return Self.parseDate(exp)
    }

    var parsedHcExpiry: Date? {
        guard let hc = hcExpiry else { return nil }
        return Self.parseDate(hc)
    }
}
