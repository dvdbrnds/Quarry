import Foundation

@MainActor
final class PushTokenService {
    static let shared = PushTokenService()

    private static let storedTokenKey = "PushToken.lastRegistered"
    private let session = URLSession.shared

    private init() {}

    func registerToken(_ token: String) async {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty, !settings.houndDogAPIKey.isEmpty else { return }

        let lastToken = UserDefaults.standard.string(forKey: Self.storedTokenKey)
        guard token != lastToken else { return }

        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/register-push") else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["token": token])

        do {
            let (_, response) = try await session.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode == 204 {
                UserDefaults.standard.set(token, forKey: Self.storedTokenKey)
                print("[Push] Token registered with server")
            }
        } catch {
            print("[Push] Token registration failed: \(error.localizedDescription)")
        }
    }
}
