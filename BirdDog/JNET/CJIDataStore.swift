import Foundation

/// Ephemeral in-memory store for CJI (Criminal Justice Information) data.
///
/// CJI is NEVER persisted to disk, Core Data, UserDefaults, or any local storage.
/// This store clears all data on:
///   - JNET results modal dismiss
///   - App enters background
///   - Screen lock
///   - 30-minute session timeout
///   - Logout
@MainActor
final class CJIDataStore: ObservableObject {
    static let shared = CJIDataStore()

    /// The current JNET lookup result, if any. Display-only.
    @Published private(set) var currentResult: JNETLookupResult?

    /// Whether CJI data is currently being displayed.
    var hasData: Bool { currentResult != nil }

    private init() {}

    /// Store a lookup result for display. This data lives only in memory.
    func store(_ result: JNETLookupResult) {
        currentResult = result
    }

    /// Immediately clear all CJI data from memory.
    func clear() {
        currentResult = nil
    }
}

/// Transit-only model for JNET lookup results. Never persisted.
struct JNETLookupResult {
    let vehicle: JNETVehicleInfo?
    let owner: JNETOwnerInfo?
    let cjisNotice: String
}

struct JNETVehicleInfo {
    let plateNumber: String
    let plateState: String
    let vin: String?
    let year: Int?
    let make: String?
    let model: String?
    let color: String?
    let bodyStyle: String?
    let registrationStatus: String?
    let registrationExpiry: String?
}

struct JNETOwnerInfo {
    let firstName: String?
    let lastName: String?
    let middleName: String?
    let addressLine1: String?
    let addressLine2: String?
    let city: String?
    let state: String?
    let zipCode: String?
    let dateOfBirth: String?
    let driversLicense: String?
}
