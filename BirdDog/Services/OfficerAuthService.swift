import Foundation
import AuthenticationServices
import Security
import CommonCrypto

@MainActor
final class OfficerAuthService: NSObject, ObservableObject {
    static let shared = OfficerAuthService()

    @Published private(set) var isLoggedIn = false
    @Published private(set) var officerName: String = ""
    @Published private(set) var officerEmail: String = ""
    @Published private(set) var officerGroups: [String] = []
    @Published private(set) var isLoggingIn = false
    @Published private(set) var loginError: String?

    var isAdmin: Bool {
        let adminGroup = AppSettings.shared.oktaAdminGroup
        return officerGroups.contains(adminGroup)
    }

    var isStaff: Bool {
        let staffGroup = AppSettings.shared.oktaStaffGroup
        return isAdmin || officerGroups.contains(staffGroup)
    }

    private static let keychainService = "edu.moravian.birddog.officer"
    private static let keychainAccountName = "name"
    private static let keychainAccountEmail = "email"
    private static let keychainAccountGroups = "groups"
    private static let keychainAccountExpiry = "expiry"

    private var webAuthSession: ASWebAuthenticationSession?

    private override init() {
        super.init()
        restoreSession()
    }

    // MARK: - Login

    func login() {
        let settings = AppSettings.shared
        guard !settings.oktaIssuer.isEmpty, !settings.oktaClientId.isEmpty else {
            loginError = "Okta is not configured. Pair this device with your Quarry server first."
            return
        }

        isLoggingIn = true
        loginError = nil

        let authURL = buildAuthURL(settings: settings)
        guard let url = authURL else {
            loginError = "Failed to build login URL"
            isLoggingIn = false
            return
        }

        let callbackScheme = settings.oktaRedirectScheme

        let session = ASWebAuthenticationSession(url: url, callbackURLScheme: callbackScheme) { [weak self] callbackURL, error in
            Task { @MainActor in
                guard let self else { return }
                self.isLoggingIn = false

                if let error {
                    if (error as NSError).code == ASWebAuthenticationSessionError.canceledLogin.rawValue {
                        return
                    }
                    self.loginError = error.localizedDescription
                    return
                }

                guard let callbackURL else {
                    self.loginError = "No callback received"
                    return
                }

                await self.handleCallback(callbackURL)
            }
        }

        session.presentationContextProvider = self
        session.prefersEphemeralWebBrowserSession = false
        self.webAuthSession = session
        session.start()
    }

    func logout() {
        officerName = ""
        officerEmail = ""
        officerGroups = []
        isLoggedIn = false
        clearKeychain()
    }

    // MARK: - OIDC Flow

    private func buildAuthURL(settings: AppSettings) -> URL? {
        let baseURL = "\(settings.oktaIssuer)/v1/authorize"
        var components = URLComponents(string: baseURL)

        let codeVerifier = generateCodeVerifier()
        let codeChallenge = generateCodeChallenge(from: codeVerifier)
        UserDefaults.standard.set(codeVerifier, forKey: "oidc_code_verifier")

        let state = UUID().uuidString
        UserDefaults.standard.set(state, forKey: "oidc_state")

        components?.queryItems = [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: settings.oktaClientId),
            URLQueryItem(name: "redirect_uri", value: settings.oktaRedirectURI),
            URLQueryItem(name: "scope", value: "openid profile email groups"),
            URLQueryItem(name: "state", value: state),
            URLQueryItem(name: "code_challenge", value: codeChallenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
        ]

        return components?.url
    }

    private func handleCallback(_ url: URL) async {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let code = components.queryItems?.first(where: { $0.name == "code" })?.value else {
            loginError = "Missing authorization code"
            return
        }

        let savedState = UserDefaults.standard.string(forKey: "oidc_state") ?? ""
        let returnedState = components.queryItems?.first(where: { $0.name == "state" })?.value ?? ""
        guard savedState == returnedState else {
            loginError = "Invalid state parameter"
            return
        }

        await exchangeCodeForTokens(code: code)
    }

