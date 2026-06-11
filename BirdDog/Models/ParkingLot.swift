import Foundation
import SwiftData
import CoreLocation

struct Coordinate: Codable, Sendable, Equatable {
    let latitude: Double
    let longitude: Double

    var clLocation: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }
}

struct ParkingLot: Codable, Identifiable, Sendable, Equatable {
    let id: String
    let name: String
    let boundary: [Coordinate]

    /// Ray-casting point-in-polygon test. O(n) where n = corner count.
    func contains(_ point: CLLocationCoordinate2D) -> Bool {
        let n = boundary.count
        guard n >= 3 else { return false }

        var inside = false
        var j = n - 1
        for i in 0..<n {
            let pi = boundary[i]
            let pj = boundary[j]

            if (pi.latitude > point.latitude) != (pj.latitude > point.latitude),
               point.longitude < (pj.longitude - pi.longitude) * (point.latitude - pi.latitude) / (pj.latitude - pi.latitude) + pi.longitude {
                inside.toggle()
            }
            j = i
        }
        return inside
    }
}

@Model
final class ParkingLotRecord {
    @Attribute(.unique) var lotId: String
    var name: String
    var boundaryJSON: Data

    init(lotId: String, name: String, boundary: [Coordinate]) {
        self.lotId = lotId
        self.name = name
        self.boundaryJSON = (try? JSONEncoder().encode(boundary)) ?? Data()
    }

    var boundary: [Coordinate] {
        (try? JSONDecoder().decode([Coordinate].self, from: boundaryJSON)) ?? []
    }

    var parkingLot: ParkingLot {
        ParkingLot(id: lotId, name: name, boundary: boundary)
    }
}
