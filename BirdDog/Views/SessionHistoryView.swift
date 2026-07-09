import SwiftUI

struct SessionHistoryView: View {

    @ObservedObject var viewModel: PlateReaderViewModel
    @State private var exportURLs: [URL] = []
    @State private var showExport = false
    @State private var showDeleteAll = false
    @State private var showCompare = false

    private let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .short
        f.timeStyle = .short
        return f
    }()

    var body: some View {
        List {
            if viewModel.sessionHistory.isEmpty {
                ContentUnavailableView(
                    "No Archive Data",
                    systemImage: "archivebox",
                    description: Text("Previous days' scans are archived here automatically and kept for 30 days.")
                )
            }

            ForEach(viewModel.sessionHistory) { session in
                NavigationLink {
                    SessionDetailView(session: session, viewModel: viewModel)
                } label: {
                    sessionRow(session)
                }
            }
            .onDelete { indices in
                for idx in indices {
                    viewModel.deleteSession(viewModel.sessionHistory[idx])
                }
            }

            if viewModel.sessionHistory.count >= 2 {
                Section {
                    NavigationLink {
                        BenchmarkCompareView(sessions: viewModel.sessionHistory)
                    } label: {
                        Label("Compare Sessions", systemImage: "arrow.left.arrow.right")
                    }

                    Button {
                        var urls: [URL] = []
                        if let report = LogExporter.exportBenchmarkSummary(from: viewModel.sessionHistory) { urls.append(report) }
                        if let csv = LogExporter.exportBenchmarkCSV(from: viewModel.sessionHistory) { urls.append(csv) }
                        if !urls.isEmpty {
                            exportURLs = urls
                            showExport = true
                        }
                    } label: {
                        Label("Export Benchmark Report", systemImage: "gauge.with.dots.needle.67percent")
                    }

                    Button {
                        let all = viewModel.sessionHistory.flatMap(\.plates)
                        var urls: [URL] = []
                        if let summary = LogExporter.exportSessionSummary(from: all) { urls.append(summary) }
                        if let csv = LogExporter.exportCSV(from: all) { urls.append(csv) }
                        if !urls.isEmpty {
                            exportURLs = urls
                            showExport = true
                        }
                    } label: {
                        Label("Export All Sessions Summary", systemImage: "chart.bar.doc.horizontal")
                    }
                }
            }
        }
        .navigationTitle("Session History")
        .toolbar {
            if !viewModel.sessionHistory.isEmpty {
                ToolbarItem(placement: .destructiveAction) {
                    Button("Delete All", role: .destructive) {
                        showDeleteAll = true
                    }
                }
            }
        }
        .alert("Delete All Sessions?", isPresented: $showDeleteAll) {
            Button("Delete All", role: .destructive) {
                viewModel.deleteAllSessions()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will permanently remove all saved session data.")
        }
        .sheet(isPresented: $showExport) {
            if !exportURLs.isEmpty {
                ShareSheet(activityItems: exportURLs)
            }
        }
        .onAppear {
            viewModel.reloadHistory()
        }
    }

    private func sessionRow(_ session: ScanSession) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(session.label)
                    .font(.headline)
                Spacer()
                Text("\(session.plates.count) plates")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 12) {
                Label(dateFormatter.string(from: session.startTime), systemImage: "clock")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if session.duration > 0 {
                    Text(formatDuration(session.duration))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 12) {
                if let device = session.deviceModel {
                    Label(device, systemImage: "ipad")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                if !session.primaryCamera.isEmpty {
                    Label(session.primaryCamera, systemImage: "camera")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            HStack(spacing: 12) {
                if !session.plates.isEmpty {
                    Text(String(format: "%.2fs avg", session.avgLatency))
                        .font(.caption2)
                        .foregroundStyle(.blue)
                    Text(String(format: "%.0f%% conf", session.avgConfidence * 100))
                        .font(.caption2)
                        .foregroundStyle(.green)
                }

                if let ocr = session.avgOCRTimeMs, ocr > 0 {
                    Text(String(format: "%.0fms OCR", ocr))
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }

                if let fps = session.avgActualFPS, fps > 0 {
                    Text(String(format: "%.0f fps", fps))
                        .font(.caption2)
                        .foregroundStyle(.purple)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func formatDuration(_ d: TimeInterval) -> String {
        let mins = Int(d) / 60
        let secs = Int(d) % 60
        return "\(mins)m \(secs)s"
    }
}

struct SessionDetailView: View {

    let session: ScanSession
    @ObservedObject var viewModel: PlateReaderViewModel
    @State private var exportURLs: [URL] = []
    @State private var showExport = false

    var body: some View {
        List {
            if session.deviceModel != nil {
                Section("Device") {
                    if let model = session.deviceModel {
                        LabeledContent("Model", value: model)
                    }
                    if let chip = session.deviceChip {
                        LabeledContent("Chip", value: chip)
                    }
                    if let conn = session.connectionType {
                        LabeledContent("Connection", value: conn)
                    }
                }
            }

            Section("Summary") {
                LabeledContent("Camera", value: session.primaryCamera)
                LabeledContent("Plates Detected", value: "\(session.plates.count)")
                LabeledContent("Duration", value: formatDuration(session.duration))
                if !session.plates.isEmpty {
                    LabeledContent("Plates/min", value: String(format: "%.1f", session.platesPerMinute))
                    LabeledContent("Avg Latency", value: String(format: "%.3fs", session.avgLatency))
                    LabeledContent("Median Latency", value: String(format: "%.3fs", session.medianLatency))
                    LabeledContent("Avg Confidence", value: String(format: "%.1f%%", session.avgConfidence * 100))

                    let minLat = session.plates.map(\.detectionLatency).min() ?? 0
                    let maxLat = session.plates.map(\.detectionLatency).max() ?? 0
                    LabeledContent("Min / Max Latency", value: String(format: "%.3f / %.3fs", minLat, maxLat))
                }
            }

            if session.framesProcessed != nil || session.avgOCRTimeMs != nil {
                Section("Pipeline Performance") {
                    if let res = session.cameraResolution {
                        LabeledContent("Resolution", value: res)
                    }
                    if let fps = session.cameraFPS, fps > 0 {
                        LabeledContent("Configured FPS", value: "\(fps)")
                    }
                    if let fps = session.avgActualFPS, fps > 0 {
                        LabeledContent("Actual FPS", value: String(format: "%.1f", fps))
                    }
                    if let tp = session.pixelThroughput, tp > 0 {
                        LabeledContent("Pixel Throughput", value: String(format: "%.1f Mpx/s", tp / 1_000_000))
                    }
                    if let ocr = session.avgOCRTimeMs, ocr > 0 {
                        LabeledContent("Avg OCR Time", value: String(format: "%.1f ms", ocr))
                    }
                    if let peak = session.peakOCRTimeMs, peak > 0 {
                        LabeledContent("Peak OCR Time", value: String(format: "%.1f ms", peak))
                    }
                    if let processed = session.framesProcessed {
                        LabeledContent("Frames Processed", value: "\(processed)")
                    }
                    if let skipped = session.framesSkipped {
                        LabeledContent("Frames Skipped", value: "\(skipped)")
                    }
                    if session.frameSkipRatio > 0 {
                        LabeledContent("Skip Ratio", value: String(format: "%.0f%%", session.frameSkipRatio * 100))
                    }
                }
            }

            Section("Auth Breakdown") {
                let auth = session.plates.filter { if case .authorized = $0.authStatus { return true }; return false }.count
                let unknown = session.plates.filter { if case .unknown = $0.authStatus { return true }; return false }.count
                let expired = session.plates.filter { if case .expired = $0.authStatus { return true }; return false }.count
                let wrongLot = session.plates.filter { if case .wrongLot = $0.authStatus { return true }; return false }.count

                LabeledContent("Authorized", value: "\(auth)")
                LabeledContent("Unknown", value: "\(unknown)")
                LabeledContent("Expired", value: "\(expired)")
                LabeledContent("Wrong Lot", value: "\(wrongLot)")
            }

            Section("Plates") {
                ForEach(session.plates) { plate in
                    HStack {
                        Text(plate.text)
                            .font(.system(.body, design: .monospaced))
                            .bold()
                        Spacer()
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(plate.authStatus.label)
                                .font(.caption)
                                .foregroundStyle(plate.authStatus.color)
                            Text(String(format: "%.2fs / %.0f%%", plate.detectionLatency, plate.confidence * 100))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle(session.label)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    var urls: [URL] = []
                    if let summary = LogExporter.exportSessionSummary(from: session.plates) { urls.append(summary) }
                    if let csv = LogExporter.exportCSV(from: session.plates) { urls.append(csv) }
                    if !session.diagnostics.isEmpty,
                       let diag = LogExporter.exportDiagnosticCSV(from: session.diagnostics) {
                        urls.append(diag)
                    }
                    if !urls.isEmpty {
                        exportURLs = urls
                        showExport = true
                    }
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
            }
        }
        .sheet(isPresented: $showExport) {
            if !exportURLs.isEmpty {
                ShareSheet(activityItems: exportURLs)
            }
        }
    }

    private func formatDuration(_ d: TimeInterval) -> String {
        let mins = Int(d) / 60
        let secs = Int(d) % 60
        return "\(mins)m \(secs)s"
    }
}
