import Foundation

/// Caches violation types received from HoundDog sync.
/// Falls back to built-in defaults when no server data is available.
final class ViolationTypeStore: ObservableObject {
    static let shared = ViolationTypeStore()

    struct ViolationType: Identifiable {
        let id: String
        let code: String
        let label: String
        let category: String  // "parking" | "moving"
        let fineFirst: String
    }

    @Published private(set) var types: [ViolationType] = []

    private static let storageKey = "ViolationTypeStore.cached"

    private static let defaults: [ViolationType] = [
        ViolationType(id: "no_permit",         code: "no_permit",         label: "No Valid Permit",            category: "parking", fineFirst: "35.00"),
        ViolationType(id: "expired_permit",    code: "expired_permit",    label: "Expired Permit",             category: "parking", fineFirst: "35.00"),
        ViolationType(id: "wrong_lot",         code: "wrong_lot",         label: "Wrong Lot",                  category: "parking", fineFirst: "35.00"),
        ViolationType(id: "fire_lane",         code: "fire_lane",         label: "Fire Lane",                  category: "parking", fineFirst: "200.00"),
        ViolationType(id: "disability_area",   code: "disability_area",   label: "Disability Area Violation",  category: "parking", fineFirst: "200.00"),
        ViolationType(id: "overtime",          code: "overtime",          label: "Overtime Parking",           category: "parking", fineFirst: "35.00"),
        ViolationType(id: "snow_emergency",    code: "snow_emergency",    label: "Snow Emergency Violation",   category: "parking", fineFirst: "35.00"),
        ViolationType(id: "loading_zone",      code: "loading_zone",      label: "Loading Zone",               category: "parking", fineFirst: "35.00"),
        ViolationType(id: "reserved",          code: "reserved",          label: "Reserved Space",             category: "parking", fineFirst: "35.00"),
        ViolationType(id: "double_parked",     code: "double_parked",     label: "Double Parked",              category: "parking", fineFirst: "35.00"),
        ViolationType(id: "speeding",          code: "speeding",          label: "Speeding",                   category: "moving",  fineFirst: "50.00"),
        ViolationType(id: "stop_sign",         code: "stop_sign",         label: "Failure to Stop at Stop Sign", category: "moving", fineFirst: "50.00"),
        ViolationType(id: "other",             code: "other",             label: "Other",                      category: "parking", fineFirst: "35.00"),
    ]

    private init() {
        if let cached = loadCached() {
            types = cached
        } else {
            types = Self.defaults
        }
    }

    func update(from serverTypes: [SyncViolationType]) {
        let mapped = serverTypes.map { vt in
            ViolationType(id: vt.code, code: vt.code, label: vt.label, category: vt.category, fineFirst: vt.fineFirst)
        }
        guard !mapped.isEmpty else { return }
        types = mapped
        saveCached(mapped)
    }

    func label(for code: String) -> String {
        types.first(where: { $0.code == code })?.label ?? code
    }

    // MARK: - Persistence (UserDefaults, simple JSON)

    private struct StoredEntry: Codable {
        let code, label, category, fineFirst: String
    }

    private func saveCached(_ types: [ViolationType]) {
        let entries = types.map { StoredEntry(code: $0.code, label: $0.label, category: $0.category, fineFirst: $0.fineFirst) }
        if let data = try? JSONEncoder().encode(entries) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }

    private func loadCached() -> [ViolationType]? {
        guard let data = UserDefaults.standard.data(forKey: Self.storageKey),
              let entries = try? JSONDecoder().decode([StoredEntry].self, from: data),
              !entries.isEmpty else { return nil }
        return entries.map { ViolationType(id: $0.code, code: $0.code, label: $0.label, category: $0.category, fineFirst: $0.fineFirst) }
    }
}
