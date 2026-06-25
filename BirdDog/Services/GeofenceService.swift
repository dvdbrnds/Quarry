import Foundation
import CoreLocation
import SwiftData

@MainActor
final class GeofenceService: NSObject, ObservableObject {
    static let shared = GeofenceService()

    @Published private(set) var currentLot: ParkingLot?
    @Published private(set) var currentLocation: CLLocation?
    @Published private(set) var locationStatus: CLAuthorizationStatus = .notDetermined
    @Published private(set) var lots: [ParkingLot] = []

    var currentLotName: String? { currentLot?.name }

    private let locationManager = CLLocationManager()
    private var container: ModelContainer?

    private static let seedVersionKey = "GeofenceService.seedVersion"

    override init() {
        super.init()
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.distanceFilter = 10
        locationManager.delegate = self
    }

    func configure(container: ModelContainer) {
        self.container = container
        seedIfNeeded()
        loadLots()
    }

    func requestPermissionAndStart() {
        let status = locationManager.authorizationStatus
        locationStatus = status

        switch status {
        case .authorizedWhenInUse, .authorizedAlways:
            locationManager.startUpdatingLocation()
        case .notDetermined:
            locationManager.requestWhenInUseAuthorization()
        default:
            break
        }
    }

    func stop() {
        locationManager.stopUpdatingLocation()
    }

    // MARK: - Lot Data

    func loadLots() {
        guard let container else { return }
        let context = ModelContext(container)
        let descriptor = FetchDescriptor<ParkingLotRecord>()
        let records = (try? context.fetch(descriptor)) ?? []
        lots = records.map(\.parkingLot)
    }

    func addLot(_ lot: ParkingLot) {
        guard let container else { return }
        let context = ModelContext(container)

        let lotId = lot.id
        var descriptor = FetchDescriptor<ParkingLotRecord>(
            predicate: #Predicate<ParkingLotRecord> { $0.lotId == lotId }
        )
        descriptor.fetchLimit = 1
        if let stale = try? context.fetch(descriptor).first {
            context.delete(stale)
        }

        let record = ParkingLotRecord(lotId: lot.id, name: lot.name, boundary: lot.boundary, spotCount: lot.spotCount, hasSheepDog: lot.hasSheepDog)
        context.insert(record)
        try? context.save()
        loadLots()
        updateCurrentLot()
    }

    func updateLot(_ lot: ParkingLot) {
        guard let container else { return }
        let context = ModelContext(container)
        let lotId = lot.id
        var descriptor = FetchDescriptor<ParkingLotRecord>(
            predicate: #Predicate<ParkingLotRecord> { $0.lotId == lotId }
        )
        descriptor.fetchLimit = 1
        if let existing = try? context.fetch(descriptor).first {
            existing.name = lot.name
            existing.boundaryJSON = (try? JSONEncoder().encode(lot.boundary)) ?? Data()
            existing.spotCount = lot.spotCount
            existing.hasSheepDog = lot.hasSheepDog
            try? context.save()
        }
        loadLots()
        updateCurrentLot()
    }

    func deleteLot(id: String) {
        guard let container else { return }
        let context = ModelContext(container)
        let lotId = id
        var descriptor = FetchDescriptor<ParkingLotRecord>(
            predicate: #Predicate<ParkingLotRecord> { $0.lotId == lotId }
        )
        descriptor.fetchLimit = 1
        if let record = try? context.fetch(descriptor).first {
            context.delete(record)
            try? context.save()
        }
        deleteSpots(forLotId: id)
        loadLots()
        updateCurrentLot()
    }

    // MARK: - Spot Data

    func spotsForLot(_ lotId: String) -> [ParkingSpot] {
        guard let container else { return [] }
        let context = ModelContext(container)
        var descriptor = FetchDescriptor<ParkingSpotRecord>(
            predicate: #Predicate<ParkingSpotRecord> { $0.lotId == lotId },
            sortBy: [SortDescriptor(\.number)]
        )
        let records = (try? context.fetch(descriptor)) ?? []
        return records.map(\.parkingSpot)
    }

    func replaceSpots(forLotId lotId: String, with spots: [ParkingSpot]) {
        guard let container else { return }
        let context = ModelContext(container)

        let existingDescriptor = FetchDescriptor<ParkingSpotRecord>(
            predicate: #Predicate<ParkingSpotRecord> { $0.lotId == lotId }
        )
        for record in (try? context.fetch(existingDescriptor)) ?? [] {
            context.delete(record)
        }

        for spot in spots {
            context.insert(ParkingSpotRecord(
                spotId: spot.id, lotId: spot.lotId, number: spot.number,
                label: spot.label, sensorId: spot.sensorId,
                latitude: spot.latitude, longitude: spot.longitude
            ))
        }
        try? context.save()
    }

    private func deleteSpots(forLotId lotId: String) {
        guard let container else { return }
        let context = ModelContext(container)
        let descriptor = FetchDescriptor<ParkingSpotRecord>(
            predicate: #Predicate<ParkingSpotRecord> { $0.lotId == lotId }
        )
        for record in (try? context.fetch(descriptor)) ?? [] {
            context.delete(record)
        }
        try? context.save()
    }

    // MARK: - Seed from bundled lots.json

    private func seedIfNeeded() {
        guard let container else { return }
        guard let url = Bundle.main.url(forResource: "lots", withExtension: "json") else { return }

        let fileDate = (try? FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as? Date)?
            .timeIntervalSince1970 ?? 0
        let seedVersion = String(format: "%.0f", fileDate)

        let lastSeed = UserDefaults.standard.string(forKey: Self.seedVersionKey) ?? ""
        guard lastSeed != seedVersion else { return }

        do {
            let data = try Data(contentsOf: url)
            let lots = try JSONDecoder().decode([ParkingLot].self, from: data)

            let context = ModelContext(container)
            try context.delete(model: ParkingLotRecord.self)
            for lot in lots {
                context.insert(ParkingLotRecord(lotId: lot.id, name: lot.name, boundary: lot.boundary, spotCount: lot.spotCount, hasSheepDog: lot.hasSheepDog))
            }
            try context.save()
            UserDefaults.standard.set(seedVersion, forKey: Self.seedVersionKey)
        } catch {
            print("Failed to seed lot data: \(error)")
        }
    }

    // MARK: - Location -> Lot Resolution

    private func updateCurrentLot() {
        guard let location = currentLocation else {
            currentLot = nil
            return
        }
        let coord = location.coordinate
        currentLot = lots.first { $0.contains(coord) }
    }
}

extension GeofenceService: CLLocationManagerDelegate {

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        Task { @MainActor in
            self.currentLocation = location
            self.updateCurrentLot()
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.locationStatus = status
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                manager.startUpdatingLocation()
            default:
                break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        print("Location error: \(error.localizedDescription)")
    }
}
