import Foundation
import ExternalAccessory
import StarIO10

@MainActor
final class PrinterService: ObservableObject {
    static let shared = PrinterService()

    private static let starEAProtocol = "jp.star-m.starpro"

    @Published private(set) var connectionState: ConnectionState = .disconnected
    @Published private(set) var printerName: String = ""
    @Published private(set) var isPrinting = false
    @Published private(set) var lastError: String?
    @Published private(set) var isPairing = false
    @Published private(set) var discoveredPrinters: [DiscoveredPrinter] = []
    @Published private(set) var isSearching = false
    @Published private(set) var diagnosticLog: [String] = []

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
        let identifier: String
        let interfaceType: InterfaceType
        let model: String

        var id: String { "\(interfaceType.rawValue)::\(identifier)" }

        var displayName: String {
            if !model.isEmpty, model != identifier {
                return "\(model) (\(identifier))"
            }
            return identifier.isEmpty ? "First Available" : identifier
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

        let starProtocol = Self.starEAProtocol
        NotificationCenter.default.addObserver(
            forName: .EAAccessoryDidConnect, object: nil, queue: .main
        ) { [weak self] notification in
            guard let accessory = notification.userInfo?[EAAccessoryKey] as? EAAccessory,
                  accessory.protocolStrings.contains(starProtocol) else { return }
            Task { @MainActor in
                self?.addAccessory(accessory)
            }
        }
        EAAccessoryManager.shared().registerForLocalNotifications()
    }

    private func log(_ message: String) {
        diagnosticLog.append(message)
        if diagnosticLog.count > 30 { diagnosticLog.removeFirst() }
    }

    // MARK: - Discovery

    func startDiscovery() {
        stopDiscovery()
        discoveredPrinters = []
        isSearching = true
        lastError = nil
        diagnosticLog = []

        seedPairedBluetoothPrinters()
        log("EA accessories: \(EAAccessoryManager.shared().connectedAccessories.map { $0.name })")
        log("Seeded \(discoveredPrinters.count) from EA")

        do {
            let manager = try StarDeviceDiscoveryManagerFactory.create(
                interfaceTypes: [.bluetooth, .bluetoothLE]
            )
            manager.discoveryTime = 8_000
            self.discoveryManager = manager

            let wrapper = DiscoveryDelegate { [weak self] found in
                Task { @MainActor in
                    guard let self else { return }
                    let id = found.connectionSettings.identifier
                    let iface = found.connectionSettings.interfaceType
                    let modelName = Self.modelLabel(from: found.information?.model)
                    self.log("SDK found: \(id) (\(iface))")
                    self.addDiscovered(identifier: id, interfaceType: iface, model: modelName)
                }
            } onFinished: { [weak self] in
                Task { @MainActor in
                    guard let self else { return }
                    self.log("Discovery finished. Found \(self.discoveredPrinters.count)")
                    self.isSearching = false
                }
            }
            manager.delegate = wrapper
            _discoveryDelegate = wrapper
            try manager.startDiscovery()
            log("StarIO10 discovery started (BT + BLE, 8s)")
        } catch {
            isSearching = false
            let msg = detailedErrorMessage(error)
            lastError = "Discovery failed: \(msg)"
            log("Discovery error: \(msg)")
        }
    }

    func presentSystemPairingPicker() async {
        isPairing = true
        lastError = nil
        log("Opening system Bluetooth picker…")

        await Task.yield()
        try? await Task.sleep(nanoseconds: 200_000_000)

        do {
            try await EAAccessoryManager.shared().showBluetoothAccessoryPicker(withNameFilter: nil)
            log("Picker dismissed (success)")
        } catch {
            let ns = error as NSError
            if ns.domain == EABluetoothAccessoryPickerError.errorDomain {
                if ns.code == EABluetoothAccessoryPickerError.Code.resultCancelled.rawValue {
                    log("Picker cancelled by user")
                    isPairing = false
                    return
                }
                if ns.code == EABluetoothAccessoryPickerError.Code.alreadyConnected.rawValue {
                    log("Picker: printer already connected")
                }
            } else {
                log("Picker error: \(error.localizedDescription)")
                lastError = "Bluetooth picker failed: \(error.localizedDescription). Try Settings → Bluetooth instead."
                isPairing = false
                return
            }
        }

        try? await Task.sleep(nanoseconds: 800_000_000)
        seedPairedBluetoothPrinters()
        log("Post-picker EA accessories: \(discoveredPrinters.map { $0.identifier })")

        if let first = discoveredPrinters.first {
            log("Auto-connecting to \(first.identifier)")
            isPairing = false
            do {
                try await connectAndWait(to: first)
            } catch {
                log("Auto-connect failed: \(detailedErrorMessage(error))")
            }
            return
        }

        log("No EA printers after picker — trying first-found")
        isPairing = false
        do {
            try await connectFirstAvailable()
        } catch {
            log("First-found also failed: \(detailedErrorMessage(error))")
        }
    }

