import Foundation
import UIKit

/// Ships structured log events to HoundDog's /api/device-logs endpoint,
/// which forwards them to the Axiom `birddog` dataset.
@MainActor
final class DeviceLogService: ObservableObject {
    static let shared = DeviceLogService()

    private struct Entry: Encodable {
        let timestamp: String
        let level: String
        let event: String
        let device_id: String
        let officer_email: String?
        let lat: Double?
        let lon: Double?
        let battery_pct: Int?
        let app_version: String?
        let extra: [String: String]?
    }

    private var buffer: [Entry] = []
    private let maxBuffer = 1000

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let appVersion: String = {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return "\(version)(\(build))"
    }()

    private init() {}

    // MARK: - Public API

    func log(
        level: String = "info",
        event: String,
        extra: [String: String]? = nil
    ) {
        let location = GeofenceService.shared.currentLocation
        let batteryLevel = Self.batteryPercentage()

        let entry = Entry(
            timestamp: Self.isoFormatter.string(from: Date()),
            level: level,
            event: event,
            device_id: DeviceInfo.modelIdentifier,
            officer_email: OfficerAuthService.shared.officerEmail.isEmpty
                ? nil : OfficerAuthService.shared.officerEmail,
            lat: location?.coordinate.latitude,
            lon: location?.coordinate.longitude,
            battery_pct: batteryLevel,
            app_version: Self.appVersion,
            extra: extra
        )

        buffer.append(entry)

        if buffer.count > maxBuffer {
            buffer.removeFirst(buffer.count - maxBuffer)
        }
    }

    /// Ship buffered entries to the server. Called from HoundDogSyncService's sync cycle.
    func flush() async {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty,
              !settings.houndDogAPIKey.isEmpty,
              !buffer.isEmpty else { return }

        guard let url = URL(string: "\(settings.houndDogURL)/api/device-logs") else { return }

        let payload: [String: Any] = ["entries": buffer.map { encodeToDictionary($0) }]
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = body

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) {
                buffer.removeAll()
            }
            // On failure, keep buffer for retry on next cycle
        } catch {
            // Network error — keep buffer for retry
        }
    }

    // MARK: - Helpers

    private static func batteryPercentage() -> Int? {
        UIDevice.current.isBatteryMonitoringEnabled = true
        let level = UIDevice.current.batteryLevel
        guard level >= 0 else { return nil }
        return Int(level * 100)
    }

    private func encodeToDictionary(_ entry: Entry) -> [String: Any] {
        var dict: [String: Any] = [
            "timestamp": entry.timestamp,
            "level": entry.level,
            "event": entry.event,
            "device_id": entry.device_id,
        ]
        if let email = entry.officer_email { dict["officer_email"] = email }
        if let lat = entry.lat { dict["lat"] = lat }
        if let lon = entry.lon { dict["lon"] = lon }
        if let battery = entry.battery_pct { dict["battery_pct"] = battery }
        if let version = entry.app_version { dict["app_version"] = version }
        if let extra = entry.extra { dict["extra"] = extra }
        return dict
    }
}
