import Foundation

struct ScanSession: Identifiable, Codable, Hashable {
    static func == (lhs: ScanSession, rhs: ScanSession) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    let id: UUID
    var label: String
    let startTime: Date
    var endTime: Date?
    var plates: [ScannedPlate]
    var diagnostics: [DiagnosticEntry]

    // Device & benchmark metadata (optional for backward compat)
    var deviceModel: String?
    var deviceChip: String?
    var deviceIdentifier: String?
    var connectionType: String?
    var cameraResolution: String?
    var cameraFPS: Int?
    var avgActualFPS: Double?
    var avgOCRTimeMs: Double?
    var peakOCRTimeMs: Double?
    var framesProcessed: Int?
    var framesSkipped: Int?
    var pixelThroughput: Double?
    var isBenchmark: Bool?

    var isActive: Bool { endTime == nil }

    var duration: TimeInterval {
        let end = endTime ?? Date()
        return end.timeIntervalSince(startTime)
    }

    var cameraNames: [String] {
        Array(Set(plates.map(\.cameraName).filter { !$0.isEmpty }))
    }

    var primaryCamera: String {
        let counts = Dictionary(grouping: plates, by: \.cameraName)
        return counts.max(by: { $0.value.count < $1.value.count })?.key ?? "Unknown"
    }

    var avgLatency: Double {
        guard !plates.isEmpty else { return 0 }
        return plates.map(\.detectionLatency).reduce(0, +) / Double(plates.count)
    }

    var medianLatency: Double {
        guard !plates.isEmpty else { return 0 }
        let sorted = plates.map(\.detectionLatency).sorted()
        let mid = sorted.count / 2
        if sorted.count.isMultiple(of: 2) {
            return (sorted[mid - 1] + sorted[mid]) / 2.0
        }
        return sorted[mid]
    }

    var avgConfidence: Double {
        guard !plates.isEmpty else { return 0 }
        return plates.map { Double($0.confidence) }.reduce(0, +) / Double(plates.count)
    }

    var platesPerMinute: Double {
        let mins = duration / 60.0
        guard mins > 0.1 else { return Double(plates.count) }
        return Double(plates.count) / mins
    }

    var frameSkipRatio: Double {
        let processed = framesProcessed ?? 0
        let skipped = framesSkipped ?? 0
        let total = processed + skipped
        guard total > 0 else { return 0 }
        return Double(skipped) / Double(total)
    }

    init(label: String) {
        self.id = UUID()
        self.label = label
        self.startTime = Date()
        self.endTime = nil
        self.plates = []
        self.diagnostics = []
    }
}
