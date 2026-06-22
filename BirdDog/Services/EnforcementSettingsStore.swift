import Foundation

/// Caches enforcement policy settings received from HoundDog sync.
/// These mirror `EnforcementSettings` on the server but only the
/// fields relevant to Bird Dog's on-device enforcement logic.
final class EnforcementSettingsStore: ObservableObject {
    static let shared = EnforcementSettingsStore()

    @Published private(set) var paymentDueDays: Int = 5
    @Published private(set) var appealWindowDays: Int = 5
    @Published private(set) var escalationThreshold: Int = 3
    @Published private(set) var towingEnabled: Bool = true
    @Published private(set) var snowEmergencyActive: Bool = false

    private static let storageKey = "EnforcementSettingsStore.cached"

    private struct StoredSettings: Codable {
        let paymentDueDays: Int
        let appealWindowDays: Int
        let escalationThreshold: Int
        let towingEnabled: Bool
        let snowEmergencyActive: Bool
    }

    private init() {
        if let data = UserDefaults.standard.data(forKey: Self.storageKey),
           let stored = try? JSONDecoder().decode(StoredSettings.self, from: data) {
            apply(stored)
        }
    }

    func update(from settings: SyncEnforcementSettings) {
        paymentDueDays      = settings.paymentDueDays
        appealWindowDays    = settings.appealWindowDays
        escalationThreshold = settings.escalationThreshold
        towingEnabled       = settings.towingEnabled
        snowEmergencyActive = settings.snowEmergencyActive

        let stored = StoredSettings(
            paymentDueDays: settings.paymentDueDays,
            appealWindowDays: settings.appealWindowDays,
            escalationThreshold: settings.escalationThreshold,
            towingEnabled: settings.towingEnabled,
            snowEmergencyActive: settings.snowEmergencyActive
        )
        if let data = try? JSONEncoder().encode(stored) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }

    private func apply(_ stored: StoredSettings) {
        paymentDueDays      = stored.paymentDueDays
        appealWindowDays    = stored.appealWindowDays
        escalationThreshold = stored.escalationThreshold
        towingEnabled       = stored.towingEnabled
        snowEmergencyActive = stored.snowEmergencyActive
    }
}
