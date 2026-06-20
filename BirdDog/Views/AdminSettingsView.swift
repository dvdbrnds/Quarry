import SwiftUI
import UniformTypeIdentifiers

struct AdminSettingsView: View {

    @ObservedObject var cameraService: CameraService
    @ObservedObject private var appSettings = AppSettings.shared
    @ObservedObject private var syncService = HoundDogSyncService.shared
    @ObservedObject private var officerAuth = OfficerAuthService.shared
    @State private var showPermitImporter = false
    @State private var showLotImporter = false
    @State private var showPasscodeChange = false
    @State private var showQRScanner = false
    @State private var importMessage: String?
    @State private var showImportAlert = false
    @State private var importAlertIsError = false

    var body: some View {
        List {
            officerSection
            cameraSection
            printerSection
            schoolSection
            houndDogSection
            oktaSection
            ocrEngineSection
            dataSection
            securitySection
            appInfoSection
        }
        .navigationTitle("Admin Settings")
        .navigationBarTitleDisplayMode(.inline)
        .fileImporter(
            isPresented: $showPermitImporter,
            allowedContentTypes: [UTType.json],
            allowsMultipleSelection: false
        ) { result in
            handlePermitImport(result)
        }
        .fileImporter(
            isPresented: $showLotImporter,
            allowedContentTypes: [UTType.json],
            allowsMultipleSelection: false
        ) { result in
            handleLotImport(result)
        }
        .alert(importAlertIsError ? "Import Failed" : "Import Successful", isPresented: $showImportAlert) {
            Button("OK") {}
        } message: {
            if let msg = importMessage {
                Text(msg)
            }
        }
        .fullScreenCover(isPresented: $showQRScanner) {
            QRScannerView(isPresented: $showQRScanner, onPaired: {})
        }
    }

    // MARK: - Officer

