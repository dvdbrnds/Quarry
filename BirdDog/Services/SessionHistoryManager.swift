import Foundation

final class SessionHistoryManager {

    static let shared = SessionHistoryManager()

    private let sessionsDir: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let dir = docs.appendingPathComponent("scan_sessions", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    private let retentionDays: Int = 30

    private init() {
        pruneExpired()
    }

    func save(_ session: ScanSession) {
        let url = sessionsDir.appendingPathComponent("\(session.id.uuidString).json")
        do {
            let data = try encoder.encode(session)
            try data.write(to: url, options: .atomic)
        } catch {
            print("Failed to save session \(session.label): \(error)")
        }
    }

    func loadAll() -> [ScanSession] {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: sessionsDir,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: .skipsHiddenFiles
        ) else { return [] }

        return files
            .filter { $0.pathExtension == "json" }
            .compactMap { url -> ScanSession? in
                guard let data = try? Data(contentsOf: url) else { return nil }
                return try? decoder.decode(ScanSession.self, from: data)
            }
            .sorted { $0.startTime > $1.startTime }
    }

    func delete(_ session: ScanSession) {
        let url = sessionsDir.appendingPathComponent("\(session.id.uuidString).json")
        try? FileManager.default.removeItem(at: url)
    }

    func deleteAll() {
        let sessions = loadAll()
        for session in sessions {
            delete(session)
        }
    }

    /// Remove sessions older than `retentionDays`.
    func pruneExpired() {
        let cutoff = Calendar.current.date(byAdding: .day, value: -retentionDays, to: Date()) ?? Date()
        let sessions = loadAll()
        for session in sessions {
            let sessionDate = session.endTime ?? session.startTime
            if sessionDate < cutoff {
                delete(session)
            }
        }
    }
}
