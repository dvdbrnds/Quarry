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
    var spotCount: Int
    var hasSheepDog: Bool
    var accessSchedule: [SyncSeasonSchedule]

    init(id: String, name: String, boundary: [Coordinate], spotCount: Int = 0, hasSheepDog: Bool = false, accessSchedule: [SyncSeasonSchedule] = []) {
        self.id = id
        self.name = name
        self.boundary = boundary
        self.spotCount = spotCount
        self.hasSheepDog = hasSheepDog
        self.accessSchedule = accessSchedule
    }

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

    /// Check whether a given permit type is allowed in this lot at the specified time.
    /// Returns true if no schedule rules apply (unrestricted) or if the permit type matches.
    func isPermitTypeAllowed(_ permitType: String, at date: Date = Date()) -> Bool {
        guard !accessSchedule.isEmpty else { return true }

        let calendar = Calendar.current
        let hour = calendar.component(.hour, from: date)
        let minute = calendar.component(.minute, from: date)
        let timeStr = String(format: "%02d:%02d", hour, minute)

        let weekday = calendar.component(.weekday, from: date)
        let dayAbbrev = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][weekday - 1]

        for season in accessSchedule {
            for rule in season.rules {
                guard rule.days.contains(dayAbbrev) else { continue }
                guard timeStr >= rule.start && timeStr < rule.end else { continue }
                if rule.allowedPermitTypes.isEmpty { return true }
                if rule.allowedPermitTypes.contains(permitType) { return true }
                return false
            }
        }
        return true
    }
}

@Model
final class ParkingLotRecord {
    @Attribute(.unique) var lotId: String
    var name: String
    var boundaryJSON: Data
    var spotCount: Int
    var hasSheepDog: Bool
    var accessScheduleJSON: Data

    init(lotId: String, name: String, boundary: [Coordinate], spotCount: Int = 0, hasSheepDog: Bool = false, accessSchedule: [SyncSeasonSchedule] = []) {
        self.lotId = lotId
        self.name = name
        self.boundaryJSON = (try? JSONEncoder().encode(boundary)) ?? Data()
        self.spotCount = spotCount
        self.hasSheepDog = hasSheepDog
        self.accessScheduleJSON = (try? JSONEncoder().encode(accessSchedule)) ?? Data()
    }

    var boundary: [Coordinate] {
        (try? JSONDecoder().decode([Coordinate].self, from: boundaryJSON)) ?? []
    }

    var accessSchedule: [SyncSeasonSchedule] {
        (try? JSONDecoder().decode([SyncSeasonSchedule].self, from: accessScheduleJSON)) ?? []
    }

    var parkingLot: ParkingLot {
        ParkingLot(id: lotId, name: name, boundary: boundary, spotCount: spotCount, hasSheepDog: hasSheepDog, accessSchedule: accessSchedule)
    }
}
