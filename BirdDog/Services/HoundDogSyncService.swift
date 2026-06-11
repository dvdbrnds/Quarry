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
    @Published var isEnabled: Bool = false

    enum SyncState: String {
        case idle = "Idle"
        case syncing = "Syncing…"
        case synced = "Synced"
        case error = "Error"
        case offline = "Offline"
    }

    private static let lastPermitSyncKey = "HoundDogSync.lastPermitSync"
    private static let lastLotSyncKey = "HoundDogSync.lastLotSync"
    private static let syncIntervalSeconds: TimeInterval = 60

    private var syncTimer: Timer?
    private let monitor = NWPathMonitor()
    private var hasWifi = false
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
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.hasWifi = path.usesInterfaceType(.wifi) || path.usesInterfaceType(.wiredEthernet)
                if self?.isEnabled == true && (path.usesInterfaceType(.wifi) || path.usesInterfaceType(.wiredEthernet)) {
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

    func syncNow() async {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty, !settings.houndDogAPIKey.isEmpty else {
            syncState = .idle
            return
        }

        guard hasWifi else {
            syncState = .offline
            return
        }

        syncState = .syncing
        lastError = nil

        do {
            try await syncPermits()
            try await syncLots()
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
        if syncResponse.fullSync {
            try db.deleteAll()
        }

        let payload = PermitPayload(permits: syncResponse.permits.map { permit in
            PermitEntry(
                plateNormalized: permit.plates.first ?? "",
                plateRaw: permit.plates.joined(separator: ";"),
                plateState: "",
                ownerName: permit.name,
                permitNumber: permit.studentId,
                permitType: permit.permitType,
                permitStatus: permit.status,
                lotZone: permit.lotAssignment,
                vehicleDescription: "",
                issuedDate: permit.startDate,
                expirationDate: permit.endDate
            )
        })
        let count = try db.seedFromPayload(payload)
        permitCount = db.totalCount()
        lastPermitSync = syncResponse.serverTimestamp

        if count > 0 {
            print("[HoundDog] Synced \(count) permits (full=\(syncResponse.fullSync))")
        }
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
            let parkingLot = ParkingLot(id: lot.id, name: lot.name, boundary: boundary)

            if geofence.lots.contains(where: { $0.id == lot.id }) {
                if lot.deletedAt != nil {
                    geofence.deleteLot(id: lot.id)
                } else {
                    geofence.updateLot(parkingLot)
                }
            } else if lot.deletedAt == nil {
                geofence.addLot(parkingLot)
            }
        }

        lotCount = geofence.lots.count
        lastLotSync = syncResponse.serverTimestamp

        if !syncResponse.lots.isEmpty {
            print("[HoundDog] Synced \(syncResponse.lots.count) lots (full=\(syncResponse.fullSync))")
        }
    }

    // MARK: - Ticket Upload (stub for Phase 2)

    func uploadTicket(plate: String, lot: String, violationType: String, confidence: Double) async throws {
        let settings = AppSettings.shared
        guard !settings.houndDogURL.isEmpty else { return }

        guard let url = URL(string: "\(settings.houndDogURL)/api/sync/tickets") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(settings.houndDogAPIKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "plate": plate,
            "lot": lot,
            "violation_type": violationType,
            "confidence": confidence,
            "camera_name": "",
            "timestamp": ISO8601DateFormatter().string(from: Date()),
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 202 else {
            throw SyncError.serverError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }
    }

    // MARK: - Types

    enum SyncError: LocalizedError {
        case serverError(Int)

        var errorDescription: String? {
            switch self {
            case .serverError(let code): return "Server returned HTTP \(code)"
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

    enum CodingKeys: String, CodingKey {
        case id
        case studentId = "student_id"
        case name, plates
        case lotAssignment = "lot_assignment"
        case permitType = "permit_type"
        case startDate = "start_date"
        case endDate = "end_date"
        case status
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
    let deletedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, name, boundary
        case deletedAt = "deleted_at"
    }
}

struct SyncCoordinate: Decodable {
    let latitude: Double
    let longitude: Double
}
