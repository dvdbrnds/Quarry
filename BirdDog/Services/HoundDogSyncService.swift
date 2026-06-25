import Foundation
import Combine
import Network

@MainActor
final class HoundDogSyncService: ObservableObject {
    static let shared = HoundDogSyncService()

    @Published private(set) var syncState: SyncState = .idle
    @Published private(set) var lastSyncDate: Date?
    @Published private(set) var lastError: String?
    @Published private(set) var permitCount: Int = 0
    @Published private(set) var lotCount: Int = 0

    @Published var isEnabled: Bool {
        didSet { UserDefaults.standard.set(isEnabled, forKey: Self.isEnabledKey) }
    }

    enum SyncState: String {
        case idle = "Idle"
        case syncing = "Syncing…"
        case synced = "Synced"
        case error = "Error"
        case offline = "Offline"
    }

    private static let lastPermitSyncKey = "HoundDogSync.lastPermitSync"
    private static let lastLotSyncKey = "HoundDogSync.lastLotSync"
    private static let isEnabledKey = "HoundDogSync.isEnabled"
    private static let syncIntervalSeconds: TimeInterval = 30

    private var syncTimer: Timer?
    private let monitor = NWPathMonitor()
    private var isConnected = false
    private let session = URLSession.shared

    private var lastPermitSync: Date? {
        get { UserDefaults.standard.object(forKey: Self.lastPermitSyncKey) as? Date }
        set { UserDefaults.standard.set(newValue, forKey: Self.lastPermitSyncKey) }
    }

    private var lastLotSync: Date? {
        get { UserDefaults.standard.object(forKey: Self.lastLotSyncKey) as? Date }
        set { UserDefaults.standard.set(newValue, forKey: Self.lastLotSyncKey) }
    }

