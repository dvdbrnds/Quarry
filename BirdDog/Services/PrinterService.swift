import Foundation
import ExternalAccessory
import StarIO10

@MainActor
final class PrinterService: ObservableObject {
    static let shared = PrinterService()

    /// SM-S230i and other Star portable i-series printers use classic Bluetooth (MFi).
    private static let starEAProtocol = "jp.star-m.starpro"

    @Published private(set) var connectionState: ConnectionState = .disconnected
    @Published private(set) var printerName: String = ""
    @Published private(set) var isPrinting = false
    @Published private(set) var lastError: String?

    @Published private(set) var discoveredPrinters: [DiscoveredPrinter] = []
    @Published private(set) var isSearching = false

    @Published var autoPrintEnabled: Bool {
        didSet { UserDefaults.standard.set(autoPrintEnabled, forKey: Self.autoPrintKey) }
    }

    enum ConnectionState: String {
        case disconnected = "Disconnected"
        case connecting = "Connecting…"
        case connected = "Connected"
        case error = "Error"
    }

    struct DiscoveredPrinter: Identifiable {
        let id: String
        let interfaceType: InterfaceType
        let model: String

        var displayName: String {
            if !model.isEmpty, model != id {
                return "\(model) (\(id))"
            }
            return id
        }

        var interfaceLabel: String {
            switch interfaceType {
            case .bluetooth: return "Bluetooth"
            case .bluetoothLE: return "Bluetooth LE"
            case .lan: return "LAN"
            case .usb: return "USB"
            case .unknown: return "Unknown"
            @unknown default: return "Unknown"
            }
        }
    }

    private static let savedIdentifierKey = "PrinterService.identifier"
    private static let savedInterfaceKey = "PrinterService.interfaceType"
    private static let savedNameKey = "PrinterService.displayName"
    private static let autoPrintKey = "PrinterService.autoPrint"

    /// Saved connection only — do not hold an open StarPrinter session between jobs.
    private var savedSettings: StarConnectionSettings?
    private var discoveryManager: StarDeviceDiscoveryManager?
    private var _discoveryDelegate: DiscoveryDelegate?

    private init() {
        self.autoPrintEnabled = UserDefaults.standard.bool(forKey: Self.autoPrintKey)
        if let settings = loadSavedSettings() {
            self.savedSettings = settings
            self.printerName = UserDefaults.standard.string(forKey: Self.savedNameKey) ?? settings.identifier
            self.connectionState = .disconnected
        }

        NotificationCenter.default.addObserver(
            forName: .EAAccessoryDidConnect, object: nil, queue: .main
        ) { [weak self] notification in
            guard let self, self.isSearching,
                  let accessory = notification.userInfo?[EAAccessoryKey] as? EAAccessory,
                  accessory.protocolStrings.contains(Self.starEAProtocol) else { return }
            Task { @MainActor in
                self.addDiscovered(
                    id: accessory.name,
                    interfaceType: .bluetooth,
                    model: accessory.modelNumber.isEmpty ? accessory.name : accessory.modelNumber
                )
            }
        }
        EAAccessoryManager.shared().registerForLocalNotifications()
    }

    // MARK: - Discovery

    func startDiscovery() {
        stopDiscovery()
        discoveredPrinters = []
        isSearching = true
        lastError = nil

        // SM-S230i is classic Bluetooth (paired in iOS Settings). Also scan BLE
        // for other Star portables that don't use MFi.
        seedPairedBluetoothPrinters()

        // If we already found paired MFi printers, mark search done quickly
        // but still kick off a short BLE scan for other printers.
        do {
            let manager = try StarDeviceDiscoveryManagerFactory.create(
                interfaceTypes: [.bluetooth, .bluetoothLE]
            )
            manager.discoveryTime = 5_000
            self.discoveryManager = manager

            let wrapper = DiscoveryDelegate { [weak self] found in
                Task { @MainActor in
                    guard let self else { return }
                    let identifier = found.connectionSettings.identifier
                    let modelName = Self.modelLabel(from: found.information?.model)
                    self.addDiscovered(
                        id: identifier,
                        interfaceType: found.connectionSettings.interfaceType,
                        model: modelName
                    )
                }
            } onFinished: { [weak self] in
                Task { @MainActor in
                    self?.isSearching = false
                }
            }
            manager.delegate = wrapper
            _discoveryDelegate = wrapper

            try manager.startDiscovery()
        } catch {
            isSearching = false
            lastError = "Discovery failed: \(error.localizedDescription)"
        }
    }

