import Foundation
import SwiftUI

@MainActor
final class AppSettings: ObservableObject {
    static let shared = AppSettings()

    private static let passcodeKey = "AppSettings.adminPasscode"
    private static let schoolNameKey = "AppSettings.schoolName"
    private static let plateRecognizerKeyKey = "AppSettings.plateRecognizerAPIKey"
    private static let useCloudOCRKey = "AppSettings.useCloudOCR"
    private static let houndDogURLKey = "AppSettings.houndDogURL"
    private static let houndDogAPIKeyKey = "AppSettings.houndDogAPIKey"
    private static let oktaIssuerKey = "AppSettings.oktaIssuer"
    private static let oktaClientIdKey = "AppSettings.oktaClientId"
    private static let oktaRedirectURIKey = "AppSettings.oktaRedirectURI"
    private static let defaultPasscode = "1234"
    private static let defaultRedirectURI = "edu.moravian.birddog://callback"

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

    @Published var houndDogURL: String {
        didSet { UserDefaults.standard.set(houndDogURL, forKey: Self.houndDogURLKey) }
    }

    @Published var houndDogAPIKey: String {
        didSet { UserDefaults.standard.set(houndDogAPIKey, forKey: Self.houndDogAPIKeyKey) }
    }

    @Published var oktaIssuer: String {
        didSet { UserDefaults.standard.set(oktaIssuer, forKey: Self.oktaIssuerKey) }
    }

    @Published var oktaClientId: String {
        didSet { UserDefaults.standard.set(oktaClientId, forKey: Self.oktaClientIdKey) }
    }

    @Published var oktaRedirectURI: String {
        didSet { UserDefaults.standard.set(oktaRedirectURI, forKey: Self.oktaRedirectURIKey) }
    }

    var oktaRedirectScheme: String {
        oktaRedirectURI.components(separatedBy: "://").first ?? "edu.moravian.birddog"
    }

    var oktaAdminGroup: String { "Quarry-Admin" }
    var oktaStaffGroup: String { "Quarry-Staff" }
    var oktaGroupsClaim: String { "groups" }

    private init() {
        self.adminPasscode = UserDefaults.standard.string(forKey: Self.passcodeKey) ?? Self.defaultPasscode
        self.schoolName = UserDefaults.standard.string(forKey: Self.schoolNameKey) ?? ""
        self.plateRecognizerAPIKey = UserDefaults.standard.string(forKey: Self.plateRecognizerKeyKey) ?? ""
        self.useCloudOCR = UserDefaults.standard.bool(forKey: Self.useCloudOCRKey)
        self.houndDogURL = UserDefaults.standard.string(forKey: Self.houndDogURLKey) ?? ""
        self.houndDogAPIKey = UserDefaults.standard.string(forKey: Self.houndDogAPIKeyKey) ?? ""
        self.oktaIssuer = UserDefaults.standard.string(forKey: Self.oktaIssuerKey) ?? ""
        self.oktaClientId = UserDefaults.standard.string(forKey: Self.oktaClientIdKey) ?? ""
        self.oktaRedirectURI = UserDefaults.standard.string(forKey: Self.oktaRedirectURIKey) ?? Self.defaultRedirectURI
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

    var isServerConfigured: Bool {
        !houndDogURL.isEmpty && !houndDogAPIKey.isEmpty
    }

    var isOktaConfigured: Bool {
        !oktaIssuer.isEmpty && !oktaClientId.isEmpty
    }

    var needsOnboarding: Bool {
        !isServerConfigured
    }
}
