import SwiftUI

struct ContentView: View {

    @StateObject private var viewModel = PlateReaderViewModel()
    @ObservedObject private var appSettings = AppSettings.shared
    @ObservedObject private var officerAuth = OfficerAuthService.shared
    @State private var showExportSheet = false
    @State private var showClearConfirm = false
    @State private var showDatabase = false
    @State private var showLotManagement = false
    @State private var showAdminSettings = false
    @State private var showSessionHistory = false
    @State private var showCameraLog = false
    @State private var showTicketIssuance = false
    @State private var showMovingViolation = false
    @State private var ticketPrefilledPlate: String?
    @State private var ticketPrefilledEntry: ScannedPlate?
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
                if PlateDatabase.isReady {
                    DatabaseManagementView()
                        .modelContainer(PlateDatabase.shared.container)
                } else {
                    ProgressView("Loading database…")
                }
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
            viewModel.pauseScanning()
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            let anyScreenOpen = showTicketIssuance || showMovingViolation
                || showDatabase || showLotManagement || showAdminSettings
                || showSessionHistory
            if viewModel.cameraPermission == .authorized
                && !viewModel.isScanningPaused
                && !anyScreenOpen {
                viewModel.startScanning()
            }
        }
        .onReceive(tick) { t in
            let anyScreenOpen = showTicketIssuance || showMovingViolation
                || showDatabase || showLotManagement || showAdminSettings
                || showSessionHistory
            if !anyScreenOpen {
                now = t
            }
        }
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

                    VStack(spacing: 6) {
                        HStack {
                            cameraStatusBadge
                            Spacer()
                            dbStatusBanner
                            Spacer()
                            currentLotBadge
                        }
                        .padding(.horizontal, 12)
                        .padding(.top, 8)

                        if appSettings.showLiveStats {
                            liveStatsBadge
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 12)
                        }

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
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 12)
                        }

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
                        unknownCount: viewModel.unknownCount,
                        onIssueTapped: officerAuth.isStaff ? { entry in
                            viewModel.pauseScanning()
                            ticketPrefilledEntry = entry
                            ticketPrefilledPlate = entry.text
                            showTicketIssuance = true
                        } : nil
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
            TicketIssuanceView(
                cameraService: viewModel.cameraService,
                prefilledPlate: ticketPrefilledPlate,
                prefilledEntry: ticketPrefilledEntry,
                onTicketIssued: { plate in
                    viewModel.markPlateTicketed(plate)
                }
            )
            .onDisappear {
                ticketPrefilledPlate = nil
                ticketPrefilledEntry = nil
            }
        }
        .sheet(isPresented: $showMovingViolation) {
            MovingViolationView(cameraService: viewModel.cameraService)
        }
        .onChange(of: showTicketIssuance) { _, isOpen in
            if !isOpen { viewModel.resumeScanning() }
        }
        .onChange(of: showMovingViolation) { _, isOpen in
            if !isOpen { viewModel.resumeScanning() }
        }
        .onChange(of: showDatabase) { _, isOpen in
            if !isOpen { viewModel.resumeScanning() }
        }
        .onChange(of: showLotManagement) { _, isOpen in
            if !isOpen { viewModel.resumeScanning() }
        }
        .onChange(of: showAdminSettings) { _, isOpen in
            if !isOpen { viewModel.resumeScanning() }
        }
        .onChange(of: showSessionHistory) { _, isOpen in
            if !isOpen { viewModel.resumeScanning() }
        }
    }

    @ViewBuilder
    private var dbStatusBanner: some View {
        if PlateDatabase.isReady && PlateDatabase.shared.isEmpty {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                Text("No permit data — sync")
                    .font(.caption2.bold())
                    .lineLimit(1)
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
                            .font(.subheadline.bold())
                    }
                    .foregroundStyle(.red)
                }
                if viewModel.wrongLotCount > 0 {
                    HStack(spacing: 4) {
                        Image(systemName: "location.slash.fill")
                        Text("\(viewModel.wrongLotCount)")
                            .font(.subheadline.bold())
                    }
                    .foregroundStyle(.orange)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(.ultraThinMaterial, in: Capsule())
        }
    }

    @ViewBuilder
    private var currentLotBadge: some View {
        let geo = viewModel.geofenceService
        if let lotName = geo.currentLotName {
            HStack(spacing: 4) {
                Image(systemName: "mappin.circle.fill")
                    .font(.caption2)
                Text(lotName)
                    .font(.caption2.bold())
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .foregroundStyle(.white)
            .background(PlateStatus.allowedGreen, in: Capsule())
        } else {
            HStack(spacing: 4) {
                Image(systemName: lotStatusIcon(for: geo))
                    .font(.caption2)
                Text(lotStatusLabel(for: geo))
                    .font(.caption2.bold())
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .foregroundStyle(lotStatusForeground(for: geo))
            .background(lotStatusBackground(for: geo), in: Capsule())
        }
    }

    private func lotStatusIcon(for geo: GeofenceService) -> String {
        switch geo.locationStatus {
        case .authorizedWhenInUse, .authorizedAlways:
            return geo.currentLocation == nil ? "location" : "mappin.slash"
        case .denied, .restricted:
            return "location.slash"
        default:
            return "location"
        }
    }

    private func lotStatusLabel(for geo: GeofenceService) -> String {
        switch geo.locationStatus {
        case .authorizedWhenInUse, .authorizedAlways:
            if geo.currentLocation == nil { return "GPS…" }
            if geo.lots.isEmpty { return "No lots synced" }
            return "Outside lots"
        case .denied, .restricted:
            return "Location off"
        default:
            return "Enable GPS"
        }
    }

    private func lotStatusForeground(for geo: GeofenceService) -> Color {
        switch geo.locationStatus {
        case .denied, .restricted: return .white
        default: return .black
        }
    }

    private func lotStatusBackground(for geo: GeofenceService) -> Color {
        switch geo.locationStatus {
        case .authorizedWhenInUse, .authorizedAlways:
            return geo.currentLocation == nil ? .yellow : .orange
        case .denied, .restricted:
            return .red
        default:
            return .yellow
        }
    }

    private var liveStatsBadge: some View {
        let stats = viewModel.sessionStats
        let m = viewModel.cameraService.liveMetrics
        return Group {
            if stats.count > 0 || m.framesReceived > 0 {
                HStack(spacing: 6) {
                    if stats.count > 0 {
                        Image(systemName: "speedometer")
                            .font(.caption2)
                        Text("\(stats.count)p")
                            .font(.caption2.bold())
                        Text(String(format: "%.2fs", stats.avgLatency))
                            .font(.caption2)
                    }
                    if m.actualFPS > 0 {
                        Text(String(format: "%.0ffps", m.actualFPS))
                            .font(.caption2)
                            .foregroundStyle(.cyan)
                    }
                    if m.avgOCRTimeMs > 0 {
                        Text(String(format: "%.0fms", m.avgOCRTimeMs))
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    }
                    if m.framesReceived > 100 {
                        Text(String(format: "%.0f%% skip", m.skipRatio * 100))
                            .font(.caption2)
                            .foregroundStyle(m.skipRatio > 0.7 ? .red : .yellow)
                    }
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
        HStack(spacing: 16) {
            Text(sessionDuration)
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()

            Spacer()

            Button {
                viewModel.audioAlertsEnabled.toggle()
            } label: {
                Image(systemName: viewModel.audioAlertsEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .font(.body)
                    .foregroundStyle(viewModel.audioAlertsEnabled ? .primary : .secondary)
            }

            if officerAuth.isStaff {
                Menu {
                    Button {
                        viewModel.pauseScanning()
                        ticketPrefilledPlate = nil
                        ticketPrefilledEntry = nil
                        showTicketIssuance = true
                    } label: {
                        Label("Parking Ticket", systemImage: "doc.text")
                    }
                    Button {
                        viewModel.pauseScanning()
                        showMovingViolation = true
                    } label: {
                        Label("Moving Citation", systemImage: "car.side")
                    }
                } label: {
                    Image(systemName: "plus.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.blue)
                }
            }

            if officerAuth.isStaff {
                Menu {
                    if officerAuth.isAdmin {
                        Button {
                            viewModel.pauseScanning()
                            showDatabase = true
                        } label: {
                            Label("Database", systemImage: "server.rack")
                        }
                        Button {
                            viewModel.pauseScanning()
                            showLotManagement = true
                        } label: {
                            Label("Lots", systemImage: "map")
                        }
                        Divider()
                    }
                    Button {
                        viewModel.pauseScanning()
                        showAdminSettings = true
                    } label: {
                        Label("Settings", systemImage: "gearshape")
                    }
                } label: {
                    Image(systemName: "gearshape")
                        .font(.body)
                }
            }

            Menu {
                Button {
                    viewModel.pauseScanning()
                    showSessionHistory = true
                } label: {
                    Label("Session History", systemImage: "archivebox")
                }
                Button(role: .destructive) {
                    showClearConfirm = true
                } label: {
                    Label("Clear Log", systemImage: "trash")
                }
                .disabled(viewModel.scanLog.isEmpty)
                Divider()
                Button {
                    var urls: [URL] = []
                    if let plates = LogExporter.exportCSV(from: viewModel.scanLog) { urls.append(plates) }
                    if let diag = LogExporter.exportDiagnosticCSV(from: viewModel.diagnosticLog) { urls.append(diag) }
                    if !urls.isEmpty {
                        exportURLs = urls
                        showExportSheet = true
                    }
                } label: {
                    Label("Export CSV", systemImage: "tablecells")
                }
                .disabled(viewModel.scanLog.isEmpty)
                Button {
                    var urls: [URL] = []
                    if let summary = LogExporter.exportSessionSummary(from: viewModel.scanLog) { urls.append(summary) }
                    if let csv = LogExporter.exportCSV(from: viewModel.scanLog) { urls.append(csv) }
                    if !urls.isEmpty {
                        exportURLs = urls
                        showExportSheet = true
                    }
                } label: {
                    Label("Performance Summary", systemImage: "chart.bar")
                }
                .disabled(viewModel.scanLog.isEmpty)
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.body)
            }

            Menu {
                Text(officerAuth.officerName)
                Text(officerAuth.officerEmail)
                Divider()
                Button(role: .destructive) {
                    officerAuth.logout()
                } label: {
                    Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                }
            } label: {
                Image(systemName: "person.crop.circle.fill")
                    .font(.body)
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
