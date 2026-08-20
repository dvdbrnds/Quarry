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

    var body: some View {
        List {
            connectionSection
            if printerService.isConnected {
                autoPrintSection
                testPrintSection
            }
            discoverySection
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

            if printerService.hasSavedPrinter && !printerService.isConnected {
                Button {
                    printerService.reconnectSaved()
                } label: {
                    Label("Reconnect", systemImage: "arrow.triangle.2.circlepath")
                }
            }
        } header: {
            Text("Thermal Printer")
        } footer: {
            Text("Works with SM-S210i, SM-S220i, SM-S230i, SM-T300/T300i, and SM-L200/L300. Pair Printer is the most reliable on older iPhones.")
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

    // MARK: - Discovery

    private var discoverySection: some View {
        Section {
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
            .disabled(printerService.isSearching || printerService.isPairing)

            Button {
                connectFirstAvailable()
            } label: {
                HStack {
                    Label("Connect First Available", systemImage: "link")
                    if isConnectingFirstAvailable {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(
                isConnectingFirstAvailable
                    || printerService.isPairing
                    || printerService.connectionState == .connecting
            )

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

            if printerService.discoveredPrinters.isEmpty && !printerService.isSearching && !printerService.isPairing {
                Text("No printers found. Power the printer on, tap Pair Printer, select it (PIN 1234), or use Connect First Available if it is already paired.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !printerService.isSearching {
                quickNameRows
                manualConnectRow
            }
        } header: {
            Text("Available Printers")
        } footer: {
            Text("If Search misses the printer (common on older iPhones), use Pair Printer or Connect First Available. Manual name is the Bluetooth name shown in Settings — usually “PRNT Star” or “Star Micronics”.")
        }
    }

    // MARK: - Common names

    private var quickNameRows: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Common names")
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            HStack(spacing: 8) {
                ForEach(Array(PrinterBluetoothNames.commonPortNames.prefix(3)), id: \.self) { name in
                    Button(name) {
                        manualName = name
                        attemptManualConnect(name)
                    }
                    .buttonStyle(.bordered)
                    .font(.caption)
                    .disabled(isManualConnecting || printerService.connectionState == .connecting)
                }
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Manual Connect

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
                    attemptManualConnect(manualName)
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

    private func connectFirstAvailable() {
        isConnectingFirstAvailable = true
        Task {
            do {
                try await printerService.connectFirstAvailable()
            } catch {
                // lastError is already set
            }
            isConnectingFirstAvailable = false
        }
    }

    private func attemptManualConnect(_ rawName: String) {
        let name = rawName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        isManualConnecting = true
        Task {
            do {
                try await printerService.connectByName(name)
                manualName = ""
            } catch {
                // lastError is already set by connectAndWait
            }
            isManualConnecting = false
        }
    }

    // MARK: - Actions

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
