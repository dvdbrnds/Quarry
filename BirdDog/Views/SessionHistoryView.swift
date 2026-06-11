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
                if !session.primaryCamera.isEmpty {
                    Label(session.primaryCamera, systemImage: "camera")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                if !session.plates.isEmpty {
                    Text(String(format: "%.2fs avg", session.avgLatency))
                        .font(.caption2)
                        .foregroundStyle(.blue)
                    Text(String(format: "%.0f%% conf", session.avgConfidence * 100))
                        .font(.caption2)
                        .foregroundStyle(.green)
                }

                if !session.diagnostics.isEmpty {
                    Text("\(session.diagnostics.count) diag")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
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
            Section("Summary") {
                LabeledContent("Camera", value: session.primaryCamera)
                LabeledContent("Plates Detected", value: "\(session.plates.count)")
                LabeledContent("Duration", value: formatDuration(session.duration))
                if !session.plates.isEmpty {
                    LabeledContent("Plates/min", value: String(format: "%.1f", session.platesPerMinute))
                    LabeledContent("Avg Latency", value: String(format: "%.3fs", session.avgLatency))
                    LabeledContent("Avg Confidence", value: String(format: "%.1f%%", session.avgConfidence * 100))

                    let medLat = medianLatency(session.plates)
                    LabeledContent("Median Latency", value: String(format: "%.3fs", medLat))

                    let minLat = session.plates.map(\.detectionLatency).min() ?? 0
                    let maxLat = session.plates.map(\.detectionLatency).max() ?? 0
                    LabeledContent("Min / Max Latency", value: String(format: "%.3f / %.3fs", minLat, maxLat))
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

    private func medianLatency(_ plates: [ScannedPlate]) -> Double {
        guard !plates.isEmpty else { return 0 }
        let sorted = plates.map(\.detectionLatency).sorted()
        let mid = sorted.count / 2
        if sorted.count.isMultiple(of: 2) {
            return (sorted[mid - 1] + sorted[mid]) / 2.0
        }
        return sorted[mid]
    }
}
