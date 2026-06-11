import SwiftUI
import SwiftData

@main
struct BirdDogApp: App {
    init() {
        GeofenceService.shared.configure(container: PlateDatabase.shared.container)
        GeofenceService.shared.requestPermissionAndStart()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(PlateDatabase.shared.container)
    }
}
