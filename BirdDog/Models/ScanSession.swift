import Foundation

struct ScanSession: Identifiable, Codable {
    let id: UUID
    var label: String
    let startTime: Date
    var endTime: Date?
    var plates: [ScannedPlate]
    var diagnostics: [DiagnosticEntry]

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

    var avgConfidence: Double {
        guard !plates.isEmpty else { return 0 }
        return plates.map { Double($0.confidence) }.reduce(0, +) / Double(plates.count)
    }

    var platesPerMinute: Double {
        let mins = duration / 60.0
        guard mins > 0.1 else { return Double(plates.count) }
        return Double(plates.count) / mins
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
