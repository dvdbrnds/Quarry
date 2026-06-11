import Foundation
import SwiftData

@Model
final class PermitRecord {
    @Attribute(.unique) var plateNormalized: String
    var plateRaw: String
    var plateState: String
    var ownerName: String
    var permitNumber: String
    var permitType: String
    var permitStatus: String
    var lotZone: String
    var vehicleDescription: String
    var issuedDate: Date
    var expirationDate: Date?
    var importedAt: Date

    init(
        plateNormalized: String,
        plateRaw: String,
        plateState: String,
        ownerName: String,
        permitNumber: String,
        permitType: String,
        permitStatus: String,
        lotZone: String,
        vehicleDescription: String,
        issuedDate: Date,
        expirationDate: Date? = nil,
        importedAt: Date = Date()
    ) {
        self.plateNormalized = plateNormalized
        self.plateRaw = plateRaw
        self.plateState = plateState
        self.ownerName = ownerName
        self.permitNumber = permitNumber
        self.permitType = permitType
        self.permitStatus = permitStatus
        self.lotZone = lotZone
        self.vehicleDescription = vehicleDescription
        self.issuedDate = issuedDate
        self.expirationDate = expirationDate
        self.importedAt = importedAt
    }
}