    private func exchangeCodeForTokens(code: String) async {
        let settings = AppSettings.shared
        let tokenURL = "\(settings.oktaIssuer)/v1/token"

        guard let url = URL(string: tokenURL) else {
            loginError = "Invalid token endpoint"
            return
        }

        guard let codeVerifier = UserDefaults.standard.string(forKey: "oidc_code_verifier") else {
            loginError = "Missing code verifier"
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        let body = [
            "grant_type=authorization_code",
            "client_id=\(settings.oktaClientId)",
            "redirect_uri=\(settings.oktaRedirectURI.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")",
            "code=\(code)",
            "code_verifier=\(codeVerifier)",
        ].joined(separator: "&")

        request.httpBody = body.data(using: .utf8)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                loginError = "Token exchange failed"
                return
            }

            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let idToken = json["id_token"] as? String else {
                loginError = "Invalid token response"
                return
            }

            parseIDToken(idToken)

            UserDefaults.standard.removeObject(forKey: "oidc_code_verifier")
            UserDefaults.standard.removeObject(forKey: "oidc_state")
        } catch {
            loginError = error.localizedDescription
        }
    }

    private func parseIDToken(_ token: String) {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else {
            loginError = "Malformed ID token"
            return
        }

        var base64 = String(parts[1])
        while base64.count % 4 != 0 { base64.append("=") }

        guard let payloadData = Data(base64Encoded: base64),
              let claims = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any] else {
            loginError = "Failed to decode ID token"
            return
        }

        let name = claims["name"] as? String
            ?? claims["preferred_username"] as? String
            ?? ""
        let email = claims["email"] as? String
            ?? claims["sub"] as? String
            ?? ""
        let groups = claims[AppSettings.shared.oktaGroupsClaim] as? [String] ?? []

        let expiry: Date
        if let exp = claims["exp"] as? TimeInterval {
            expiry = Date(timeIntervalSince1970: exp)
        } else {
            expiry = Date().addingTimeInterval(8 * 3600)
        }

        self.officerName = name
        self.officerEmail = email
        self.officerGroups = groups
        self.isLoggedIn = true

        saveToKeychain(name: name, email: email, groups: groups, expiry: expiry)
    }

    // MARK: - PKCE Helpers

    private func generateCodeVerifier() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private func generateCodeChallenge(from verifier: String) -> String {
        guard let data = verifier.data(using: .ascii) else { return "" }
        var hash = [UInt8](repeating: 0, count: 32)
        _ = data.withUnsafeBytes { ptr in
            CC_SHA256(ptr.baseAddress, CC_LONG(data.count), &hash)
        }
        return Data(hash)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    // MARK: - Keychain Persistence

    private func saveToKeychain(name: String, email: String, groups: [String], expiry: Date) {
        let groupsStr = groups.joined(separator: ",")
        let expiryStr = String(expiry.timeIntervalSince1970)

        setKeychainValue(name, account: Self.keychainAccountName)
        setKeychainValue(email, account: Self.keychainAccountEmail)
        setKeychainValue(groupsStr, account: Self.keychainAccountGroups)
        setKeychainValue(expiryStr, account: Self.keychainAccountExpiry)
    }

    private func restoreSession() {
        guard let expiryStr = getKeychainValue(account: Self.keychainAccountExpiry),
              let expiryInterval = Double(expiryStr) else {
            return
        }

        let expiry = Date(timeIntervalSince1970: expiryInterval)
        guard expiry > Date() else {
            clearKeychain()
            return
        }

        guard let name = getKeychainValue(account: Self.keychainAccountName),
              let email = getKeychainValue(account: Self.keychainAccountEmail) else {
            return
        }

        let groupsStr = getKeychainValue(account: Self.keychainAccountGroups) ?? ""
        let groups = groupsStr.isEmpty ? [] : groupsStr.components(separatedBy: ",")

        self.officerName = name
        self.officerEmail = email
        self.officerGroups = groups
        self.isLoggedIn = true
    }

    private func clearKeychain() {
        let accounts = [
            Self.keychainAccountName,
            Self.keychainAccountEmail,
            Self.keychainAccountGroups,
            Self.keychainAccountExpiry,
        ]
        for account in accounts {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: Self.keychainService,
                kSecAttrAccount as String: account,
            ]
            SecItemDelete(query as CFDictionary)
        }
    }

    private func setKeychainValue(_ value: String, account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.keychainService,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)

        var attrs = query
        attrs[kSecValueData as String] = value.data(using: .utf8)
        SecItemAdd(attrs as CFDictionary, nil)
    }

    private func getKeychainValue(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.keychainService,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

// MARK: - ASWebAuthenticationPresentationContextProviding

extension OfficerAuthService: ASWebAuthenticationPresentationContextProviding {
    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            ASPresentationAnchor()
        }
    }
}
