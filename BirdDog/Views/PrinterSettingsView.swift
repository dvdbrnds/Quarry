import SwiftUI

struct PrinterSettingsView: View {
    @ObservedObject private var printerService = PrinterService.shared
    @ObservedObject private var appSettings = AppSettings.shared
    @State private var isPrintingTest = false
    @State private var testPrintError: String?
    @State private var showTestResult = false
    @State private var manualName = ""
    @State private var isManualConnecting = false
    @State private var isConnectingFirstAvailable = false
    @State private var showDiagnostics = false

    var body: some View {
        List {
            connectionSection
            if printerService.isConnected {
                autoPrintSection
                testPrintSection
            }
            discoverySection
            diagnosticsSection
        }
        .navigationTitle("Printer")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if printerService.hasSavedPrinter && !printerService.isConnected {
                printerService.reconnectSaved()
            } else if !printerService.hasSavedPrinter && !printerService.isSearching {
                printerService.startDiscovery()
            }
        }
        .alert(testPrintError == nil ? "Test Print Sent" : "Print Failed", isPresented: $showTestResult) {
            Button("OK") {}
        } message: {
            if let err = testPrintError {
                Text(err)
            } else {
                Text("Check the printer for output.")
            }
        }
    }

    // MARK: - Connection Status

    private var connectionSection: some View {
        Section {
            HStack {
                Text("Status")
                Spacer()
                HStack(spacing: 6) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 8, height: 8)
                    Text(printerService.connectionState.rawValue)
                        .foregroundStyle(.secondary)
                }
            }

            if printerService.isConnected {
                HStack {
                    Text("Printer")
                    Spacer()
                    Text(printerService.printerName)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Button(role: .destructive) {
                    Task { await printerService.clearSavedPrinter() }
                } label: {
                    Label("Disconnect & Forget", systemImage: "xmark.circle")
                }
            }

            if let error = printerService.lastError, !printerService.isConnected {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            if printerService.hasSavedPrinter && !printerService.isConnected
                && printerService.connectionState != .connecting {
                Button {
                    printerService.reconnectSaved()
                } label: {
                    Label("Reconnect", systemImage: "arrow.triangle.2.circlepath")
                }
            }
        } header: {
            Text("Thermal Printer")
        } footer: {
            Text("Star SM-S210i / S220i / S230i, T300, L200/L300. Pair it first in iOS Settings → Bluetooth (PIN 1234).")
        }
    }

    private var statusColor: Color {
        switch printerService.connectionState {
        case .connected: return .green
        case .connecting: return .orange
        case .error: return .red
        case .disconnected: return .gray
        }
    }

    // MARK: - Auto Print

    private var autoPrintSection: some View {
        Section {
            Toggle(isOn: $printerService.autoPrintEnabled) {
                Label("Auto-Print Tickets", systemImage: "printer.fill")
            }
        } footer: {
            Text("Automatically print a receipt when a ticket is issued.")
        }
    }

    // MARK: - Test Print

    private var testPrintSection: some View {
        Section {
            Button {
                sendTestPrint()
            } label: {
                HStack {
                    Label("Test Print", systemImage: "printer.dotmatrix")
                    if isPrintingTest {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(isPrintingTest)
        }
    }

    // MARK: - Discovery & Connect

    private var discoverySection: some View {
        Section {
            // 1. System pairing picker (most reliable path)
            Button {
                Task { await printerService.presentSystemPairingPicker() }
            } label: {
                HStack {
                    Label("Pair Printer", systemImage: "antenna.radiowaves.left.and.right")
                    if printerService.isPairing {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(printerService.isPairing || printerService.connectionState == .connecting)

            // 2. SDK discovery scan
            Button {
                printerService.startDiscovery()
            } label: {
                HStack {
                    Label("Search for Printers", systemImage: "magnifyingglass")
                    if printerService.isSearching {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(printerService.isSearching || printerService.connectionState == .connecting)

            // 3. Blind first-found (no discovery needed)
            Button {
                connectFirstAvailable()
            } label: {
                HStack {
                    Label("Connect First Available", systemImage: "link.badge.plus")
                    if isConnectingFirstAvailable {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(isConnectingFirstAvailable || printerService.connectionState == .connecting)

            // Discovered printers
            ForEach(printerService.discoveredPrinters) { discovered in
                Button {
                    printerService.connect(to: discovered)
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(discovered.displayName)
                                .foregroundStyle(.primary)
                            Text(discovered.interfaceLabel)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if printerService.connectionState == .connecting {
                            ProgressView()
                        } else {
                            Image(systemName: "link")
                                .foregroundStyle(.blue)
                        }
                    }
                }
            }

            if printerService.discoveredPrinters.isEmpty
                && !printerService.isSearching
                && !printerService.isPairing
                && printerService.connectionState != .connecting {
                Text("No printers found yet. Make sure the printer is on, then try Pair Printer or Connect First Available.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            // Manual connect
            manualConnectRow
        } header: {
            Text("Connect")
        } footer: {
            Text("Step 1: Pair the printer in iOS Settings → Bluetooth (PIN 1234). Step 2: Tap Connect First Available or enter the Bluetooth name (shown in Settings, e.g. \"PRNT Star\").")
        }
    }

    private var manualConnectRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Manual Connect")
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            HStack {
                TextField("Bluetooth name (e.g. PRNT Star)", text: $manualName)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Button {
                    attemptManualConnect()
                } label: {
                    if isManualConnecting {
                        ProgressView()
                    } else {
                        Text("Connect")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(manualName.trimmingCharacters(in: .whitespaces).isEmpty || isManualConnecting)
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Diagnostics

    private var diagnosticsSection: some View {
        Section {
            let btAuth = printerService.bluetoothAuthStatus
            if btAuth != "allowed" {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.yellow)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Bluetooth permission: \(btAuth.uppercased())")
                            .font(.caption.bold())
                            .foregroundStyle(.red)
                        Text("Go to Settings → Privacy & Security → Bluetooth and enable Bird Dog.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            DisclosureGroup("Diagnostic Log", isExpanded: $showDiagnostics) {
                if printerService.diagnosticLog.isEmpty {
                    Text("No log entries yet. Tap Search or Connect to populate.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(Array(printerService.diagnosticLog.enumerated()), id: \.offset) { _, entry in
                        Text(entry)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    // MARK: - Actions

    private func connectFirstAvailable() {
        isConnectingFirstAvailable = true
        Task {
            do {
                try await printerService.connectFirstAvailable()
            } catch {
                // lastError already set
            }
            isConnectingFirstAvailable = false
        }
    }

    private func attemptManualConnect() {
        let name = manualName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        isManualConnecting = true
        Task {
            do {
                try await printerService.connectByName(name)
                manualName = ""
            } catch {
                // lastError already set
            }
            isManualConnecting = false
        }
    }

    private func sendTestPrint() {
        isPrintingTest = true
        testPrintError = nil

        Task {
            do {
                let commands = TicketReceiptBuilder.buildTestCommands(
                    schoolName: appSettings.schoolName
                )
                try await printerService.printCommands(commands)
                testPrintError = nil
            } catch {
                testPrintError = error.localizedDescription
            }
            isPrintingTest = false
            showTestResult = true
        }
    }
}
