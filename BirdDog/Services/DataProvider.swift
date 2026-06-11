import Foundation

struct ImportResult {
    let permitCount: Int
    let lotCount: Int
}

protocol DataProvider {
    @MainActor func importPermits(from data: Data) throws -> Int
    @MainActor func importLots(from data: Data) throws -> Int
}

@MainActor
final class LocalDataProvider: DataProvider {

    static let shared = LocalDataProvider()

    private static let importedPermitsFilename = "imported_permits.json"
    private static let importedLotsFilename = "imported_lots.json"

    private init() {}

    private var documentsDirectory: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
    }

    var importedPermitsURL: URL {
        documentsDirectory.appendingPathComponent(Self.importedPermitsFilename)
    }

    var importedLotsURL: URL {
        documentsDirectory.appendingPathComponent(Self.importedLotsFilename)
    }

    var hasImportedPermits: Bool {
        FileManager.default.fileExists(atPath: importedPermitsURL.path)
    }

    var hasImportedLots: Bool {
        FileManager.default.fileExists(atPath: importedLotsURL.path)
    }

    func importPermits(from data: Data) throws -> Int {
        let payload = try JSONDecoder().decode(PermitPayload.self, from: data)
        try data.write(to: importedPermitsURL)

        let db = PlateDatabase.shared
        try db.deleteAll()
        let count = try db.seedFromPayload(payload)
        return count
    }

    func importLots(from data: Data) throws -> Int {
        let lots = try JSONDecoder().decode([ParkingLot].self, from: data)
        try data.write(to: importedLotsURL)

        let geofence = GeofenceService.shared
        for existingLot in geofence.lots {
            geofence.deleteLot(id: existingLot.id)
        }
        for lot in lots {
            geofence.addLot(lot)
        }
        return lots.count
    }

    func permitDataURL() -> URL? {
        if hasImportedPermits { return importedPermitsURL }
        return Bundle.main.url(forResource: "permits", withExtension: "json")
    }

    func lotDataURL() -> URL? {
        if hasImportedLots { return importedLotsURL }
        return Bundle.main.url(forResource: "lots", withExtension: "json")
    }
}
