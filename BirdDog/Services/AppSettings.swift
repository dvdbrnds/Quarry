import Foundation
import SwiftUI

@MainActor
final class AppSettings: ObservableObject {
    static let shared = AppSettings()

    private static let passcodeKey = "AppSettings.adminPasscode"
    private static let schoolNameKey = "AppSettings.schoolName"
    private static let plateRecognizerKeyKey = "AppSettings.plateRecognizerAPIKey"
    private static let useCloudOCRKey = "AppSettings.useCloudOCR"
    private static let defaultPasscode = "1234"

    @Published var isAdminUnlocked = false

    @Published var adminPasscode: String {
        didSet { UserDefaults.standard.set(adminPasscode, forKey: Self.passcodeKey) }
    }

    @Published var schoolName: String {
        didSet { UserDefaults.standard.set(schoolName, forKey: Self.schoolNameKey) }
    }

    @Published var plateRecognizerAPIKey: String {
        didSet { UserDefaults.standard.set(plateRecognizerAPIKey, forKey: Self.plateRecognizerKeyKey) }
    }

    @Published var useCloudOCR: Bool {
        didSet { UserDefaults.standard.set(useCloudOCR, forKey: Self.useCloudOCRKey) }
    }

    private init() {
        self.adminPasscode = UserDefaults.standard.string(forKey: Self.passcodeKey) ?? Self.defaultPasscode
        self.schoolName = UserDefaults.standard.string(forKey: Self.schoolNameKey) ?? ""
        self.plateRecognizerAPIKey = UserDefaults.standard.string(forKey: Self.plateRecognizerKeyKey) ?? ""
        self.useCloudOCR = UserDefaults.standard.bool(forKey: Self.useCloudOCRKey)
    }

    func attemptUnlock(with code: String) -> Bool {
        if code == adminPasscode {
            isAdminUnlocked = true
            return true
        }
        return false
    }

    func lock() {
        isAdminUnlocked = false
    }

    var isFirstLaunch: Bool {
        schoolName.isEmpty
    }
}