    func connectFirstAvailable() async throws {
        log("Attempting first-found (no identifier)")
        try await connectWithIdentifier(
            identifier: StarConnectionSettings.FIRST_FOUND_DEVICE,
            interfaceType: .bluetooth,
            label: "First Available"
        )
    }

    func connectByName(_ name: String) async throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw PrintError.notConfigured }
        log("Manual connect: \"\(trimmed)\"")
        try await connectWithIdentifier(
            identifier: trimmed,
            interfaceType: .bluetooth,
            label: trimmed
        )
    }

    private func seedPairedBluetoothPrinters() {
        for accessory in EAAccessoryManager.shared().connectedAccessories {
            addAccessory(accessory)
        }
    }

    private func addAccessory(_ accessory: EAAccessory) {
        guard accessory.protocolStrings.contains(Self.starEAProtocol) else { return }
        let portName = accessory.name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !portName.isEmpty else { return }
        let model = accessory.modelNumber.isEmpty ? portName : accessory.modelNumber
        addDiscovered(identifier: portName, interfaceType: .bluetooth, model: model)
    }

    private func addDiscovered(identifier: String, interfaceType: InterfaceType, model: String) {
        let dp = DiscoveredPrinter(identifier: identifier, interfaceType: interfaceType, model: model)
        if !discoveredPrinters.contains(where: {
            $0.identifier.caseInsensitiveCompare(dp.identifier) == .orderedSame
                && $0.interfaceType == dp.interfaceType
        }) {
            discoveredPrinters.append(dp)
        }
    }

    private static func modelLabel(from model: StarPrinterModel?) -> String {
        guard let model else { return "" }
        let raw = String(describing: model)
        if raw.allSatisfy(\.isNumber) { return "" }
        return raw
            .replacingOccurrences(of: "StarPrinterModel.", with: "")
            .replacingOccurrences(of: "_", with: "-")
    }

    func stopDiscovery() {
        discoveryManager?.stopDiscovery()
        discoveryManager = nil
        _discoveryDelegate = nil
        isSearching = false
    }

    // MARK: - Connect

    func connect(to discovered: DiscoveredPrinter) {
        Task {
            try? await connectAndWait(to: discovered)
        }
    }

    @discardableResult
    func connectAndWait(to discovered: DiscoveredPrinter) async throws -> Bool {
        return try await connectWithIdentifier(
            identifier: discovered.identifier,
            interfaceType: discovered.interfaceType,
            label: discovered.displayName
        )
    }

    /// Core connection logic. Tries the given identifier, then falls back to
    /// FIRST_FOUND_DEVICE on the same interface, then on the other BT radio.
    @discardableResult
    private func connectWithIdentifier(
        identifier: String,
        interfaceType: InterfaceType,
        label: String
    ) async throws -> Bool {
        stopDiscovery()
        connectionState = .connecting
        lastError = nil

        // Build a short list of (interface, identifier) to try.
        var attempts: [(InterfaceType, String)] = []

        let isFirstFound = identifier == StarConnectionSettings.FIRST_FOUND_DEVICE
            || identifier.isEmpty

        if !isFirstFound {
            attempts.append((interfaceType, identifier))
        }
        // Always try first-found as fallback on both radios.
        attempts.append((.bluetooth, StarConnectionSettings.FIRST_FOUND_DEVICE))
        attempts.append((.bluetoothLE, StarConnectionSettings.FIRST_FOUND_DEVICE))

        var lastFailure: Error?
        for attempt in attempts {
            let ifaceLabel = attempt.0 == .bluetooth ? "BT" : "BLE"
            let idLabel = attempt.1 == StarConnectionSettings.FIRST_FOUND_DEVICE
                ? "FIRST_FOUND" : "\"\(attempt.1)\""
            log("Try open: \(ifaceLabel) / \(idLabel)")

            let settings = StarConnectionSettings(
                interfaceType: attempt.0,
                identifier: attempt.1
            )
            let printer = StarPrinter(settings)

            do {
                try await printer.open()
                let actualId = printer.connectionSettings.identifier
                log("Opened OK (actual id: \(actualId))")
                await printer.close()

                let saveId = actualId.isEmpty ? attempt.1 : actualId
                savedSettings = StarConnectionSettings(
                    interfaceType: attempt.0,
                    identifier: saveId
                )
                printerName = label.isEmpty ? (saveId.isEmpty ? "Star Printer" : saveId) : label
                connectionState = .connected

                UserDefaults.standard.set(saveId, forKey: Self.savedIdentifierKey)
                UserDefaults.standard.set(attempt.0.rawValue, forKey: Self.savedInterfaceKey)
                UserDefaults.standard.set(printerName, forKey: Self.savedNameKey)
                return true
            } catch {
                await printer.close()
                lastFailure = error
                let msg = detailedErrorMessage(error)
                log("Failed: \(msg)")

                if isFatalBluetoothUnavailable(error) {
                    log("Bluetooth unavailable — stopping")
                    break
                }

                if isBusyOrAlreadyOpen(error) {
                    log("Port busy — waiting 600ms before next attempt")
                    try? await Task.sleep(nanoseconds: 600_000_000)
                }
            }
        }

        connectionState = .error
        lastError = friendlyMessage(for: lastFailure)
        throw lastFailure ?? PrintError.notConnected
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
            do {
                try await reconnectSavedAndWait()
            } catch {
                log("Reconnect failed: \(detailedErrorMessage(error))")
                log("Clearing stale saved printer")
                await clearSavedPrinter()
            }
        }
    }

    @discardableResult
    func reconnectSavedAndWait() async throws -> Bool {
        guard let settings = loadSavedSettings() else {
            throw PrintError.notConfigured
        }
        let name = UserDefaults.standard.string(forKey: Self.savedNameKey) ?? settings.identifier
        log("Reconnecting saved: \"\(settings.identifier)\" (\(settings.interfaceType))")
        return try await connectWithIdentifier(
            identifier: settings.identifier,
            interfaceType: settings.interfaceType,
            label: name
        )
    }

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
            try await openForPrint(printer)
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

    /// Open with one retry for busy/already-open errors.
    private func openForPrint(_ printer: StarPrinter) async throws {
        do {
            try await printer.open()
        } catch {
            if isBusyOrAlreadyOpen(error) {
                await printer.close()
                try await Task.sleep(nanoseconds: 500_000_000)
                try await printer.open()
            } else {
                throw error
            }
        }
    }

    // MARK: - Error classification

    private func isBusyOrAlreadyOpen(_ error: Error) -> Bool {
        if case StarIO10Error.inUse = error { return true }
        if case StarIO10Error.invalidOperation = error { return true }
        let msg = error.localizedDescription.lowercased()
        return msg.contains("already open") || msg.contains("in use")
    }

    private func isFatalBluetoothUnavailable(_ error: Error) -> Bool {
        if case StarIO10Error.illegalDeviceState(_, let code) = error {
            return code == .bluetoothUnavailable
        }
        return false
    }

    private func detailedErrorMessage(_ error: Error) -> String {
        switch error {
        case StarIO10Error.notFound(let message, let code):
            return "notFound[\(code)]: \(message)"
        case StarIO10Error.communication(let message, let code):
            return "communication[\(code)]: \(message)"
        case StarIO10Error.inUse(let message, let code):
            return "inUse[\(code)]: \(message)"
        case StarIO10Error.invalidOperation(let message, let code):
            return "invalidOperation[\(code)]: \(message)"
        case StarIO10Error.illegalDeviceState(let message, let code):
            return "illegalDeviceState[\(code)]: \(message)"
        case StarIO10Error.argument(let message, let code):
            return "argument[\(code)]: \(message)"
        case StarIO10Error.badResponse(let message, let code):
            return "badResponse[\(code)]: \(message)"
        case StarIO10Error.unsupportedModel(let message, let code):
            return "unsupportedModel[\(code)]: \(message)"
        default:
            return error.localizedDescription
        }
    }

    private func friendlyMessage(for error: Error?) -> String {
        guard let error else {
            return "Could not reach the printer. Power it on and try again."
        }
        if isFatalBluetoothUnavailable(error) {
            return "Bluetooth is turned off on this device."
        }
        if isBusyOrAlreadyOpen(error) {
            return "Printer port is busy. Wait a few seconds and try again."
        }
        if case StarIO10Error.notFound = error {
            return "Printer not found. Make sure it is powered on and paired in iOS Bluetooth Settings (PIN 1234)."
        }
        if case StarIO10Error.communication = error {
            return "Lost communication with the printer. Power-cycle it and try again."
        }
        return error.localizedDescription
    }

    // MARK: - Persistence

    var isConnected: Bool { connectionState == .connected }

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

    // MARK: - Errors

    enum PrintError: LocalizedError {
        case notConnected
        case notConfigured

        var errorDescription: String? {
            switch self {
            case .notConnected: return "No printer connected"
            case .notConfigured: return "No printer paired. Open Settings → Printer to connect."
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