    /// Surfaces printers already paired/connected in iOS Settings (classic BT / MFi).
    private func seedPairedBluetoothPrinters() {
        let accessories = EAAccessoryManager.shared().connectedAccessories
        for accessory in accessories {
            guard accessory.protocolStrings.contains(Self.starEAProtocol) else { continue }
            addDiscovered(
                id: accessory.name,
                interfaceType: .bluetooth,
                model: accessory.modelNumber.isEmpty ? accessory.name : accessory.modelNumber
            )
        }
    }

    private func addDiscovered(id: String, interfaceType: InterfaceType, model: String) {
        let dp = DiscoveredPrinter(id: id, interfaceType: interfaceType, model: model)
        if !discoveredPrinters.contains(where: { $0.id == dp.id && $0.interfaceType == dp.interfaceType }) {
            discoveredPrinters.append(dp)
        }
    }

    private static func modelLabel(from model: StarPrinterModel?) -> String {
        guard let model else { return "" }
        let raw = String(describing: model)
        // Avoid dumping opaque enum junk like "17" into the UI.
        if raw.allSatisfy(\.isNumber) { return "" }
        return raw
            .replacingOccurrences(of: "StarPrinterModel.", with: "")
            .replacingOccurrences(of: "_", with: "-")
    }

    func stopDiscovery() {
        discoveryManager?.stopDiscovery()
        discoveryManager = nil
        isSearching = false
    }

    // MARK: - Connect / Disconnect

    func connect(to discovered: DiscoveredPrinter) {
        Task {
            do {
                try await connectAndWait(to: discovered)
            } catch {
                // lastError / connectionState already set by connectAndWait
            }
        }
    }

    /// Verifies the printer can be opened, then closes it. Settings are saved for
    /// per-job open/print/close — holding the port open causes "Already Opened."
    @discardableResult
    func connectAndWait(to discovered: DiscoveredPrinter) async throws -> Bool {
        stopDiscovery()
        connectionState = .connecting
        lastError = nil

        let settings = StarConnectionSettings(
            interfaceType: discovered.interfaceType,
            identifier: discovered.id
        )
        let printer = StarPrinter(settings)

        do {
            try await printer.open()
            await printer.close()

            savedSettings = settings
            printerName = discovered.displayName.isEmpty ? discovered.id : discovered.displayName
            connectionState = .connected

            UserDefaults.standard.set(discovered.id, forKey: Self.savedIdentifierKey)
            UserDefaults.standard.set(discovered.interfaceType.rawValue, forKey: Self.savedInterfaceKey)
            UserDefaults.standard.set(printerName, forKey: Self.savedNameKey)
            return true
        } catch {
            await printer.close()
            connectionState = .error
            lastError = friendlyMessage(for: error)
            throw error
        }
    }

    func disconnect() async {
        stopDiscovery()
        savedSettings = nil
        connectionState = .disconnected
        printerName = ""
        lastError = nil
    }

    func reconnectSaved() {
        Task {
            try? await reconnectSavedAndWait()
        }
    }

    @discardableResult
    func reconnectSavedAndWait() async throws -> Bool {
        guard let discovered = savedDiscoveredPrinter() else {
            throw PrintError.notConfigured
        }
        return try await connectAndWait(to: discovered)
    }

    /// Ensures saved settings exist. Does not hold an open session.
    func ensureConnected() async throws {
        if savedSettings != nil, connectionState == .connected { return }
        if hasSavedPrinter {
            try await reconnectSavedAndWait()
            return
        }
        throw PrintError.notConfigured
    }

