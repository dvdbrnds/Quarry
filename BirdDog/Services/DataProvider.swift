import Foundation

struct ImportResult {
    let permitCount: Int
    let lotCount: Int
}

protocol DataProvider {
    @MainActor func importLots(from data: Data) throws -> Int
}

@MainActor
final class LocalDataProvider: DataProvider {

    static let shared = LocalDataProvider()

    private static let importedLotsFilename = "imported_lots.json"

    private init() {}

    private var documentsDirectory: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
    }

    var importedLotsURL: URL {
        documentsDirectory.appendingPathComponent(Self.importedLotsFilename)
    }

    var hasImportedLots: Bool {
        FileManager.default.fileExists(atPath: importedLotsURL.path)
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

    func lotDataURL() -> URL? {
        if hasImportedLots { return importedLotsURL }
        return Bundle.main.url(forResource: "lots", withExtension: "json")
    }
}
