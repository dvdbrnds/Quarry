import Foundation

enum MatchMethod: String, Sendable, Codable {
    case exact
    case fuzzy
    case smart
    case beaconAssisted
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
    private let database: PlateDatabase

    private var wildcardZones: Set<String> {
        AppSettings.shared.wildcardZoneSet
    }

    init() {
        self.database = PlateDatabase.shared
    }

    func check(plate: String, currentLot: String? = nil) -> PlateStatus {
        checkDetailed(plate: plate, currentLot: currentLot).status
    }

    func checkDetailed(plate: String, currentLot: String? = nil) -> AuthResult {
        guard !database.isEmpty else {
            return AuthResult(status: .unchecked, matchMethod: .none, matchedPlate: plate)
        }

        let normalized = PlatePatternMatcher.normalize(plate)

        if let record = database.lookup(normalizedPlate: normalized) {
            return AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .exact, matchedPlate: record.plateNormalized)
        }

        if let record = database.fuzzyLookup(normalizedPlate: normalized) {
            return AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .fuzzy, matchedPlate: record.plateNormalized)
        }

        if let record = database.smartLookup(normalizedPlate: normalized) {
            return AuthResult(status: statusFor(record, currentLot: currentLot), matchMethod: .smart, matchedPlate: record.plateNormalized)
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
            issuedDate: record.issuedDate
        )

        if record.permitStatus != "Valid" {
            return .expired(permit: info)
        }

        if let expiration = record.expirationDate, expiration < Date() {
            return .expired(permit: info)
        }

        if let currentLot, !record.lotZone.isEmpty,
           !lotMatches(permitZone: record.lotZone, currentLot: currentLot) {
            return .wrongLot(permit: info, expectedLot: record.lotZone, actualLot: currentLot)
        }

        return .authorized(permit: info)
    }

    private func lotMatches(permitZone: String, currentLot: String) -> Bool {
        let normalizedPermit = permitZone.trimmingCharacters(in: .whitespaces).uppercased()
        let normalizedLot = currentLot.trimmingCharacters(in: .whitespaces).uppercased()

        if normalizedPermit == normalizedLot { return true }

        if wildcardZones.contains(normalizedPermit) { return true }

        if normalizedPermit.contains(",") {
            let zones = normalizedPermit.split(separator: ",").map {
                $0.trimmingCharacters(in: .whitespaces)
            }
            if zones.contains(normalizedLot) { return true }
        }

        return false
    }
}
