import SwiftUI

struct BenchmarkCompareView: View {

    let sessions: [ScanSession]
    @State private var sessionA: ScanSession?
    @State private var sessionB: ScanSession?

    private let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .short
        f.timeStyle = .short
        return f
    }()

    var body: some View {
        List {
            pickerSection

            if let a = sessionA, let b = sessionB {
                deviceSection(a: a, b: b)
                bandwidthSection(a: a, b: b)
                processingSection(a: a, b: b)
                platesSection(a: a, b: b)
            } else {
                ContentUnavailableView(
                    "Select Two Sessions",
                    systemImage: "arrow.left.arrow.right",
                    description: Text("Pick two sessions above to compare device and processing performance side-by-side.")
                )
            }
        }
        .navigationTitle("Compare Sessions")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if sessions.count >= 2 {
                sessionA = sessions[0]
                sessionB = sessions[1]
            }
        }
    }

    // MARK: - Pickers

    private var pickerSection: some View {
        Section("Sessions") {
            Picker("Session A", selection: $sessionA) {
                Text("Select...").tag(ScanSession?.none)
                ForEach(sessions) { s in
                    Text(sessionLabel(s)).tag(ScanSession?.some(s))
                }
            }
            Picker("Session B", selection: $sessionB) {
                Text("Select...").tag(ScanSession?.none)
                ForEach(sessions) { s in
                    Text(sessionLabel(s)).tag(ScanSession?.some(s))
                }
            }
        }
    }

    private func sessionLabel(_ s: ScanSession) -> String {
        let device = s.deviceModel ?? "Unknown"
        let date = dateFormatter.string(from: s.startTime)
        return "\(device) — \(date)"
    }

    // MARK: - Device

    private func deviceSection(a: ScanSession, b: ScanSession) -> some View {
        Section("Device") {
            compareRow("Model", valA: a.deviceModel ?? "—", valB: b.deviceModel ?? "—")
            compareRow("Chip", valA: a.deviceChip ?? "—", valB: b.deviceChip ?? "—")
            compareRow("Connection", valA: a.connectionType ?? "—", valB: b.connectionType ?? "—")
            compareRow("Camera", valA: a.primaryCamera, valB: b.primaryCamera)
        }
    }

    // MARK: - Bandwidth

    private func bandwidthSection(a: ScanSession, b: ScanSession) -> some View {
        Section("Bandwidth") {
            compareRow("Resolution",
                        valA: a.cameraResolution ?? "—",
                        valB: b.cameraResolution ?? "—")
            compareRow("Configured FPS",
                        valA: fmtInt(a.cameraFPS),
                        valB: fmtInt(b.cameraFPS))
            compareNumeric("Actual FPS",
                           valA: a.avgActualFPS, valB: b.avgActualFPS,
                           format: "%.1f", higherIsBetter: true)
            compareNumeric("Pixel Throughput",
                           valA: a.pixelThroughput.map { $0 / 1_000_000 },
                           valB: b.pixelThroughput.map { $0 / 1_000_000 },
                           format: "%.1f Mpx/s", higherIsBetter: true)
            compareNumeric("Frames Processed",
                           valA: a.framesProcessed.map(Double.init),
                           valB: b.framesProcessed.map(Double.init),
                           format: "%.0f", higherIsBetter: true)
            compareNumeric("Frame Skip Ratio",
                           valA: a.frameSkipRatio * 100,
                           valB: b.frameSkipRatio * 100,
                           format: "%.0f%%", higherIsBetter: false)
        }
    }

    // MARK: - Processing

    private func processingSection(a: ScanSession, b: ScanSession) -> some View {
        Section("Processing Power") {
            compareNumeric("Avg OCR Time",
                           valA: a.avgOCRTimeMs, valB: b.avgOCRTimeMs,
                           format: "%.1f ms", higherIsBetter: false)
            compareNumeric("Peak OCR Time",
                           valA: a.peakOCRTimeMs, valB: b.peakOCRTimeMs,
                           format: "%.1f ms", higherIsBetter: false)
            compareNumeric("Avg Latency",
                           valA: a.avgLatency, valB: b.avgLatency,
                           format: "%.3f s", higherIsBetter: false)
            compareNumeric("Median Latency",
                           valA: a.medianLatency, valB: b.medianLatency,
                           format: "%.3f s", higherIsBetter: false)
            compareNumeric("Avg Confidence",
                           valA: a.avgConfidence * 100, valB: b.avgConfidence * 100,
                           format: "%.1f%%", higherIsBetter: true)
        }
    }

    // MARK: - Plates

    private func platesSection(a: ScanSession, b: ScanSession) -> some View {
        Section("Plate Detection") {
            compareNumeric("Plates Detected",
                           valA: Double(a.plates.count), valB: Double(b.plates.count),
                           format: "%.0f", higherIsBetter: true)
            compareNumeric("Plates/min",
                           valA: a.platesPerMinute, valB: b.platesPerMinute,
                           format: "%.1f", higherIsBetter: true)
            compareRow("Duration",
                        valA: formatDuration(a.duration),
                        valB: formatDuration(b.duration))
        }
    }

    // MARK: - Row Helpers

    private func compareRow(_ label: String, valA: String, valB: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Text(valA)
                    .font(.system(.callout, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                Divider()
                Text(valB)
                    .font(.system(.callout, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.vertical, 2)
    }

    private func compareNumeric(_ label: String,
                                valA: Double?, valB: Double?,
                                format: String,
                                higherIsBetter: Bool) -> some View {
        let a = valA ?? 0
        let b = valB ?? 0
        let delta: Double? = {
            guard let _ = valA, let _ = valB, a != 0 else { return nil }
            return ((b - a) / abs(a)) * 100
        }()

        let aWins: Bool? = {
            guard let _ = valA, let _ = valB, a != b else { return nil }
            return higherIsBetter ? a > b : a < b
        }()

        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if let delta {
                    let sign = delta > 0 ? "+" : ""
                    let good = higherIsBetter ? delta > 0 : delta < 0
                    Text("\(sign)\(String(format: "%.0f", delta))%")
                        .font(.caption2.bold())
                        .foregroundStyle(good ? .green : .red)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            (good ? Color.green : Color.red).opacity(0.15),
                            in: Capsule()
                        )
                }
            }
            HStack {
                Text(valA != nil ? String(format: format, a) : "—")
                    .font(.system(.callout, design: .monospaced))
                    .foregroundStyle(aWins == true ? .green : .primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Divider()
                Text(valB != nil ? String(format: format, b) : "—")
                    .font(.system(.callout, design: .monospaced))
                    .foregroundStyle(aWins == false ? .green : .primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.vertical, 2)
    }

    private func fmtInt(_ val: Int?) -> String {
        guard let v = val else { return "—" }
        return "\(v)"
    }

    private func formatDuration(_ d: TimeInterval) -> String {
        let mins = Int(d) / 60
        let secs = Int(d) % 60
        return "\(mins)m \(secs)s"
    }
}
