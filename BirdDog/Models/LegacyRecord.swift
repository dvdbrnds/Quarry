import Foundation
import SwiftData

@Model
final class LegacyRecord {
    @Attribute(.unique) var plateNormalized: String
    var plateState: String
    var ownerName: String
    var permitNumber: String
    var permitType: String
    var permitStatus: String
    var lotZone: String
    var vehicleDescription: String
    var source: String

    init(
        plateNormalized: String,
        plateState: String = "",
        ownerName: String = "",
        permitNumber: String = "",
        permitType: String = "",
        permitStatus: String = "",
        lotZone: String = "",
        vehicleDescription: String = "",
        source: String = "omnigo"
    ) {
        self.plateNormalized = plateNormalized
        self.plateState = plateState
        self.ownerName = ownerName
        self.permitNumber = permitNumber
        self.permitType = permitType
        self.permitStatus = permitStatus
        self.lotZone = lotZone
        self.vehicleDescription = vehicleDescription
        self.source = source
    }
}
