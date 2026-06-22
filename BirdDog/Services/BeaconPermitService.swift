import Foundation
import CoreLocation

struct NearbyBeaconPermit: Sendable {
    let minor: UInt16
    let major: UInt16
    let permit: PermitInfo
    let plate: String
    let proximity: CLProximity
    let rssi: Int
    let lastSeen: Date
}

@MainActor
final class BeaconPermitService: NSObject, ObservableObject {
    static let shared = BeaconPermitService()

    /// SheepDog hangtag/ePermit iBeacon UUID
    static let beaconUUID = UUID(uuidString: "A495FF00-C5B1-4B44-B512-1370F02D74DE")!

    @Published private(set) var nearbyPermits: [UInt16: NearbyBeaconPermit] = [:]
    @Published private(set) var isRanging = false

    private let locationManager = CLLocationManager()
    private let constraint: CLBeaconIdentityConstraint
    private let region: CLBeaconRegion
    private let database = PlateDatabase.shared

    /// Beacons not seen within this window are pruned
    private static let staleThreshold: TimeInterval = 10

    override init() {
        constraint = CLBeaconIdentityConstraint(uuid: Self.beaconUUID)
        region = CLBeaconRegion(beaconIdentityConstraint: constraint, identifier: "sheepdog.hangtag")
        region.notifyOnEntry = true
        region.notifyOnExit = true
        super.init()
        locationManager.delegate = self
    }

    // MARK: - Public API

    func startRanging() {
        guard CLLocationManager.isRangingAvailable() else {
            print("[BeaconPermit] Ranging not available on this device")
            return
        }

        let status = locationManager.authorizationStatus
        guard status == .authorizedWhenInUse || status == .authorizedAlways else {
            print("[BeaconPermit] Location not authorized (status: \(status.rawValue)), deferring ranging")
            return
        }

        locationManager.startRangingBeacons(satisfying: constraint)
        isRanging = true
        print("[BeaconPermit] Started ranging for UUID \(Self.beaconUUID)")
    }

    func stopRanging() {
        locationManager.stopRangingBeacons(satisfying: constraint)
        nearbyPermits.removeAll()
        isRanging = false
        print("[BeaconPermit] Stopped ranging")
    }

    /// Returns the pre-loaded permit if a nearby beacon's plate matches the scanned plate.
    /// Match means: the permit resolved from the beacon minor has this plate on file.
    func preloadedMatch(forPlate plate: String) -> NearbyBeaconPermit? {
        let normalized = plate.uppercased().replacingOccurrences(of: " ", with: "")
        pruneStale()
        for (_, beacon) in nearbyPermits {
            guard beacon.proximity != .unknown else { continue }
            if beacon.plate == normalized {
                return beacon
            }
        }
        return nil
    }

    /// Returns true if any nearby beacon's permit does NOT match the given plate,
    /// indicating a potential hangtag swap or counterfeit.
    func hasMismatch(forPlate plate: String) -> NearbyBeaconPermit? {
        let normalized = plate.uppercased().replacingOccurrences(of: " ", with: "")
        pruneStale()
        for (_, beacon) in nearbyPermits {
            guard beacon.proximity == .near || beacon.proximity == .immediate else { continue }
            if beacon.plate != normalized {
                return beacon
            }
        }
        return nil
    }

    // MARK: - Internal

    private func resolvePermit(minor: UInt16, major: UInt16) -> (permit: PermitInfo, plate: String)? {
        let minorStr = String(minor)

        if let record = database.lookupByBeaconMinor(minorStr) {
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
            return (info, record.plateNormalized)
        }
        return nil
    }

    private func pruneStale() {
        let cutoff = Date().addingTimeInterval(-Self.staleThreshold)
        nearbyPermits = nearbyPermits.filter { $0.value.lastSeen > cutoff }
    }
}

// MARK: - CLLocationManagerDelegate

extension BeaconPermitService: CLLocationManagerDelegate {

    nonisolated func locationManager(_ manager: CLLocationManager, didRange beacons: [CLBeacon], satisfying constraint: CLBeaconIdentityConstraint) {
        Task { @MainActor in
            self.handleRangedBeacons(beacons)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailRangingFor constraint: CLBeaconIdentityConstraint, error: Error) {
        print("[BeaconPermit] Ranging error: \(error.localizedDescription)")
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                if !self.isRanging {
                    self.startRanging()
                }
            case .denied, .restricted:
                self.stopRanging()
            default:
                break
            }
        }
    }

    @MainActor
    private func handleRangedBeacons(_ beacons: [CLBeacon]) {
        let now = Date()

        for beacon in beacons {
            let minor = beacon.minor.uint16Value
            let major = beacon.major.uint16Value

            if let existing = nearbyPermits[minor] {
                nearbyPermits[minor] = NearbyBeaconPermit(
                    minor: minor,
                    major: major,
                    permit: existing.permit,
                    plate: existing.plate,
                    proximity: beacon.proximity,
                    rssi: beacon.rssi,
                    lastSeen: now
                )
            } else if let resolved = resolvePermit(minor: minor, major: major) {
                nearbyPermits[minor] = NearbyBeaconPermit(
                    minor: minor,
                    major: major,
                    permit: resolved.permit,
                    plate: resolved.plate,
                    proximity: beacon.proximity,
                    rssi: beacon.rssi,
                    lastSeen: now
                )
                print("[BeaconPermit] Pre-loaded permit \(minor) → plate \(resolved.plate)")
            }
        }

        pruneStale()
    }
}