    private var officerSection: some View {
        Section {
            HStack {
                Text("Officer")
                Spacer()
                Text(officerAuth.officerName)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Text("Email")
                Spacer()
                Text(officerAuth.officerEmail)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            HStack {
                Text("Role")
                Spacer()
                Text(officerAuth.isAdmin ? "Admin" : officerAuth.isStaff ? "Staff" : "Officer")
                    .foregroundStyle(.secondary)
            }
            Button(role: .destructive) {
                officerAuth.logout()
            } label: {
                Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
            }
        } header: {
            Text("Signed-In Officer")
        } footer: {
            Text("Officer identity is attached to every ticket as a digital signature.")
        }
    }

    // MARK: - Camera Diagnostics

    private var cameraSection: some View {
        Section {
            infoRow("Camera", value: cameraService.activeCameraName)
            infoRow("Status", value: cameraService.cameraStatus.rawValue)
            infoRow("Resolution", value: cameraService.activeResolution)
            infoRow("Frame Rate", value: cameraService.activeFPS)
            infoRow("Devices Detected", value: "\(cameraService.detectedDeviceCount)")

            Button {
                cameraService.forceReconnect()
            } label: {
                Label("Reconnect Camera", systemImage: "arrow.triangle.2.circlepath.camera")
            }

            DisclosureGroup("Camera Log") {
                if cameraService.debugLog.isEmpty {
                    Text("No log entries")
                        .foregroundStyle(.secondary)
                        .font(.caption)
                } else {
                    ForEach(Array(cameraService.debugLog.suffix(15).enumerated()), id: \.offset) { _, entry in
                        Text(entry)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Camera")
        } footer: {
            Text("If the external camera is not detected through a USB hub, try Reconnect Camera or unplug and replug the hub.")
        }
    }

    // MARK: - Printer

    private var printerSection: some View {
        Section {
            NavigationLink {
                PrinterSettingsView()
            } label: {
                HStack {
                    Label("Thermal Printer", systemImage: "printer.fill")
                    Spacer()
                    HStack(spacing: 6) {
                        Circle()
                            .fill(printerStatusColor)
                            .frame(width: 8, height: 8)
                        Text(PrinterService.shared.connectionState.rawValue)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Printer")
        } footer: {
            Text("Connect a Star Micronics thermal printer via Bluetooth LE to print tickets in the field.")
        }
    }

    private var printerStatusColor: Color {
        switch PrinterService.shared.connectionState {
        case .connected: return .green
        case .connecting: return .orange
        case .error: return .red
        case .disconnected: return .gray
        }
    }

    // MARK: - School

    private var schoolSection: some View {
        Section {
            HStack {
                Text("School Name")
                Spacer()
                TextField("e.g. Moravian University", text: $appSettings.schoolName)
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("Organization")
        } footer: {
            Text("Displayed in the app header and included in export metadata.")
        }
    }

    // MARK: - HoundDog Server

    private var houndDogSection: some View {
        Section {
            HStack {
                Text("Server URL")
                Spacer()
                TextField("https://hounddog.example.com", text: $appSettings.houndDogURL)
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
            }

            HStack {
                Text("API Key")
                Spacer()
                SecureField("Device API key", text: $appSettings.houndDogAPIKey)
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }

            Toggle(isOn: $syncService.isEnabled) {
                Label("Auto-Sync", systemImage: "arrow.triangle.2.circlepath")
            }
            .onChange(of: syncService.isEnabled) { _, enabled in
                if enabled {
                    syncService.start()
                } else {
                    syncService.stop()
                }
            }

            HStack {
                Text("Status")
                Spacer()
                HStack(spacing: 6) {
                    Circle()
                        .fill(syncStatusColor)
                        .frame(width: 8, height: 8)
                    Text(syncService.syncState.rawValue)
                        .foregroundStyle(.secondary)
                }
            }

            if let lastSync = syncService.lastSyncDate {
                infoRow("Last Sync", value: lastSync.formatted(.dateTime.hour().minute().second()))
            }

            if let error = syncService.lastError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            Button {
                Task { await syncService.syncNow() }
            } label: {
                Label("Sync Now", systemImage: "arrow.clockwise")
            }
            .disabled(appSettings.houndDogURL.isEmpty || appSettings.houndDogAPIKey.isEmpty)

            Button {
                showQRScanner = true
            } label: {
                Label("Scan Pairing QR Code", systemImage: "qrcode.viewfinder")
            }
        } header: {
            Text("Quarry Server")
        } footer: {
            Text("Connect to your school's Quarry server for centralized permit and lot management. Permits and lots sync automatically.")
        }
    }

    private var syncStatusColor: Color {
        switch syncService.syncState {
        case .synced: return .green
        case .syncing: return .orange
        case .error: return .red
        case .offline: return .gray
        case .idle: return .gray
        }
    }

    // MARK: - Okta SSO

    private var oktaSection: some View {
        Section {
            HStack {
                Text("Issuer URL")
                Spacer()
                TextField("https://example.okta.com/oauth2/default", text: $appSettings.oktaIssuer)
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
            }

            HStack {
                Text("Client ID")
                Spacer()
                TextField("Okta app client ID", text: $appSettings.oktaClientId)
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }

            HStack {
                Text("Redirect URI")
                Spacer()
                TextField("edu.moravian.birddog://callback", text: $appSettings.oktaRedirectURI)
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.secondary)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }

            HStack {
                Text("Status")
                Spacer()
                HStack(spacing: 6) {
                    Circle()
                        .fill(appSettings.isOktaConfigured ? .green : .gray)
                        .frame(width: 8, height: 8)
                    Text(appSettings.isOktaConfigured ? "Configured" : "Not Configured")
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Officer Authentication (Okta)")
        } footer: {
            Text("Okta SSO settings are normally auto-configured during QR pairing. Create a Native app in Okta with Authorization Code + PKCE grant.")
        }
    }

    // MARK: - OCR Engine

    private var ocrEngineSection: some View {
        Section {
            Toggle(isOn: $appSettings.useCloudOCR) {
                Label("PlateRecognizer API", systemImage: "cloud.fill")
            }
            .onChange(of: appSettings.useCloudOCR) { _, _ in
                NotificationCenter.default.post(name: .ocrEngineChanged, object: nil)
            }

            if appSettings.useCloudOCR {
                HStack {
                    Text("API Key")
                    Spacer()
                    SecureField("Paste token here", text: $appSettings.plateRecognizerAPIKey)
                        .multilineTextAlignment(.trailing)
                        .foregroundStyle(.secondary)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
                .onChange(of: appSettings.plateRecognizerAPIKey) { _, _ in
                    NotificationCenter.default.post(name: .ocrEngineChanged, object: nil)
                }
            }
        } header: {
            Text("OCR Engine")
        } footer: {
            if appSettings.useCloudOCR {
                Text("Frames are sent to PlateRecognizer cloud API. Requires internet. Free tier: 2,500 lookups/month.")
            } else {
                Text("Using on-device Apple Vision OCR. No internet required.")
            }
        }
    }

    // MARK: - Data

    private var dataSection: some View {
        Section {
            Button {
                showPermitImporter = true
            } label: {
                HStack {
                    Label("Import Permits", systemImage: "doc.badge.plus")
                    Spacer()
                    Text("\(PlateDatabase.shared.totalCount()) loaded")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Button {
                showLotImporter = true
            } label: {
                HStack {
                    Label("Import Lots", systemImage: "map.fill")
                    Spacer()
                    Text("\(GeofenceService.shared.lots.count) defined")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Data Management")
        } footer: {
            Text("Import JSON files via AirDrop, Files, or any file source. Permit files must match the permits.json format. Lot files must be an array of lot objects.")
        }
    }

    // MARK: - Security

    private var securitySection: some View {
        Section {
            Button {
                showPasscodeChange = true
            } label: {
                Label("Change Admin Passcode", systemImage: "key.fill")
            }
        } header: {
            Text("Security")
        }
        .sheet(isPresented: $showPasscodeChange) {
            ChangePasscodeView(appSettings: appSettings)
        }
    }

    // MARK: - App Info

    private var appInfoSection: some View {
        Section("About") {
            infoRow("Version", value: appVersion)
            infoRow("Build", value: buildNumber)
            infoRow("Permits", value: "\(PlateDatabase.shared.totalCount()) (\(PlateDatabase.shared.validCount()) valid)")
            infoRow("Lots", value: "\(GeofenceService.shared.lots.count)")
            if syncService.isEnabled && !appSettings.houndDogURL.isEmpty {
                infoRow("Data Source", value: "HoundDog server")
            } else if LocalDataProvider.shared.hasImportedPermits {
                infoRow("Data Source", value: "Imported file")
            } else {
                infoRow("Data Source", value: "Bundled")
            }
        }
    }

    private func infoRow(_ label: String, value: String) -> some View {
        HStack {
            Text(label)
            Spacer()
            Text(value)
                .foregroundStyle(.secondary)
        }
    }

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
    }

    private var buildNumber: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "—"
    }

    // MARK: - Import Handlers

    private func handlePermitImport(_ result: Result<[URL], Error>) {
        do {
            guard let url = try result.get().first else { return }
            guard url.startAccessingSecurityScopedResource() else {
                showError("Unable to access the selected file.")
                return
            }
            defer { url.stopAccessingSecurityScopedResource() }

            let data = try Data(contentsOf: url)
            let count = try LocalDataProvider.shared.importPermits(from: data)
            importMessage = "Imported \(count) permit records successfully."
            importAlertIsError = false
            showImportAlert = true
        } catch {
            showError("Failed to import permits: \(error.localizedDescription)")
        }
    }

    private func handleLotImport(_ result: Result<[URL], Error>) {
        do {
            guard let url = try result.get().first else { return }
            guard url.startAccessingSecurityScopedResource() else {
                showError("Unable to access the selected file.")
                return
            }
            defer { url.stopAccessingSecurityScopedResource() }

            let data = try Data(contentsOf: url)
            let count = try LocalDataProvider.shared.importLots(from: data)
            importMessage = "Imported \(count) parking lots successfully."
            importAlertIsError = false
            showImportAlert = true
        } catch {
            showError("Failed to import lots: \(error.localizedDescription)")
        }
    }

    private func showError(_ message: String) {
        importMessage = message
        importAlertIsError = true
        showImportAlert = true
    }
}

// MARK: - Change Passcode

struct ChangePasscodeView: View {

    @ObservedObject var appSettings: AppSettings
    @Environment(\.dismiss) private var dismiss

    @State private var currentCode = ""
    @State private var newCode = ""
    @State private var confirmCode = ""
    @State private var errorMessage: String?
    @State private var step: Step = .verifyCurrent

    enum Step {
        case verifyCurrent, enterNew, confirmNew
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                Image(systemName: stepIcon)
                    .font(.system(size: 40))
                    .foregroundStyle(.blue)

                Text(stepTitle)
                    .font(.title3.bold())

                codeField

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }

                Spacer()
            }
            .padding()
            .navigationTitle("Change Passcode")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private var stepIcon: String {
        switch step {
        case .verifyCurrent: return "lock.fill"
        case .enterNew: return "key.fill"
        case .confirmNew: return "checkmark.shield.fill"
        }
    }

    private var stepTitle: String {
        switch step {
        case .verifyCurrent: return "Enter Current Passcode"
        case .enterNew: return "Enter New Passcode"
        case .confirmNew: return "Confirm New Passcode"
        }
    }

    private var codeField: some View {
        SecureField("Passcode", text: binding)
            .keyboardType(.numberPad)
            .textContentType(.oneTimeCode)
            .multilineTextAlignment(.center)
            .font(.title2.monospaced())
            .frame(width: 160)
            .textFieldStyle(.roundedBorder)
            .onChange(of: bindingValue) { _, newValue in
                if newValue.count >= 4 {
                    handleEntry(newValue)
                }
            }
    }

    private var binding: Binding<String> {
        switch step {
        case .verifyCurrent: return $currentCode
        case .enterNew: return $newCode
        case .confirmNew: return $confirmCode
        }
    }

    private var bindingValue: String {
        switch step {
        case .verifyCurrent: return currentCode
        case .enterNew: return newCode
        case .confirmNew: return confirmCode
        }
    }

    private func handleEntry(_ value: String) {
        errorMessage = nil
        switch step {
        case .verifyCurrent:
            if value == appSettings.adminPasscode {
                step = .enterNew
            } else {
                errorMessage = "Incorrect passcode"
                currentCode = ""
            }
        case .enterNew:
            step = .confirmNew
        case .confirmNew:
            if confirmCode == newCode {
                appSettings.adminPasscode = newCode
                dismiss()
            } else {
                errorMessage = "Passcodes don't match"
                confirmCode = ""
            }
        }
    }
}
