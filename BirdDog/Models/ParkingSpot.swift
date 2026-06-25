import Foundation
import SwiftData

struct ParkingSpot: Codable, Identifiable, Sendable, Equatable {
    let id: String
    let lotId: String
    let number: Int
    var label: String?
    var sensorId: String?
    var latitude: Double?
    var longitude: Double?
}

@Model
final class ParkingSpotRecord {
    @Attribute(.unique) var spotId: String
    var lotId: String
    var number: Int
    var label: String?
    var sensorId: String?
    var latitude: Double?
    var longitude: Double?

    init(spotId: String, lotId: String, number: Int, label: String? = nil, sensorId: String? = nil, latitude: Double? = nil, longitude: Double? = nil) {
        self.spotId = spotId
        self.lotId = lotId
        self.number = number
        self.label = label
        self.sensorId = sensorId
        self.latitude = latitude
        self.longitude = longitude
    }

    var parkingSpot: ParkingSpot {
        ParkingSpot(id: spotId, lotId: lotId, number: number, label: label, sensorId: sensorId, latitude: latitude, longitude: longitude)
    }
}