    private init() {
        self.isEnabled = UserDefaults.standard.bool(forKey: Self.isEnabledKey)

        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isConnected = path.status == .satisfied
                if self?.isEnabled == true && path.status == .satisfied {
                    await self?.syncNow()
                }
            }
        }
        monitor.start(queue: .global(qos: .utility))
    }

    func start() {
        guard isEnabled else { return }
        syncTimer?.invalidate()
        syncTimer = Timer.scheduledTimer(withTimeInterval: Self.syncIntervalSeconds, repeats: true) { [weak self] _ in
            Task { @MainActor in
                await self?.syncNow()
            }
        }
        Task { await syncNow() }
    }

    func stop() {
        syncTimer?.invalidate()
        syncTimer = nil
    }

    func startIfConfigured() {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty, !settings.houndDogAPIKey.isEmpty else { return }
        isEnabled = true
        start()
    }

    func syncNow() async {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty, !settings.houndDogAPIKey.isEmpty else {
            syncState = .idle
            return
        }

        guard isConnected else {
            syncState = .offline
            return
        }

        syncState = .syncing
        lastError = nil

        do {
            try await syncPermits()
            try await syncLots()
            try await syncViolationTypes()
            try await syncCalendar()
            try await syncEnforcementSettings()
            await retryPendingTickets()
            syncState = .synced
            lastSyncDate = Date()
        } catch {
            syncState = .error
            lastError = error.localizedDescription
        }
    }

    // MARK: - Permits

    private func syncPermits() async throws {
        let settings = AppSettings.shared
        var urlString = "\(settings.houndDogURL)/api/sync/permits"
        if let since = lastPermitSync {
            let ts = ISO8601DateFormatter().string(from: since)
            urlString += "?since=\(ts)"
        }

        guard let url = URL(string: urlString) else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw SyncError.serverError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let syncResponse = try decoder.decode(PermitSyncResponse.self, from: data)

        let db = PlateDatabase.shared
        let allPlatesRaw = syncResponse.permits.flatMap { $0.plates }.joined(separator: ";")

        if syncResponse.fullSync {
            // Full sync: delete everything and re-seed from expanded plates
            try db.deleteAll()
            var entries: [PermitEntry] = []
            for permit in syncResponse.permits {
                guard permit.deletedAt == nil else { continue }
                for plate in permit.plates {
                    let normalized = plate.uppercased().replacingOccurrences(of: " ", with: "")
                    guard !normalized.isEmpty else { continue }
                    entries.append(makePermitEntry(permit, plateNormalized: normalized))
                }
            }
            let count = try db.seedFromPayload(PermitPayload(permits: entries))
            permitCount = db.totalCount()
            lastPermitSync = syncResponse.serverTimestamp
            print("[HoundDog] Full sync: \(count) plate records from \(syncResponse.permits.count) permits")
        } else {
            // Incremental sync: upsert updated permits, delete removed ones
            var upserted = 0
            var deleted = 0
            for permit in syncResponse.permits {
                let plateNormalized = permit.plates.map {
                    $0.uppercased().replacingOccurrences(of: " ", with: "")
                }
                if permit.deletedAt != nil {
                    for plate in plateNormalized {
                        db.deleteRecord(normalizedPlate: plate)
                        deleted += 1
                    }
                } else {
                    for plate in plateNormalized {
                        guard !plate.isEmpty else { continue }
                        try db.upsertRecord(makePermitEntry(permit, plateNormalized: plate))
                        upserted += 1
                    }
                }
            }
            permitCount = db.totalCount()
            lastPermitSync = syncResponse.serverTimestamp
            if upserted > 0 || deleted > 0 {
                print("[HoundDog] Incremental sync: \(upserted) upserted, \(deleted) deleted")
            }
        }
        _ = allPlatesRaw  // suppress unused warning
    }

    private func makePermitEntry(_ permit: SyncPermit, plateNormalized: String) -> PermitEntry {
        PermitEntry(
            plateNormalized: plateNormalized,
            plateRaw: permit.plates.joined(separator: ";"),
            plateState: "",
            ownerName: permit.name,
            permitNumber: permit.studentId,
            permitType: permit.permitType,
            permitStatus: permit.status,
            lotZone: permit.lotAssignment,
            vehicleDescription: "",
            issuedDate: permit.startDate,
            expirationDate: permit.endDate,
            beaconId: permit.beaconId
        )
    }

    // MARK: - Violation Types

    private func syncViolationTypes() async throws {
        let settings = AppSettings.shared
        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/violation-types") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let syncResponse = try decoder.decode(ViolationTypesSyncResponse.self, from: data)
        ViolationTypeStore.shared.update(from: syncResponse.violationTypes)
    }

    // MARK: - Academic Calendar

    private func syncCalendar() async throws {
        let settings = AppSettings.shared
        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/calendar") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let syncResponse = try decoder.decode(CalendarSyncResponse.self, from: data)
        CalendarStore.shared.update(from: syncResponse)
    }

    // MARK: - Enforcement Settings

    private func syncEnforcementSettings() async throws {
        let settings = AppSettings.shared
        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/settings") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let syncResponse = try decoder.decode(SettingsSyncResponse.self, from: data)
        EnforcementSettingsStore.shared.update(from: syncResponse.settings)
    }

    // MARK: - Lots

    private func syncLots() async throws {
        let settings = AppSettings.shared
        var urlString = "\(settings.houndDogURL)/api/sync/lots"
        if let since = lastLotSync {
            let ts = ISO8601DateFormatter().string(from: since)
            urlString += "?since=\(ts)"
        }

        guard let url = URL(string: urlString) else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw SyncError.serverError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let syncResponse = try decoder.decode(LotSyncResponse.self, from: data)

        let geofence = GeofenceService.shared
        if syncResponse.fullSync {
            for existing in geofence.lots {
                geofence.deleteLot(id: existing.id)
            }
        }

        for lot in syncResponse.lots {
            let boundary = lot.boundary.map { Coordinate(latitude: $0.latitude, longitude: $0.longitude) }
            let parkingLot = ParkingLot(
                id: lot.id, name: lot.name, boundary: boundary,
                spotCount: lot.spotCount ?? 0, hasSheepDog: lot.hasSheepDog ?? false
            )

            if geofence.lots.contains(where: { $0.id == lot.id }) {
                if lot.deletedAt != nil {
                    geofence.deleteLot(id: lot.id)
                } else {
                    geofence.updateLot(parkingLot)
                }
            } else if lot.deletedAt == nil {
                geofence.addLot(parkingLot)
            }

            if let syncSpots = lot.spots, lot.deletedAt == nil {
                let spots = syncSpots.map { s in
                    ParkingSpot(id: s.id, lotId: lot.id, number: s.number,
                                label: s.label, sensorId: s.sensorId,
                                latitude: s.latitude, longitude: s.longitude)
                }
                geofence.replaceSpots(forLotId: lot.id, with: spots)
            }
        }

        lotCount = geofence.lots.count
        lastLotSync = syncResponse.serverTimestamp

        if !syncResponse.lots.isEmpty {
            print("[HoundDog] Synced \(syncResponse.lots.count) lots (full=\(syncResponse.fullSync))")
        }
    }

    // MARK: - Pending Ticket Retry

    private func retryPendingTickets() async {
        let pending = PlateDatabase.shared.pendingTickets()
        guard !pending.isEmpty else { return }
        print("[HoundDog] Retrying \(pending.count) pending ticket(s)...")
        for ticket in pending {
            do {
                _ = try await uploadTicket(ticket)
                PlateDatabase.shared.markTicketUploaded(ticket)
            } catch {
                print("[HoundDog] Retry failed for ticket \(ticket.ticketId): \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Ticket Upload

    struct TicketUploadResponse {
        let ticketId: String
        let paymentUrl: String
        let fineAmount: String
        let offenseNumber: Int
    }

    func uploadTicket(_ ticket: PendingTicket) async throws -> TicketUploadResponse {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty else {
            throw SyncError.serverError(0)
        }

        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/tickets") else {
            throw SyncError.serverError(0)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = [
            "plate": ticket.plate,
            "lot": ticket.lot,
            "violation_type": ticket.violationType,
            "confidence": ticket.confidence,
            "camera_name": ticket.cameraName,
            "timestamp": ISO8601DateFormatter().string(from: ticket.issuedAt),
            "ticket_category": ticket.ticketCategory,
        ]

        if let photoPath = ticket.photoPath,
           let imageData = try? Data(contentsOf: URL(fileURLWithPath: photoPath)) {
            body["photo_base64"] = imageData.base64EncodedString()
        }

        if let lat = ticket.locationLat { body["location_lat"] = lat }
        if let lng = ticket.locationLng { body["location_lng"] = lng }
        if let text = ticket.locationText { body["location_text"] = text }
        if let desc = ticket.vehicleDescription { body["vehicle_description"] = desc }
        if let notes = ticket.officerNotes { body["officer_notes"] = notes }
        if let name = ticket.driverName { body["driver_name"] = name }
        if let lic = ticket.driverLicense { body["driver_license"] = lic }
        if let officerName = ticket.officerName { body["officer_name"] = officerName }
        if let officerEmail = ticket.officerEmail { body["officer_email"] = officerEmail }
        if let ownerName = ticket.ownerName { body["owner_name"] = ownerName }
        if let permitNumber = ticket.permitNumber { body["permit_number"] = permitNumber }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 202 else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
            let serverMessage = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw SyncError.serverError(statusCode, detail: serverMessage)
        }

        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        return TicketUploadResponse(
            ticketId: json["ticket_id"] as? String ?? ticket.ticketId,
            paymentUrl: json["payment_url"] as? String ?? "",
            fineAmount: json["fine_amount"] as? String ?? "0.00",
            offenseNumber: json["offense_number"] as? Int ?? 1
        )
    }

    @available(*, deprecated, message: "Use uploadTicket(_ ticket:) instead")
    func uploadTicket(plate: String, lot: String, violationType: String, confidence: Double) async throws {
        let ticket = PendingTicket(plate: plate, lot: lot, violationType: violationType, confidence: confidence)
        _ = try await uploadTicket(ticket)
    }

    // MARK: - Types

    enum SyncError: LocalizedError {
        case serverError(Int, detail: String? = nil)

        var errorDescription: String? {
            switch self {
            case .serverError(let code, let detail):
                if let detail { return "Server \(code): \(detail)" }
                return "Server returned HTTP \(code)"
            }
        }
    }
}

// MARK: - Sync Response Models

struct PermitSyncResponse: Decodable {
    let permits: [SyncPermit]
    let serverTimestamp: Date
    let fullSync: Bool

    enum CodingKeys: String, CodingKey {
        case permits
        case serverTimestamp = "server_timestamp"
        case fullSync = "full_sync"
    }
}

struct SyncPermit: Decodable {
    let id: String
    let studentId: String
    let name: String
    let plates: [String]
    let lotAssignment: String
    let permitType: String
    let startDate: String
    let endDate: String?
    let status: String
    let beaconId: String?
    let deletedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case studentId = "student_id"
        case name, plates
        case lotAssignment = "lot_assignment"
        case permitType = "permit_type"
        case startDate = "start_date"
        case endDate = "end_date"
        case status
        case beaconId = "beacon_id"
        case deletedAt = "deleted_at"
    }
}

struct LotSyncResponse: Decodable {
    let lots: [SyncLot]
    let serverTimestamp: Date
    let fullSync: Bool

    enum CodingKeys: String, CodingKey {
        case lots
        case serverTimestamp = "server_timestamp"
        case fullSync = "full_sync"
    }
}

struct SyncLot: Decodable {
    let id: String
    let name: String
    let boundary: [SyncCoordinate]
    let spotCount: Int?
    let hasSheepDog: Bool?
    let spots: [SyncSpot]?
    let deletedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, name, boundary, spots
        case spotCount = "spot_count"
        case hasSheepDog = "has_sheepdog"
        case deletedAt = "deleted_at"
    }
}