    // MARK: - Print

    func printCommands(_ commands: String) async throws {
        stopDiscovery()

        if savedSettings == nil {
            try await ensureConnected()
        }

        guard let settings = savedSettings ?? loadSavedSettings() else {
            throw PrintError.notConfigured
        }
        savedSettings = settings

        isPrinting = true
        lastError = nil

        let printer = StarPrinter(settings)

        do {
            try await openWithRetry(printer)
            try await printer.print(command: commands)
            await printer.close()
            connectionState = .connected
            isPrinting = false
        } catch {
            await printer.close()
            isPrinting = false
            lastError = friendlyMessage(for: error)
            connectionState = .error
            throw error
        }
    }

    /// Open once; on in-use / already-open, close and retry a single time.
    private func openWithRetry(_ printer: StarPrinter) async throws {
        do {
            try await printer.open()
        } catch {
            if isBusyOrAlreadyOpen(error) {
                await printer.close()
                try await Task.sleep(nanoseconds: 400_000_000)
                try await printer.open()
            } else {
                throw error
            }
        }
    }

    private func isBusyOrAlreadyOpen(_ error: Error) -> Bool {
        if case StarIO10Error.inUse = error { return true }
        if case StarIO10Error.invalidOperation = error { return true }
        let message = error.localizedDescription.lowercased()
        return message.contains("already open")
            || message.contains("in use")
            || message.contains("another process")
    }

    private func friendlyMessage(for error: Error) -> String {
        if isBusyOrAlreadyOpen(error) {
            return "Printer is busy. Close other Star apps, wait a second, and try again."
        }
        return error.localizedDescription
    }

    var isConnected: Bool {
        connectionState == .connected
    }

    var hasSavedPrinter: Bool {
        UserDefaults.standard.string(forKey: Self.savedIdentifierKey) != nil
    }

    func clearSavedPrinter() async {
        await disconnect()
        UserDefaults.standard.removeObject(forKey: Self.savedIdentifierKey)
        UserDefaults.standard.removeObject(forKey: Self.savedInterfaceKey)
        UserDefaults.standard.removeObject(forKey: Self.savedNameKey)
    }

    private func loadSavedSettings() -> StarConnectionSettings? {
        guard let identifier = UserDefaults.standard.string(forKey: Self.savedIdentifierKey),
              let rawInterface = UserDefaults.standard.object(forKey: Self.savedInterfaceKey) as? Int,
              let interfaceType = InterfaceType(rawValue: rawInterface) else {
            return nil
        }
        return StarConnectionSettings(interfaceType: interfaceType, identifier: identifier)
    }

    private func savedDiscoveredPrinter() -> DiscoveredPrinter? {
        guard let settings = loadSavedSettings() else { return nil }
        let name = UserDefaults.standard.string(forKey: Self.savedNameKey) ?? settings.identifier
        return DiscoveredPrinter(
            id: settings.identifier,
            interfaceType: settings.interfaceType,
            model: name
        )
    }

    // MARK: - Errors

    enum PrintError: LocalizedError {
        case notConnected
        case notConfigured

        var errorDescription: String? {
            switch self {
            case .notConnected: return "No printer connected"
            case .notConfigured: return "No printer paired. Open Settings → Printer to connect a Star Micronics printer."
            }
        }
    }
}

// MARK: - Discovery Delegate

private class DiscoveryDelegate: NSObject, StarDeviceDiscoveryManagerDelegate {
    let onFound: (StarPrinter) -> Void
    let onFinished: () -> Void

    init(onFound: @escaping (StarPrinter) -> Void, onFinished: @escaping () -> Void) {
        self.onFound = onFound
        self.onFinished = onFinished
    }

    func manager(_ manager: StarDeviceDiscoveryManager, didFind printer: StarPrinter) {
        onFound(printer)
    }

    func managerDidFinishDiscovery(_ manager: StarDeviceDiscoveryManager) {
        onFinished()
    }
}
