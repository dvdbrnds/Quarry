import SwiftUI

struct ContentView: View {

    @StateObject private var viewModel = PlateReaderViewModel()
    @ObservedObject private var appSettings = AppSettings.shared
    @ObservedObject private var officerAuth = OfficerAuthService.shared
    @State private var showExportSheet = false
    @State private var showClearConfirm = false
    @State private var showExportOptions = false
    @State private var showDatabase = false
    @State private var showLotManagement = false
    @State private var showAdminSettings = false
    @State private var showSessionHistory = false
    @State private var showCameraLog = false
    @State private var showTicketIssuance = false
    @State private var showMovingViolation = false
    @State private var exportURLs: [URL] = []
    @State private var now = Date()

    private let tick = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                switch viewModel.cameraPermission {
                case .authorized:
                    scannerView
                case .denied, .restricted:
                    permissionDeniedView
                default:
                    ProgressView("Requesting camera access\u{2026}")
                        .foregroundStyle(.white)
                }
            }
            .preferredColorScheme(.dark)
            .navigationDestination(isPresented: $showDatabase) {
                DatabaseManagementView()
            }
            .navigationDestination(isPresented: $showLotManagement) {
                LotManagementView()
            }
            .navigationDestination(isPresented: $showAdminSettings) {
                AdminSettingsView(cameraService: viewModel.cameraService)
            }
        }
        .onAppear { viewModel.checkPermissionAndStart() }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.willResignActiveNotification)) { _ in
            viewModel.stopScanning()
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            if viewModel.cameraPermission == .authorized {
                viewModel.startScanning()
            }
        }
        .onReceive(tick) { now = $0 }
    }

    private var scannerView: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                ZStack {
                    CameraPreviewView(session: viewModel.cameraService.session, cameraSwitchCount: viewModel.cameraService.cameraSwitchCount)
                    PlateOverlayView(
                        plates: viewModel.currentPlates,
                        authStatus: viewModel.latestAuthStatus
                    )

                    VStack {
                        HStack(spacing: 8) {
                            cameraStatusBadge
                            liveStatsBadge
                            dbStatusBanner
                            currentLotBadge
                            if appSettings.useCloudOCR {
                                HStack(spacing: 4) {
                                    Image(systemName: "cloud.fill")
                                        .font(.caption2)
                                    Text("API")
                                        .font(.caption2.bold())
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .foregroundStyle(.white)
                                .background(.blue, in: Capsule())
                            }
                        }
                        .padding(.top, 8)
                        Spacer()
                        if viewModel.cameraService.focusMeterEnabled {
                            focusMeterOverlay
                                .padding(.bottom, 4)
                        }
                    }
                }
                .frame(height: geo.size.height * 0.58)
                .clipped()

                VStack(spacing: 0) {
                    ScanLogView(
                        log: viewModel.scanLog,
                        uniqueCount: viewModel.uniquePlateCount,
                        authorizedCount: viewModel.authorizedCount,
                        wrongLotCount: viewModel.wrongLotCount,
                        expiredCount: viewModel.expiredCount,
                        unknownCount: viewModel.unknownCount
                    )

                    Divider()

                    bottomBar
                        .padding(.horizontal)
                        .padding(.vertical, 8)
                }
                .background(Color(.systemBackground))
            }
        }
        .sheet(isPresented: $showExportSheet) {
            if !exportURLs.isEmpty {
                ShareSheet(activityItems: exportURLs)
            }
        }
        .alert("Clear Scan Log?", isPresented: $showClearConfirm) {
            Button("Clear", role: .destructive) { viewModel.clearLog() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will remove all \(viewModel.scanLog.count) scanned plates from this session.")
        }
        .sheet(isPresented: $showSessionHistory) {
            NavigationStack {
                SessionHistoryView(viewModel: viewModel)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Done") { showSessionHistory = false }
                        }
                    }
            }
        }
        .sheet(isPresented: $showCameraLog) {
            NavigationStack {
                CameraLogView(cameraService: viewModel.cameraService)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Done") { showCameraLog = false }
                        }
                    }
            }
        }
        .sheet(isPresented: $showTicketIssuance) {
            TicketIssuanceView()
        }
        .sheet(isPresented: $showMovingViolation) {
            MovingViolationView()
        }
    }

    @ViewBuilder
    private var dbStatusBanner: some View {
        if PlateDatabase.shared.isEmpty {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                Text("No permit data loaded")
                    .font(.caption2.bold())
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(.ultraThinMaterial, in: Capsule())
        } else if viewModel.unknownCount > 0 || viewModel.wrongLotCount > 0 {
            HStack(spacing: 10) {
                if viewModel.unknownCount > 0 {
                    HStack(spacing: 4) {
                        Image(systemName: "xmark.shield.fill")
                        Text("\(viewModel.unknownCount)")
                            .font(.caption.bold())
                    }
                    .foregroundStyle(.red)
                }
                if viewModel.wrongLotCount > 0 {
                    HStack(spacing: 4) {
                        Image(systemName: "location.slash.fill")
                        Text("\(viewModel.wrongLotCount) WRONG LOT")
                            .font(.caption.bold())
                    }
                    .foregroundStyle(.orange)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(.ultraThinMaterial, in: Capsule())
        }
    }

    @ViewBuilder
    private var currentLotBadge: some View {
        if let lotName = viewModel.geofenceService.currentLotName {
            HStack(spacing: 4) {
                Image(systemName: "mappin.circle.fill")
                    .font(.caption2)
                Text(lotName)
                    .font(.caption2.bold())
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.ultraThinMaterial, in: Capsule())
        }
    }

    private var liveStatsBadge: some View {
        let stats = viewModel.sessionStats
        return Group {
            if stats.count > 0 {
                HStack(spacing: 4) {
                    Image(systemName: "speedometer")
                        .font(.caption2)
                    Text("\(stats.count)p")
                        .font(.caption2.bold())
                    Text(String(format: "%.2fs", stats.avgLatency))
                        .font(.caption2)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .foregroundStyle(.white)
                .background(.ultraThinMaterial, in: Capsule())
            }
        }
    }

    private var cameraStatusBadge: some View {
        let status = viewModel.cameraService.cameraStatus
        return HStack(spacing: 4) {
            Image(systemName: status == .externalActive ? "video.fill" : status == .searchingExternal ? "video.badge.ellipsis" : "ipad.rear.camera")
                .font(.caption2)
            Text(status.rawValue)
                .font(.caption2.bold())
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .foregroundStyle(.white)
        .background(
            status == .externalActive ? Color.green :
            status == .searchingExternal ? Color.yellow :
            Color.gray,
            in: Capsule()
        )
        .foregroundStyle(status == .searchingExternal ? .black : .white)
        .onTapGesture { showCameraLog = true }
    }

    private var bottomBar: some View {
        HStack {
            Text(sessionDuration)
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()

            Spacer()

            Button {
                viewModel.audioAlertsEnabled.toggle()
            } label: {
                Image(systemName: viewModel.audioAlertsEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .font(.subheadline)
                    .foregroundStyle(viewModel.audioAlertsEnabled ? .primary : .secondary)
            }

            if officerAuth.isStaff {
                Button {
                    showTicketIssuance = true
                } label: {
                    Label("Ticket", systemImage: "doc.text")
                        .font(.subheadline)
                }

                Button {
                    showMovingViolation = true
                } label: {
                    Label("Citation", systemImage: "car.side")
                        .font(.subheadline)
                }
            }

            if officerAuth.isAdmin {
                Button {
                    showDatabase = true
                } label: {
                    Label("Database", systemImage: "server.rack")
                        .font(.subheadline)
                }

                Button {
                    showLotManagement = true
                } label: {
                    Label("Lots", systemImage: "map")
                        .font(.subheadline)
                }

                Button {
                    showAdminSettings = true
                } label: {
                    Label("Settings", systemImage: "gearshape")
                        .font(.subheadline)
                }
            }

            Button {
                showSessionHistory = true
            } label: {
                Label("Archive", systemImage: "archivebox")
                    .font(.subheadline)
            }

            Button {
                showClearConfirm = true
            } label: {
                Label("Clear", systemImage: "trash")
                    .font(.subheadline)
            }
            .disabled(viewModel.scanLog.isEmpty)

            Button {
                showExportOptions = true
            } label: {
                Label("Export", systemImage: "square.and.arrow.up")
                    .font(.subheadline)
            }
            .disabled(viewModel.scanLog.isEmpty)
            .confirmationDialog("Export Options", isPresented: $showExportOptions) {
                Button("Plates + Diagnostics (CSV)") {
                    var urls: [URL] = []
                    if let plates = LogExporter.exportCSV(from: viewModel.scanLog) { urls.append(plates) }
                    if let diag = LogExporter.exportDiagnosticCSV(from: viewModel.diagnosticLog) { urls.append(diag) }
                    if !urls.isEmpty {
                        exportURLs = urls
                        showExportSheet = true
                    }
                }
                Button("Performance Summary") {
                    var urls: [URL] = []
                    if let summary = LogExporter.exportSessionSummary(from: viewModel.scanLog) { urls.append(summary) }
                    if let csv = LogExporter.exportCSV(from: viewModel.scanLog) { urls.append(csv) }
                    if !urls.isEmpty {
                        exportURLs = urls
                        showExportSheet = true
                    }
                }
                Button("Cancel", role: .cancel) {}
            }

            Menu {
                Text(officerAuth.officerName)
                Text(officerAuth.officerEmail)
                    .font(.caption)
                Divider()
                Button(role: .destructive) {
                    officerAuth.logout()
                } label: {
                    Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                }
            } label: {
                Image(systemName: "person.crop.circle.fill")
                    .font(.subheadline)
                    .foregroundStyle(.green)
            }
        }
    }

    private var focusMeterOverlay: some View {
        let cs = viewModel.cameraService
        let ratio = cs.focusPeak > 0 ? cs.focusScore / cs.focusPeak : 0
        let color: Color = ratio > 0.9 ? .green : ratio > 0.6 ? .yellow : .red

        return HStack(spacing: 12) {
            Image(systemName: "scope")
                .font(.caption)
                .foregroundStyle(.white)
            Text("FOCUS")
                .font(.caption2.bold())
                .foregroundStyle(.white.opacity(0.7))
            Text(String(format: "%.0f", cs.focusScore))
                .font(.system(.title2, design: .monospaced))
                .bold()
                .foregroundStyle(color)
            Text(String(format: "peak %.0f", cs.focusPeak))
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.5))
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, 16)
    }


    private var permissionDeniedView: some View {
        VStack(spacing: 16) {
            Image(systemName: "camera.fill")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("Camera Access Required")
                .font(.title2.bold())
                .foregroundStyle(.white)
            Text("Bird Dog needs camera access to scan license plates. Open Settings and enable Camera for this app.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 32)
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var sessionDuration: String {
        let elapsed = now.timeIntervalSince(viewModel.sessionStartTime)
        let m = Int(elapsed) / 60
        let s = Int(elapsed) % 60
        return String(format: "%d:%02d", m, s)
    }

}

struct ShareSheet: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