struct SyncSpot: Decodable {
    let id: String
    let number: Int
    let label: String?
    let sensorId: String?
    let latitude: Double?
    let longitude: Double?

    enum CodingKeys: String, CodingKey {
        case id, number, label, latitude, longitude
        case sensorId = "sensor_id"
    }
}

struct SyncCoordinate: Decodable {
    let latitude: Double
    let longitude: Double
}

// MARK: - Violation Types sync models

struct SyncViolationType: Decodable {
    let code: String
    let label: String
    let category: String
    let fineFirst: String

    enum CodingKeys: String, CodingKey {
        case code, label, category
        case fineFirst = "fine_first"
    }
}

struct ViolationTypesSyncResponse: Decodable {
    let violationTypes: [SyncViolationType]
    let serverTimestamp: Date

    enum CodingKeys: String, CodingKey {
        case violationTypes = "violation_types"
        case serverTimestamp = "server_timestamp"
    }
}

// MARK: - Calendar sync models

struct SyncAcademicSeason: Decodable {
    let code: String
    let label: String
    let startDate: String
    let endDate: String
    let isDefault: Bool

    enum CodingKeys: String, CodingKey {
        case code, label
        case startDate = "start_date"
        case endDate = "end_date"
        case isDefault = "is_default"
    }
}

struct CalendarSyncResponse: Decodable {
    let seasons: [SyncAcademicSeason]
    let activeSeason: SyncAcademicSeason?
    let serverTimestamp: Date

    enum CodingKeys: String, CodingKey {
        case seasons
        case activeSeason = "active_season"
        case serverTimestamp = "server_timestamp"
    }
}

// MARK: - Enforcement settings sync models

struct SyncEnforcementSettings: Decodable {
    let paymentDueDays: Int
    let appealWindowDays: Int
    let escalationThreshold: Int
    let towingEnabled: Bool
    let snowEmergencyActive: Bool

    enum CodingKeys: String, CodingKey {
        case paymentDueDays = "payment_due_days"
        case appealWindowDays = "appeal_window_days"
        case escalationThreshold = "escalation_threshold"
        case towingEnabled = "towing_enabled"
        case snowEmergencyActive = "snow_emergency_active"
    }
}

struct SettingsSyncResponse: Decodable {
    let settings: SyncEnforcementSettings
    let serverTimestamp: Date

    enum CodingKeys: String, CodingKey {
        case settings
        case serverTimestamp = "server_timestamp"
    }
}
