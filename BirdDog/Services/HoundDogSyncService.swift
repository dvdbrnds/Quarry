import Foundation
import Combine
import Network
import UIKit

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
    private static let syncIntervalSeconds: TimeInterval = 60

    private static let jsonDecoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
    private static let isoFormatter = ISO8601DateFormatter()

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

    private var started = false

    private init() {
        self.isEnabled = UserDefaults.standard.bool(forKey: Self.isEnabledKey)

        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isConnected = path.status == .satisfied
                if self?.started == true && self?.isEnabled == true && path.status == .satisfied {
                    await self?.syncNow()
                }
            }
        }
        monitor.start(queue: .global(qos: .utility))
    }

    func start() {
        guard isEnabled else { return }
        started = true
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

    func resetSyncDates() {
        lastPermitSync = nil
        lastLotSync = nil
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

        let dbEmpty = PlateDatabase.shared.totalCount() == 0
        let lotsEmpty = GeofenceService.shared.lots.isEmpty
        let hoursSinceFullSync = lastPermitSync.map { Date().timeIntervalSince($0) / 3600 } ?? .infinity
        if dbEmpty || lotsEmpty || hoursSinceFullSync >= 1.0 {
            lastPermitSync = nil
            lastLotSync = nil
            if dbEmpty || lotsEmpty {
                print("[HoundDog] Local data missing (permits=\(dbEmpty), lots=\(lotsEmpty)) — forcing full sync")
                DeviceLogService.shared.log(event: "full_sync_forced", extra: ["reason": "local_data_missing", "permits_empty": "\(dbEmpty)", "lots_empty": "\(lotsEmpty)"])
            } else {
                print("[HoundDog] Hourly full refresh (\(String(format: "%.1f", hoursSinceFullSync))h since last)")
                DeviceLogService.shared.log(event: "full_sync_forced", extra: ["reason": "hourly_refresh", "hours_since": String(format: "%.1f", hoursSinceFullSync)])
            }
        }

        do {
            print("[HoundDog] Starting sync… (permits=\(lastPermitSync?.description ?? "nil"), lots=\(lastLotSync?.description ?? "nil"))")
            DeviceLogService.shared.log(event: "sync_started")
            try await syncPermits()
            print("[HoundDog] Permits OK (\(permitCount) records)")
            try await syncLots()
            print("[HoundDog] Lots OK (\(lotCount) lots)")
            try await syncDiversions()
            try await syncViolationTypes()
            try await syncCalendar()
            try await syncEnforcementSettings()
            try await syncRecentTickets()
            await retryPendingTickets()
            DeviceLogService.shared.log(event: "sync_completed", extra: ["permits": "\(permitCount)", "lots": "\(lotCount)"])
            await DeviceLogService.shared.flush()
            syncState = .synced
            lastSyncDate = Date()
            NotificationCenter.default.post(name: .init("HoundDogSyncCompleted"), object: nil)
        } catch {
            let msg = error.localizedDescription
            print("[HoundDog] SYNC FAILED: \(msg)")
            DeviceLogService.shared.log(level: "error", event: "sync_failed", extra: ["error": msg])
            syncState = .error
            lastError = msg
            await DeviceLogService.shared.flush()
        }
    }

    // MARK: - Permits

    private func syncPermits() async throws {
        let settings = AppSettings.shared
        var urlString = "\(settings.houndDogURL)/api/sync/permits"
        if let since = lastPermitSync {
            let ts = Self.isoFormatter.string(from: since)
            urlString += "?since=\(ts)"
        }

        guard let url = URL(string: urlString) else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw SyncError.serverError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }

        let syncResponse = try Self.jsonDecoder.decode(PermitSyncResponse.self, from: data)

        let db = PlateDatabase.shared
        let allPlatesRaw = syncResponse.permits.flatMap { $0.plates }.joined(separator: ";")

        if syncResponse.fullSync {
            // Full sync: delete everything and re-seed from expanded plates
            try db.deleteAll()
            var entries: [PermitEntry] = []
            for permit in syncResponse.permits {
                guard permit.deletedAt == nil else { continue }
                for plate in permit.plates {
                    let normalized = PlatePatternMatcher.normalize(plate)
                    guard !normalized.isEmpty else { continue }
                    entries.append(makePermitEntry(permit, plateNormalized: normalized))
                }
            }
            let count = try db.seedFromPayload(PermitPayload(permits: entries))
            permitCount = db.totalCount()
            lastPermitSync = syncResponse.serverTimestamp
            print("[HoundDog] Full sync: \(count) plate records from \(syncResponse.permits.count) permits")
            DeviceLogService.shared.log(event: "permits_full_sync", extra: ["plate_records": "\(count)", "permits": "\(syncResponse.permits.count)"])
        } else {
            // Incremental sync: upsert updated permits, delete removed ones
            var upserted = 0
            var deleted = 0
            for permit in syncResponse.permits {
                let plateNormalized = permit.plates.map {
                    PlatePatternMatcher.normalize($0)
                }
                if permit.deletedAt != nil {
                    for plate in plateNormalized {
                        db.deleteRecord(normalizedPlate: plate)
                        deleted += 1
                    }
                } else {
                    let validPlates = Set(plateNormalized.filter { !$0.isEmpty })
                    for plate in validPlates {
                        try db.upsertRecord(makePermitEntry(permit, plateNormalized: plate))
                        upserted += 1
                    }
                }
            }
            permitCount = db.totalCount()
            lastPermitSync = syncResponse.serverTimestamp
            if upserted > 0 || deleted > 0 {
                print("[HoundDog] Incremental sync: \(upserted) upserted, \(deleted) deleted")
                DeviceLogService.shared.log(event: "permits_incremental_sync", extra: ["upserted": "\(upserted)", "deleted": "\(deleted)"])
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
            vehicleDescription: permit.vehicleDescription,
            issuedDate: permit.startDate,
            expirationDate: permit.endDate,
            beaconId: permit.beaconId,
            hcStatus: permit.hcStatus,
            hcExpiry: permit.hcExpiry
        )
    }

    // MARK: - Diversions

    /// Active lot diversions: maps closed lot name → divert-to lot name.
    /// When a lot is closed and diverted, permit holders from the closed lot
    /// are allowed in the diversion target without citation.
    @Published private(set) var activeDiversions: [String: String] = [:]

    /// Recently ticketed plates from ALL devices (last 24h).
    /// Keyed by normalized plate → lot name.
    @Published private(set) var recentlyTicketedPlates: [String: String] = [:]

    private func syncDiversions() async throws {
        let settings = AppSettings.shared
        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/diversions") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }

        let syncResponse = try Self.jsonDecoder.decode(DiversionsSyncResponse.self, from: data)
        var map: [String: String] = [:]
        for d in syncResponse.diversions {
            map[d.closedLotName.uppercased()] = d.divertToLotName.uppercased()
        }
        activeDiversions = map
        print("[HoundDog] Diversions: \(map.count) active")
    }

    // MARK: - Recently Ticketed Plates

    private struct RecentTicketEntry: Decodable {
        let plate: String
        let lot: String
        let issued_at: String
        let officer_email: String?
    }

    private struct RecentTicketsSyncResponse: Decodable {
        let tickets: [RecentTicketEntry]
        let server_timestamp: String
    }

    private func syncRecentTickets() async throws {
        let settings = AppSettings.shared
        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/recent-tickets") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }

        let syncResponse = try Self.jsonDecoder.decode(RecentTicketsSyncResponse.self, from: data)
        var map: [String: String] = [:]
        for entry in syncResponse.tickets {
            let normalized = entry.plate.uppercased().trimmingCharacters(in: .whitespaces)
            if map[normalized] == nil {
                map[normalized] = entry.lot
            }
        }
        recentlyTicketedPlates = map
        print("[HoundDog] Recent tickets: \(map.count) plates ticketed in last 24h")
    }

    // MARK: - Violation Types

    private func syncViolationTypes() async throws {
        let settings = AppSettings.shared
        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/violation-types") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return }

        let syncResponse = try Self.jsonDecoder.decode(ViolationTypesSyncResponse.self, from: data)
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

        let syncResponse = try Self.jsonDecoder.decode(CalendarSyncResponse.self, from: data)
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

        let syncResponse = try Self.jsonDecoder.decode(SettingsSyncResponse.self, from: data)
        EnforcementSettingsStore.shared.update(from: syncResponse.settings)
        if let url = syncResponse.studentFacingUrl, !url.isEmpty {
            AppSettings.shared.studentFacingURL = url
        }
    }

    // MARK: - Lots

    private func syncLots() async throws {
        let settings = AppSettings.shared
        var urlString = "\(settings.houndDogURL)/api/sync/lots"
        if let since = lastLotSync {
            let ts = Self.isoFormatter.string(from: since)
            urlString += "?since=\(ts)"
        }

        guard let url = URL(string: urlString) else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw SyncError.serverError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }

        let syncResponse = try Self.jsonDecoder.decode(LotSyncResponse.self, from: data)

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
                spotCount: lot.spotCount ?? 0, hasSheepDog: lot.hasSheepDog ?? false,
                accessSchedule: lot.accessSchedule ?? []
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
        let db = PlateDatabase.shared
        let pending = db.pendingTickets()
        guard !pending.isEmpty else { return }
        print("[HoundDog] Retrying \(pending.count) pending ticket(s)...")
        DeviceLogService.shared.log(event: "ticket_retry_started", extra: ["count": "\(pending.count)"])
        for ticket in pending {
            do {
                let result = try await uploadTicket(ticket)
                db.markTicketUploaded(ticket)
                ticket.paymentUrl = result.paymentUrl
                ticket.fineAmount = result.fineAmount
                ticket.offenseNumber = result.offenseNumber
                try? db.saveContext()
            } catch {
                print("[HoundDog] Retry failed for ticket \(ticket.ticketId): \(error.localizedDescription)")
                DeviceLogService.shared.log(level: "error", event: "ticket_retry_failed", extra: ["error": error.localizedDescription])
            }
        }
    }

    // MARK: - Ticket Upload

    struct TicketUploadResponse {
        let status: String
        let ticketId: String
        let paymentUrl: String
        let fineAmount: String
        let offenseNumber: Int
        let notificationSent: Bool
        let notificationEmail: String?

        var isDuplicate: Bool { status == "duplicate" }
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
            "timestamp": Self.isoFormatter.string(from: ticket.issuedAt),
            "ticket_category": ticket.ticketCategory,
            "client_ticket_id": ticket.ticketId,
        ]

        if let photoPath = ticket.photoPath,
           let imageData = try? Data(contentsOf: URL(fileURLWithPath: photoPath)) {
            body["photo_base64"] = imageData.base64EncodedString()
        }

        if !ticket.additionalPhotoPaths.isEmpty {
            var extras: [String] = []
            for path in ticket.additionalPhotoPaths {
                if let data = try? Data(contentsOf: URL(fileURLWithPath: path)) {
                    extras.append(data.base64EncodedString())
                }
            }
            if !extras.isEmpty {
                body["additional_photos_base64"] = extras
            }
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
        if ticket.isWarning { body["is_warning"] = true }
        if let warningReason = ticket.warningReason { body["warning_reason"] = warningReason }
        if let ocrOriginal = ticket.ocrOriginalPlate { body["ocr_original_plate"] = ocrOriginal }
        if let ownerName = ticket.ownerName { body["owner_name"] = ownerName }
        if let permitNumber = ticket.permitNumber { body["permit_number"] = permitNumber }
        if let permitType = ticket.permitTypeLabel { body["permit_type_label"] = permitType }
        if let permitLot = ticket.permitLotZone { body["permit_lot_zone"] = permitLot }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 202 else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
            let serverMessage = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw SyncError.serverError(statusCode, detail: serverMessage)
        }

        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        return TicketUploadResponse(
            status: json["status"] as? String ?? "accepted",
            ticketId: json["ticket_id"] as? String ?? ticket.ticketId,
            paymentUrl: json["payment_url"] as? String ?? "",
            fineAmount: json["fine_amount"] as? String ?? "0.00",
            offenseNumber: json["offense_number"] as? Int ?? 1,
            notificationSent: json["notification_sent"] as? Bool ?? false,
            notificationEmail: json["notification_email"] as? String
        )
    }

    @available(*, deprecated, message: "Use uploadTicket(_ ticket:) instead")
    func uploadTicket(plate: String, lot: String, violationType: String, confidence: Double) async throws {
        let ticket = PendingTicket(plate: plate, lot: lot, violationType: violationType, confidence: confidence)
        _ = try await uploadTicket(ticket)
    }

    // MARK: - Plate Corrections

    struct PlateCorrectionPayload: Encodable {
        let ocr_plate: String
        let correct_plate: String
        let plate_state: String
        let lot: String
        let officer_name: String
        let officer_email: String
        let device_name: String
        let notes: String
    }

    func uploadPlateCorrection(
        ocrPlate: String,
        correctPlate: String,
        plateState: String = "",
        lot: String = "",
        officerName: String = "",
        officerEmail: String = "",
        notes: String = ""
    ) async throws {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty else {
            throw SyncError.serverError(0)
        }

        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/plate-correction") else {
            throw SyncError.serverError(0)
        }

        let payload = PlateCorrectionPayload(
            ocr_plate: ocrPlate,
            correct_plate: correctPlate,
            plate_state: plateState,
            lot: lot,
            officer_name: officerName,
            officer_email: officerEmail,
            device_name: UIDevice.current.name,
            notes: notes
        )

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONEncoder().encode(payload)

        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw SyncError.serverError(code)
        }
        print("[HoundDog] Plate correction submitted: \(ocrPlate) -> \(correctPlate)")
    }

    // MARK: - Vehicle Tags

    struct VehicleTagPayload: Encodable {
        let plates: [String]
        let owner_name: String
        let owner_address: String
        let student_name: String
        let student_email: String
        let vehicle_make: String
        let vehicle_model: String
        let vehicle_color: String
        let vehicle_year: String
        let source: String
        let notes: String
        let officer_name: String
        let officer_email: String
    }

    struct VehicleTagResponse: Decodable {
        let status: String
        let tag_id: String
        let plates: [String]
    }

    func createVehicleTag(
        plates: [String],
        ownerName: String = "",
        ownerAddress: String = "",
        studentName: String = "",
        studentEmail: String = "",
        vehicleMake: String = "",
        vehicleModel: String = "",
        vehicleColor: String = "",
        vehicleYear: String = "",
        source: String = "officer",
        notes: String = ""
    ) async throws -> VehicleTagResponse {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty else {
            throw SyncError.serverError(0)
        }

        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/vehicle-tags") else {
            throw SyncError.serverError(0)
        }

        let payload = VehicleTagPayload(
            plates: plates,
            owner_name: ownerName,
            owner_address: ownerAddress,
            student_name: studentName,
            student_email: studentEmail,
            vehicle_make: vehicleMake,
            vehicle_model: vehicleModel,
            vehicle_color: vehicleColor,
            vehicle_year: vehicleYear,
            source: source,
            notes: notes,
            officer_name: OfficerAuthService.shared.officerName,
            officer_email: OfficerAuthService.shared.officerEmail
        )

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let serverMessage = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw SyncError.serverError(code, detail: serverMessage)
        }

        let result = try JSONDecoder().decode(VehicleTagResponse.self, from: data)
        print("[HoundDog] Vehicle tag created: \(result.plates.joined(separator: ", "))")
        return result
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
    let hcStatus: String?
    let hcExpiry: String?
    let vehicleMake: String?
    let vehicleModel: String?
    let vehicleColor: String?
    let vehicleYear: String?

    var vehicleDescription: String {
        [vehicleYear, vehicleColor, vehicleMake, vehicleModel]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

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
        case hcStatus = "hc_status"
        case hcExpiry = "hc_expiry"
        case vehicleMake = "vehicle_make"
        case vehicleModel = "vehicle_model"
        case vehicleColor = "vehicle_color"
        case vehicleYear = "vehicle_year"
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
    let accessSchedule: [SyncSeasonSchedule]?

    enum CodingKeys: String, CodingKey {
        case id, name, boundary, spots
        case spotCount = "spot_count"
        case hasSheepDog = "has_sheepdog"
        case deletedAt = "deleted_at"
        case accessSchedule = "access_schedule"
    }
}

struct SyncSeasonSchedule: Codable, Sendable, Equatable {
    let season: String
    let label: String?
    let rules: [SyncTimeRule]
}

struct SyncTimeRule: Codable, Sendable, Equatable {
    let start: String
    let end: String
    let days: [String]
    let allowedPermitTypes: [String]
    let label: String?

    enum CodingKeys: String, CodingKey {
        case start, end, days, label
        case allowedPermitTypes = "allowed_permit_types"
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

// MARK: - Diversion sync models

struct SyncDiversion: Decodable {
    let closedLotName: String
    let divertToLotName: String
    let reason: String

    enum CodingKeys: String, CodingKey {
        case closedLotName = "closed_lot_name"
        case divertToLotName = "divert_to_lot_name"
        case reason
    }
}

struct DiversionsSyncResponse: Decodable {
    let diversions: [SyncDiversion]
    let serverTimestamp: Date

    enum CodingKeys: String, CodingKey {
        case diversions
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
    let studentFacingUrl: String?

    enum CodingKeys: String, CodingKey {
        case settings
        case serverTimestamp = "server_timestamp"
        case studentFacingUrl = "student_facing_url"
    }
}
