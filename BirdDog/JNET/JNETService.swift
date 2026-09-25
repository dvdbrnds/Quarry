import Foundation

/// API client for JNET endpoints on the Quarry backend.
/// CJI response data is kept in memory only — never persisted.
@MainActor
final class JNETService: ObservableObject {
    static let shared = JNETService()

    @Published private(set) var isAuthorized = false
    @Published private(set) var prerequisitesMet = false
    @Published private(set) var jnetEnabled = false
    @Published private(set) var missingPrerequisites: [String] = []

    private init() {}

    // MARK: - Status Check

    /// Check JNET authorization status. Called on login.
    /// A 404 means the feature is invisible to this user (stealth mode) —
    /// treated identically to "not authorized" with no error surfaced.
    func checkStatus() async {
        guard let baseURL = AppSettings.shared.serverURL,
              let url = URL(string: "\(baseURL)/api/jnet/status") else {
            clearStatus()
            return
        }

        var request = URLRequest(url: url)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = await getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                clearStatus()
                return
            }

            // 404 = stealth (feature invisible to this user), treat as not authorized
            guard http.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                clearStatus()
                return
            }

            jnetEnabled = json["enabled"] as? Bool ?? false
            isAuthorized = json["authorized"] as? Bool ?? false
            prerequisitesMet = json["prerequisites_met"] as? Bool ?? false
            missingPrerequisites = json["missing_prerequisites"] as? [String] ?? []
        } catch {
            clearStatus()
        }
    }

    /// Reset all JNET status to defaults (not authorized).
    private func clearStatus() {
        jnetEnabled = false
        isAuthorized = false
        prerequisitesMet = false
        missingPrerequisites = []
    }

    // MARK: - Plate Lookup

    /// Perform a JNET plate lookup. Returns result in memory only.
    func plateLookup(plateNumber: String, state: String = "PA") async throws -> JNETLookupResult {
        guard let baseURL = AppSettings.shared.serverURL,
              let url = URL(string: "\(baseURL)/api/jnet/plate-lookup") else {
            throw JNETServiceError.notConfigured
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = await getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let deviceId = DeviceInfo.deviceIdentifier {
            request.setValue(deviceId, forHTTPHeaderField: "X-BirdDog-Device-Id")
        }

        let body: [String: Any] = [
            "plate_number": plateNumber,
            "state": state,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw JNETServiceError.networkError
        }

        // 404 = stealth denial (feature disabled or access revoked mid-session)
        if http.statusCode == 404 {
            clearStatus()
            throw JNETServiceError.unauthorized
        }

        if http.statusCode == 401 {
            let detail = parseErrorDetail(data)
            if detail == "cjis_session_expired" {
                CJISSessionManager.shared.expireSession()
                throw JNETServiceError.sessionExpired
            }
            throw JNETServiceError.unauthorized
        }

        if http.statusCode == 403 {
            let detail = parseErrorDetail(data)
            throw JNETServiceError.forbidden(detail)
        }

        if http.statusCode == 429 {
            throw JNETServiceError.rateLimited
        }

        guard http.statusCode == 200 else {
            throw JNETServiceError.serverError(http.statusCode)
        }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw JNETServiceError.parseError
        }

        // Record activity for session timeout tracking
        CJISSessionManager.shared.recordActivity()

        return parseResult(json)
    }

    // MARK: - Parsing

    private func parseResult(_ json: [String: Any]) -> JNETLookupResult {
        let vehicleDict = json["vehicle"] as? [String: Any]
        let ownerDict = json["owner"] as? [String: Any]

        let vehicle: JNETVehicleInfo? = vehicleDict.map { v in
            JNETVehicleInfo(
                plateNumber: v["plate_number"] as? String ?? "",
                plateState: v["plate_state"] as? String ?? "",
                vin: v["vin"] as? String,
                year: v["year"] as? Int,
                make: v["make"] as? String,
                model: v["model"] as? String,
                color: v["color"] as? String,
                bodyStyle: v["body_style"] as? String,
                registrationStatus: v["registration_status"] as? String,
                registrationExpiry: v["registration_expiry"] as? String
            )
        }

        let owner: JNETOwnerInfo? = ownerDict.map { o in
            JNETOwnerInfo(
                firstName: o["first_name"] as? String,
                lastName: o["last_name"] as? String,
                middleName: o["middle_name"] as? String,
                addressLine1: o["address_line1"] as? String,
                addressLine2: o["address_line2"] as? String,
                city: o["city"] as? String,
                state: o["state"] as? String,
                zipCode: o["zip_code"] as? String,
                dateOfBirth: o["date_of_birth"] as? String,
                driversLicense: o["drivers_license"] as? String
            )
        }

        let notice = json["cjis_notice"] as? String ?? ""

        return JNETLookupResult(vehicle: vehicle, owner: owner, cjisNotice: notice)
    }

    private func parseErrorDetail(_ data: Data) -> String {
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            return json["detail"] as? String ?? ""
        }
        return ""
    }

    private func getAccessToken() async -> String? {
        // Read from keychain — same token storage as OfficerAuthService
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "edu.moravian.birddog.officer",
            kSecAttrAccount as String: "access_token",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

enum JNETServiceError: LocalizedError {
    case notConfigured
    case unauthorized
    case forbidden(String)
    case sessionExpired
    case rateLimited
    case serverError(Int)
    case networkError
    case parseError

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "JNET is not configured. Pair this device with your Quarry server."
        case .unauthorized: return "Authentication required. Please log in again."
        case .forbidden(let detail): return detail.isEmpty ? "Access denied." : detail
        case .sessionExpired: return "JNET session expired (30-minute inactivity). Please re-authenticate."
        case .rateLimited: return "Too many queries. Please wait before trying again."
        case .serverError(let code): return "Server error (\(code)). Please try again."
        case .networkError: return "Network error. Check your connection."
        case .parseError: return "Failed to parse JNET response."
        }
    }
}
