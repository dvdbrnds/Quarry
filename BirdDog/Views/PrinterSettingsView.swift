import SwiftUI

struct PrinterSettingsView: View {
    @ObservedObject private var printerService = PrinterService.shared
    @ObservedObject private var appSettings = AppSettings.shared
    @State private var isPrintingTest = false
    @State private var testPrintError: String?
    @State private var showTestResult = false
    @State private var manualName = ""
    @State private var isManualConnecting = false

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
            Text("Pair the SM-S230i in iOS Settings → Bluetooth first, then search here. Classic Bluetooth (MFi) printers appear after pairing.")
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
            .disabled(printerService.isSearching)

            ForEach(printerService.discoveredPrinters) { discovered in
                Button {
                    printerService.connect(to: discovered)
                    printerService.stopDiscovery()
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

            if printerService.discoveredPrinters.isEmpty && !printerService.isSearching {
                Text("No printers found. For SM-S230i: power on the printer, pair it in iPhone Settings → Bluetooth (PIN 1234), confirm it shows Connected, then search again.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !printerService.isSearching {
                manualConnectRow
            }
        } header: {
            Text("Available Printers")
        } footer: {
            Text("If the printer doesn't appear, use Manual Connect and enter its Bluetooth name (usually \"PRNT Star\" or the name shown in Settings → Bluetooth).")
        }
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

    private func attemptManualConnect() {
        let name = manualName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        isManualConnecting = true
        let discovered = PrinterService.DiscoveredPrinter(
            id: name,
            interfaceType: .bluetooth,
            model: name
        )
        Task {
            do {
                try await printerService.connectAndWait(to: discovered)
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
