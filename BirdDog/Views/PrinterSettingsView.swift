import SwiftUI

struct PrinterSettingsView: View {
    @ObservedObject private var printerService = PrinterService.shared
    @ObservedObject private var appSettings = AppSettings.shared
    @State private var isPrintingTest = false
    @State private var testPrintError: String?
    @State private var showTestResult = false

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
            if printerService.connectionState == .disconnected && printerService.hasSavedPrinter {
                printerService.reconnectSaved()
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

            if let error = printerService.lastError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            if printerService.connectionState == .disconnected && printerService.hasSavedPrinter {
                Button {
                    printerService.reconnectSaved()
                } label: {
                    Label("Reconnect", systemImage: "arrow.triangle.2.circlepath")
                }
            }
        } header: {
            Text("Thermal Printer")
        } footer: {
            Text("Connect a Star Micronics thermal printer via Bluetooth LE to print tickets in the field.")
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
                Text("No printers found. Make sure your printer is powered on and within range.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("Available Printers")
        } footer: {
            Text("Tap a printer to connect. The selection is saved for future sessions.")
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
