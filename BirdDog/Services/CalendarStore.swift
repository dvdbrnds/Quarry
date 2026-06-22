import Foundation

/// Caches academic calendar data received from HoundDog sync.
final class CalendarStore: ObservableObject {
    static let shared = CalendarStore()

    struct AcademicSeason: Identifiable {
        let id: String
        let code: String
        let label: String
        let startDate: String
        let endDate: String
        let isDefault: Bool
    }

    @Published private(set) var seasons: [AcademicSeason] = []
    @Published private(set) var activeSeason: AcademicSeason?

    private static let seasonsKey = "CalendarStore.seasons"
    private static let activeKey  = "CalendarStore.activeSeason"

    private init() {
        seasons = loadSeasons()
        activeSeason = loadActiveSeason()
    }

    func update(from response: CalendarSyncResponse) {
        let mapped = response.seasons.map { s in
            AcademicSeason(id: s.code, code: s.code, label: s.label,
                           startDate: s.startDate, endDate: s.endDate, isDefault: s.isDefault)
        }
        seasons = mapped
        activeSeason = response.activeSeason.map { s in
            AcademicSeason(id: s.code, code: s.code, label: s.label,
                           startDate: s.startDate, endDate: s.endDate, isDefault: s.isDefault)
        }
        saveSeasons(mapped)
        saveActiveSeason(activeSeason)
    }

    // MARK: - Persistence

    private struct StoredSeason: Codable {
        let code, label, startDate, endDate: String
        let isDefault: Bool
    }

    private func saveSeasons(_ seasons: [AcademicSeason]) {
        let stored = seasons.map { StoredSeason(code: $0.code, label: $0.label, startDate: $0.startDate, endDate: $0.endDate, isDefault: $0.isDefault) }
        if let data = try? JSONEncoder().encode(stored) {
            UserDefaults.standard.set(data, forKey: Self.seasonsKey)
        }
    }

    private func loadSeasons() -> [AcademicSeason] {
        guard let data = UserDefaults.standard.data(forKey: Self.seasonsKey),
              let stored = try? JSONDecoder().decode([StoredSeason].self, from: data) else { return [] }
        return stored.map { AcademicSeason(id: $0.code, code: $0.code, label: $0.label, startDate: $0.startDate, endDate: $0.endDate, isDefault: $0.isDefault) }
    }

    private func saveActiveSeason(_ season: AcademicSeason?) {
        guard let s = season,
              let data = try? JSONEncoder().encode(StoredSeason(code: s.code, label: s.label, startDate: s.startDate, endDate: s.endDate, isDefault: s.isDefault)) else {
            UserDefaults.standard.removeObject(forKey: Self.activeKey)
            return
        }
        UserDefaults.standard.set(data, forKey: Self.activeKey)
    }

    private func loadActiveSeason() -> AcademicSeason? {
        guard let data = UserDefaults.standard.data(forKey: Self.activeKey),
              let s = try? JSONDecoder().decode(StoredSeason.self, from: data) else { return nil }
        return AcademicSeason(id: s.code, code: s.code, label: s.label, startDate: s.startDate, endDate: s.endDate, isDefault: s.isDefault)
    }
}
