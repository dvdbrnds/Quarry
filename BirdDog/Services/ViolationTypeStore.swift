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
        // Parking violations
        ViolationType(id: "no_permit",              code: "no_permit",              label: "No Valid Permit",                                  category: "parking", fineFirst: "35.00"),
        ViolationType(id: "expired_permit",         code: "expired_permit",         label: "Expired Permit",                                   category: "parking", fineFirst: "35.00"),
        ViolationType(id: "wrong_lot",              code: "wrong_lot",              label: "Wrong Lot",                                        category: "parking", fineFirst: "35.00"),
        ViolationType(id: "fire_lane",              code: "fire_lane",              label: "Fire Lane",                                        category: "parking", fineFirst: "200.00"),
        ViolationType(id: "disability_area",        code: "disability_area",        label: "Disability Area Violation",                        category: "parking", fineFirst: "200.00"),
        ViolationType(id: "overtime",               code: "overtime",               label: "Overtime Parking",                                 category: "parking", fineFirst: "35.00"),
        ViolationType(id: "snow_emergency",         code: "snow_emergency",         label: "Snow Emergency Violation",                         category: "parking", fineFirst: "35.00"),
        ViolationType(id: "loading_zone",           code: "loading_zone",           label: "Loading Zone",                                     category: "parking", fineFirst: "35.00"),
        ViolationType(id: "reserved",               code: "reserved",              label: "Reserved Space",                                    category: "parking", fineFirst: "35.00"),
        ViolationType(id: "double_parked",          code: "double_parked",          label: "Double Parked",                                    category: "parking", fineFirst: "35.00"),
        ViolationType(id: "other",                  code: "other",                  label: "Other",                                            category: "parking", fineFirst: "35.00"),
        // Moving violations (MUPD 2026 Traffic Citation)
        ViolationType(id: "stop_sign",              code: "stop_sign",              label: "Failure to Obey Stop Sign",                        category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "one_way",                code: "one_way",                label: "Failure to Obey One-Way Sign",                     category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "do_not_enter",           code: "do_not_enter",           label: "Failure to Obey Do Not Enter Sign",                category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "traffic_control_device", code: "traffic_control_device", label: "Failure to Obey Other Traffic Control Devices",    category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "unsafe_speed",           code: "unsafe_speed",           label: "Driving at Unsafe Speed",                          category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "crosswalk_yield",        code: "crosswalk_yield",        label: "Failure to Yield to a Pedestrian in a Crosswalk",  category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "careless_driving",       code: "careless_driving",       label: "Careless Driving",                                 category: "moving",  fineFirst: "100.00"),
        ViolationType(id: "reckless_driving",       code: "reckless_driving",       label: "Reckless Driving",                                 category: "moving",  fineFirst: "100.00"),
        ViolationType(id: "no_license",             code: "no_license",             label: "Driving Without a Valid License",                   category: "moving",  fineFirst: "100.00"),
        ViolationType(id: "no_registration",        code: "no_registration",        label: "Driving Without a Valid Vehicle Registration",      category: "moving",  fineFirst: "75.00"),
        ViolationType(id: "no_insurance",           code: "no_insurance",           label: "Driving Without Required Insurance",                category: "moving",  fineFirst: "150.00"),
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

    func types(in category: String) -> [ViolationType] {
        types.filter { $0.category == category }
    }

    /// Picks the first preferred code that exists for the category, else the first type in that category.
    func resolveCode(preferred: [String], category: String) -> String {
        let available = types(in: category)
        let codes = Set(available.map(\.code))
        if let match = preferred.first(where: { codes.contains($0) }) {
            return match
        }
        return available.first?.code ?? preferred.first ?? ""
    }

    func label(for code: String) -> String {
        types.first(where: { $0.code == code })?.label ?? code
    }

    func fineAmount(forCode code: String) -> String {
        types.first(where: { $0.code == code })?.fineFirst ?? "35.00"
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
