import Foundation

enum MatchMethod: String, Sendable, Codable {
    case exact
    case fuzzy
    case smart
    case none
}

struct AuthResult: Sendable {
    let status: PlateStatus
    let matchMethod: MatchMethod
    let matchedPlate: String
}

protocol PlateCheckable: Sendable {
    @MainActor func check(plate: String, currentLot: String?) -> PlateStatus
}

@MainActor
final class PlateAuthService: PlateCheckable {
    private var database: PlateDatabase { PlateDatabase.shared }

    private var wildcardZones: Set<String> {
        AppSettings.shared.wildcardZoneSet
    }

    /// HoundDog uses "active"; legacy BirdDog JSON used "Valid".
    private static let activeStatuses: Set<String> = ["active", "valid"]

    private static let easternCalendar: Calendar = {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        return cal
    }()

    private var lookupCache: [String: AuthResult] = [:]
    private var cacheTimestamp: Date = .distantPast
    private static let cacheTTL: TimeInterval = 30.0

    init() {}

    func clearCache() {
        lookupCache.removeAll()
        cacheTimestamp = .distantPast
    }

    func check(plate: String, currentLot: String? = nil) -> PlateStatus {
        checkDetailed(plate: plate, currentLot: currentLot).status
    }

    func checkDetailed(plate: String, currentLot: String? = nil) -> AuthResult {
        guard PlateDatabase.isReady, !database.isEmpty else {
            return AuthResult(status: .unchecked, matchMethod: .none, matchedPlate: plate)
        }

        let normalized = PlatePatternMatcher.normalize(plate)
        let cacheKey = "\(normalized)|\(currentLot ?? "")"

        if Date().timeIntervalSince(cacheTimestamp) > Self.cacheTTL {
            lookupCache.removeAll()
            cacheTimestamp = Date()
        }
        if let cached = lookupCache[cacheKey] {
            return cached
        }

        let result: AuthResult
        if let record = database.lookup(normalizedPlate: normalized) {
            result = AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .exact, matchedPlate: record.plateNormalized)
        } else if let record = database.fuzzyLookup(normalizedPlate: normalized) {
            result = AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .fuzzy, matchedPlate: record.plateNormalized)
        } else if let record = database.smartLookup(normalizedPlate: normalized) {
            result = AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .smart, matchedPlate: record.plateNormalized)
        } else {
            result = AuthResult(status: .unknown, matchMethod: .none, matchedPlate: normalized)
        }

        lookupCache[cacheKey] = result
        return result
    }

    /// Lightweight check — exact + fuzzy only, skips expensive smartLookup.
    /// Used for speculative checks (instant-confirm, alternate pre-verification)
    /// where a miss is acceptable and will be caught by the full check later.
    func quickCheck(plate: String, currentLot: String? = nil) -> AuthResult {
        guard PlateDatabase.isReady, !database.isEmpty else {
            return AuthResult(status: .unchecked, matchMethod: .none, matchedPlate: plate)
        }

        let normalized = PlatePatternMatcher.normalize(plate)
        let cacheKey = "\(normalized)|\(currentLot ?? "")"

        if Date().timeIntervalSince(cacheTimestamp) > Self.cacheTTL {
            lookupCache.removeAll()
            cacheTimestamp = Date()
        }
        if let cached = lookupCache[cacheKey] {
            return cached
        }

        if let record = database.lookup(normalizedPlate: normalized) {
            let result = AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .exact, matchedPlate: record.plateNormalized)
            lookupCache[cacheKey] = result
            return result
        }
        if let record = database.fuzzyLookup(normalizedPlate: normalized) {
            let result = AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .fuzzy, matchedPlate: record.plateNormalized)
            lookupCache[cacheKey] = result
            return result
        }

        return AuthResult(status: .unknown, matchMethod: .none, matchedPlate: normalized)
    }

    private func statusFor(_ record: PermitRecord, currentLot: String?) -> PlateStatus {
        let info = PermitInfo(
            ownerName: record.ownerName,
            permitNumber: record.permitNumber,
            permitType: record.permitType,
            permitStatus: record.permitStatus,
            lotZone: record.lotZone,
            vehicleDescription: record.vehicleDescription,
            plateState: record.plateState,
            issuedDate: record.issuedDate,
            hcStatus: record.hcStatus,
            hcExpiry: record.hcExpiry
        )

        // Vehicle tag (known vehicle, no permit) — always show as "tag only"
        if record.permitType.lowercased() == "vehicle_tag" {
            return .tagOnly(permit: info)
        }

        let statusKey = record.permitStatus.trimmingCharacters(in: .whitespaces).lowercased()
        let now = Date()

        // Not an active/valid permit (revoked, suspended, expired status, etc.)
        if !Self.activeStatuses.contains(statusKey) {
            return .expired(permit: info)
        }

        // Not yet valid for this date
        if record.issuedDate > now {
            return .expired(permit: info)
        }

        // Past end date
        if let expiration = record.expirationDate, expiration < Self.easternCalendar.startOfDay(for: now) {
            return .expired(permit: info)
        }

        // Guest permits can park in any lot at any time during their registration
        if record.permitType.lowercased() == "student_guest" {
            return .authorized(permit: info)
        }

        // Lot access: check zone match, diversions, and time-of-day schedule
        if let currentLot {
            let lot = GeofenceService.shared.lots.first(where: { $0.name == currentLot })

            // After hours: any active permit holder can park in any lot
            if let lot, !lot.accessSchedule.isEmpty, !lot.isWithinEnforcementHours() {
                return .authorized(permit: info)
            }

            let zoneMatch = record.lotZone.isEmpty || lotMatches(permitZone: record.lotZone, currentLot: currentLot)

            if !zoneMatch {
                // Check active diversion (closed lot → this lot)
                let diversions = HoundDogSyncService.shared.activeDiversions
                let normalizedCurrent = Self.normalizeLotCode(currentLot)
                let permitZones = record.lotZone
                    .split(separator: ",")
                    .map { Self.normalizeLotCode(String($0)) }
                    .filter { !$0.isEmpty }
                let isDiverted = permitZones.contains { zone in
                    diversions[zone] == normalizedCurrent
                }

                // Check if the lot's access schedule explicitly allows this permit type
                // right now (e.g., resident students in commuter lots after hours)
                let allowedBySchedule: Bool = {
                    guard let lot, !lot.accessSchedule.isEmpty else { return false }
                    return lot.isPermitTypeAllowed(record.permitType)
                }()

                if !isDiverted && !allowedBySchedule {
                    return .wrongLot(permit: info, expectedLot: record.lotZone, actualLot: currentLot)
                }
            } else {
                // Zone matches, but still check time-of-day restrictions
                if let lot, !lot.accessSchedule.isEmpty,
                   !lot.isPermitTypeAllowed(record.permitType) {
                    return .wrongLot(permit: info, expectedLot: "\(currentLot) (time-restricted)", actualLot: currentLot)
                }
            }
        }

        // Allowed to park in this lot at this time
        return .authorized(permit: info)
    }

    private func lotMatches(permitZone: String, currentLot: String) -> Bool {
        let normalizedLot = Self.normalizeLotCode(currentLot)
        guard !normalizedLot.isEmpty else { return false }

        if wildcardZones.contains(Self.normalizeLotCode(permitZone)) { return true }

        let zones = permitZone
            .split(separator: ",")
            .map { Self.normalizeLotCode(String($0)) }
            .filter { !$0.isEmpty }

        if zones.isEmpty {
            return Self.normalizeLotCode(permitZone) == normalizedLot
        }

        return zones.contains(normalizedLot)
    }

    /// HoundDog uses codes like "A"; bundled BirdDog data used "LOT A".
    static func normalizeLotCode(_ raw: String) -> String {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if s.hasPrefix("LOT ") {
            s = String(s.dropFirst(4)).trimmingCharacters(in: .whitespaces)
        }
        return s
    }
}
