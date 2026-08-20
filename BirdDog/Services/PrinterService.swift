import Foundation
import ExternalAccessory
import StarIO10

/// Well-known iOS Bluetooth port names for Star portable printers.
/// Classic MFi models (SM-S210i / S220i / S230i / T300 / T400) advertise a name,
/// not a serial number. StarIO10 on iOS connects by that port name.
enum PrinterBluetoothNames {
    static let commonPortNames = [
        "PRNT Star",
        "Star Micronics",
        "SM-S230i",
        "SM-S210i",
        "SM-S220i",
        "SM-T300i",
        "SM-T300",
        "SM-T400i",
        "SM-L200",
        "SM-L300"
    ]
}

@MainActor
final class PrinterService: ObservableObject {
    static let shared = PrinterService()

    /// SM-S230i and other Star portable i-series printers use classic Bluetooth (MFi).
    private static let starEAProtocol = "jp.star-m.starpro"

    @Published private(set) var connectionState: ConnectionState = .disconnected
    @Published private(set) var printerName: String = ""
    @Published private(set) var isPrinting = false
    @Published private(set) var lastError: String?
    @Published private(set) var isPairing = false

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

    struct DiscoveredPrinter: Identifiable, Hashable {
        /// StarIO10 identifier: iOS port name for classic Bluetooth, MAC for BLE.
        let identifier: String
        let interfaceType: InterfaceType
        let model: String
        var alternateIdentifiers: [String] = []

        var id: String { "\(interfaceType.rawValue)::\(identifier)" }

        var displayName: String {
            if !model.isEmpty, model != identifier {
                return "\(model) (\(identifier.isEmpty ? "first available" : identifier))"
            }
            if identifier.isEmpty { return model.isEmpty ? "First available printer" : model }
            return identifier
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
    private var discoveryTask: Task<Void, Never>?

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

    // MARK: - Discovery

    func startDiscovery() {
        stopDiscovery()
        discoveredPrinters = []
        isSearching = true
        lastError = nil

        // Classic Bluetooth (MFi) printers only appear in connectedAccessories
        // after they are actually connected — pairing in Settings is not enough
        // on some iPhones. Seed whatever is already up, then scan both radios.
        seedPairedBluetoothPrinters()

        discoveryTask = Task { [weak self] in
            await self?.runDiscoverySequence()
        }
    }

    /// In-app MFi pairing sheet. More reliable than sending officers to
    /// Settings → Bluetooth, especially on older iPhones where EA discovery is empty.
    func presentSystemPairingPicker() async {
        isPairing = true
        lastError = nil

        // SwiftUI can swallow the system picker if it is presented in the same
        // run loop as the button tap. Yield so the alert can appear.
        await Task.yield()
        try? await Task.sleep(nanoseconds: 200_000_000)

        var pickerFailed = false
        do {
            try await EAAccessoryManager.shared().showBluetoothAccessoryPicker(withNameFilter: nil)
        } catch {
            if isPickerCancelled(error) {
                isPairing = false
                return
            }
            if !isPickerAlreadyConnected(error) {
                pickerFailed = true
                lastError = "Could not open the Bluetooth pairing sheet. Pair the printer in iOS Settings → Bluetooth (PIN 1234), then search here."
            }
        }

        // Accessory list updates a beat after the picker dismisses.
        try? await Task.sleep(nanoseconds: 500_000_000)
        seedPairedBluetoothPrinters()

        if let first = discoveredPrinters.first {
            isPairing = false
            do {
                try await connectAndWait(to: first)
            } catch {
                // lastError already set
            }
            return
        }

        if !pickerFailed {
            // Picker succeeded (or printer was already connected) but EA still
            // did not list it — fall back to first classic-Bluetooth device.
            isPairing = false
            do {
                try await connectFirstAvailable()
            } catch {
                // lastError already set
            }
            return
        }

        isPairing = false
    }

    /// Opens the first Star printer the SDK can see. Used when discovery lists
    /// nothing (common on older iPhones) but the printer is already paired.
    func connectFirstAvailable() async throws {
        let discovered = DiscoveredPrinter(
            identifier: "",
            interfaceType: .bluetooth,
            model: "Star Printer",
            alternateIdentifiers: Array(PrinterBluetoothNames.commonPortNames.prefix(3))
        )
        try await connectAndWait(to: discovered)
    }

    func connectByName(_ name: String) async throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw PrintError.notConfigured }

        let looksLikeMAC = Self.isBluetoothAddress(trimmed)
        let discovered = DiscoveredPrinter(
            identifier: trimmed,
            interfaceType: looksLikeMAC ? .bluetoothLE : .bluetooth,
            model: trimmed
        )
        try await connectAndWait(to: discovered)
    }

    private func runDiscoverySequence() async {
        // Sequential scans: combined bluetooth+BLE discovery misses classic
        // MFi printers on some older radios. EA-seeded printers stay visible
        // the whole time so officers can connect without waiting.
        await discover(interfaceTypes: [.bluetooth], timeoutMs: 10_000)
        guard !Task.isCancelled, isSearching else { return }
        await discover(interfaceTypes: [.bluetoothLE], timeoutMs: 8_000)
        if isSearching {
            isSearching = false
        }
        if discoveredPrinters.isEmpty, lastError == nil {
            lastError = "No printers found. Power the printer on, pair it with Pair Printer (or Settings → Bluetooth, PIN 1234), then try Connect First Available."
        }
    }

    private func discover(interfaceTypes: [InterfaceType], timeoutMs: Int) async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            var resumed = false
            func finish() {
                guard !resumed else { return }
                resumed = true
                continuation.resume()
            }

            if Task.isCancelled {
                finish()
                return
            }

            do {
                let manager = try StarDeviceDiscoveryManagerFactory.create(interfaceTypes: interfaceTypes)
                manager.discoveryTime = timeoutMs

                let wrapper = DiscoveryDelegate { [weak self] found in
                    Task { @MainActor in
                        self?.addFromStarPrinter(found)
                    }
                } onFinished: {
                    finish()
                }
                manager.delegate = wrapper
                self.discoveryManager = manager
                self._discoveryDelegate = wrapper
                try manager.startDiscovery()
            } catch {
                if discoveredPrinters.isEmpty {
                    lastError = friendlyMessage(for: error)
                }
                finish()
            }
        }
    }

    /// Surfaces printers already paired/connected in iOS Settings (classic BT / MFi).
    private func seedPairedBluetoothPrinters() {
        for accessory in EAAccessoryManager.shared().connectedAccessories {
            addAccessory(accessory)
        }
    }

    private func addAccessory(_ accessory: EAAccessory) {
        guard accessory.protocolStrings.contains(Self.starEAProtocol) else { return }

        // StarIO10 on iOS Bluetooth uses the iOS port name (Settings name),
        // not the accessory serial. Prefer name; keep serial as a fallback.
        let portName = accessory.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let serial = accessory.serialNumber.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = accessory.modelNumber.isEmpty ? (portName.isEmpty ? serial : portName) : accessory.modelNumber
        let primary = portName.isEmpty ? serial : portName
        guard !primary.isEmpty else { return }

        var alternates: [String] = []
        if !serial.isEmpty, serial.caseInsensitiveCompare(primary) != .orderedSame {
            alternates.append(serial)
        }

        addDiscovered(
            identifier: primary,
            interfaceType: .bluetooth,
            model: model,
            alternateIdentifiers: alternates
        )
    }

    private func addFromStarPrinter(_ found: StarPrinter) {
        let identifier = found.connectionSettings.identifier
        let modelName = Self.modelLabel(from: found.information?.model)
        addDiscovered(
            identifier: identifier,
            interfaceType: found.connectionSettings.interfaceType,
            model: modelName
        )
    }

    private func addDiscovered(
        identifier: String,
        interfaceType: InterfaceType,
        model: String,
        alternateIdentifiers: [String] = []
    ) {
        let dp = DiscoveredPrinter(
            identifier: identifier,
            interfaceType: interfaceType,
            model: model,
            alternateIdentifiers: alternateIdentifiers
        )
        if let index = discoveredPrinters.firstIndex(where: {
            $0.identifier.caseInsensitiveCompare(dp.identifier) == .orderedSame
                && $0.interfaceType == dp.interfaceType
        }) {
            var existing = discoveredPrinters[index]
            let merged = Array(Set(existing.alternateIdentifiers + dp.alternateIdentifiers))
            existing.alternateIdentifiers = merged
            discoveredPrinters[index] = existing
        } else {
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
        discoveryTask?.cancel()
        discoveryTask = nil
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
    /// Tries port name, serial, the other radio (classic vs BLE), then first-found.
    @discardableResult
    func connectAndWait(to discovered: DiscoveredPrinter) async throws -> Bool {
        stopDiscovery()
        connectionState = .connecting
        lastError = nil

        let attempts = connectionAttempts(for: discovered)
        var lastFailure: Error?

        for (index, attempt) in attempts.enumerated() {
            let settings = makeSettings(
                interfaceType: attempt.interface,
                identifier: attempt.identifier,
                autoSwitch: false
            )
            let printer = StarPrinter(settings)

            do {
                try await openWithRetry(printer, extraAttempts: index == 0 ? 2 : 0)
                await printer.close()

                savedSettings = makeSettings(
                    interfaceType: attempt.interface,
                    identifier: attempt.identifier,
                    autoSwitch: true
                )
                let label = discovered.displayName
                printerName = label.isEmpty ? (attempt.identifier.isEmpty ? "Star Printer" : attempt.identifier) : label
                connectionState = .connected

                UserDefaults.standard.set(attempt.identifier, forKey: Self.savedIdentifierKey)
                UserDefaults.standard.set(attempt.interface.rawValue, forKey: Self.savedInterfaceKey)
                UserDefaults.standard.set(printerName, forKey: Self.savedNameKey)
                return true
            } catch {
                await printer.close()
                lastFailure = error
                if isFatalBluetoothUnavailable(error) {
                    break
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

        do {
            try await printOnce(commands, settings: settings, autoSwitch: true)
            connectionState = .connected
            isPrinting = false
        } catch {
            if isNotFoundOrCommunication(error), let recovered = try? await recoverConnection() {
                do {
                    try await printOnce(commands, settings: recovered, autoSwitch: true)
                    connectionState = .connected
                    isPrinting = false
                    return
                } catch {
                    await failPrint(error)
                    throw error
                }
            }
            await failPrint(error)
            throw error
        }
    }

    private func printOnce(_ commands: String, settings: StarConnectionSettings, autoSwitch: Bool) async throws {
        let jobSettings = makeSettings(
            interfaceType: settings.interfaceType,
            identifier: settings.identifier,
            autoSwitch: autoSwitch
        )
        let printer = StarPrinter(jobSettings)
        do {
            try await openWithRetry(printer, extraAttempts: 2)
            try await printer.print(command: commands)
            await printer.close()
        } catch {
            await printer.close()
            throw error
        }
    }

    private func failPrint(_ error: Error) async {
        isPrinting = false
        lastError = friendlyMessage(for: error)
        connectionState = .error
    }

    /// Re-seed EA accessories and try first-found if the saved identifier went stale.
    private func recoverConnection() async throws -> StarConnectionSettings {
        seedPairedBluetoothPrinters()
        if let live = discoveredPrinters.first {
            _ = try await connectAndWait(to: live)
            if let settings = savedSettings { return settings }
        }
        try await connectFirstAvailable()
        guard let settings = savedSettings else { throw PrintError.notConfigured }
        return settings
    }

    /// Open with retries. Classic Bluetooth on older iPhones often fails the first open.
    private func openWithRetry(_ printer: StarPrinter, extraAttempts: Int) async throws {
        var attempt = 0
        let maxAttempts = 1 + extraAttempts
        var lastError: Error?
        while attempt < maxAttempts {
            do {
                try await printer.open()
                return
            } catch {
                lastError = error
                await printer.close()
                if isFatalBluetoothUnavailable(error) { throw error }
                attempt += 1
                if attempt < maxAttempts {
                    let delay = UInt64(400_000_000 + (attempt * 250_000_000))
                    try await Task.sleep(nanoseconds: delay)
                }
            }
        }
        throw lastError ?? PrintError.notConnected
    }

    private func makeSettings(
        interfaceType: InterfaceType,
        identifier: String,
        autoSwitch: Bool
    ) -> StarConnectionSettings {
        let settings = StarConnectionSettings(
            interfaceType: interfaceType,
            identifier: identifier,
            autoSwitchInterface: autoSwitch
        )
        return settings
    }

    /// Ordered (interface, identifier) probes. Empty identifier = first device found.
    /// Classic Bluetooth uses an iOS port name; BLE uses a MAC address — do not
    /// cross those, or each failed open() burns several seconds.
    private func connectionAttempts(for discovered: DiscoveredPrinter) -> [(interface: InterfaceType, identifier: String)] {
        var attempts: [(InterfaceType, String)] = []
        var seen = Set<String>()

        func add(_ interface: InterfaceType, _ identifier: String) {
            let key = "\(interface.rawValue)|\(identifier.lowercased())"
            if seen.insert(key).inserted {
                attempts.append((interface, identifier))
            }
        }

        if discovered.identifier.isEmpty {
            for name in discovered.alternateIdentifiers {
                add(.bluetooth, name)
            }
            add(.bluetooth, StarConnectionSettings.FIRST_FOUND_DEVICE)
            add(.bluetoothLE, StarConnectionSettings.FIRST_FOUND_DEVICE)
            return attempts
        }

        add(discovered.interfaceType, discovered.identifier)
        for alternate in discovered.alternateIdentifiers where !alternate.isEmpty {
            add(discovered.interfaceType, alternate)
        }

        if Self.isBluetoothAddress(discovered.identifier) {
            add(.bluetoothLE, discovered.identifier)
        } else {
            add(.bluetooth, discovered.identifier)
            for alternate in discovered.alternateIdentifiers
            where !alternate.isEmpty && !Self.isBluetoothAddress(alternate) {
                add(.bluetooth, alternate)
            }
        }

        add(.bluetooth, StarConnectionSettings.FIRST_FOUND_DEVICE)
        add(.bluetoothLE, StarConnectionSettings.FIRST_FOUND_DEVICE)
        return attempts
    }

    private func isBusyOrAlreadyOpen(_ error: Error) -> Bool {
        if case StarIO10Error.inUse = error { return true }
        if case StarIO10Error.invalidOperation = error { return true }
        let message = error.localizedDescription.lowercased()
        return message.contains("already open")
            || message.contains("in use")
            || message.contains("another process")
    }

    private func isNotFoundOrCommunication(_ error: Error) -> Bool {
        if case StarIO10Error.notFound = error { return true }
        if case StarIO10Error.communication = error { return true }
        let message = error.localizedDescription.lowercased()
        return message.contains("not found")
            || message.contains("communication")
            || message.contains("timeout")
    }

    private func isFatalBluetoothUnavailable(_ error: Error) -> Bool {
        if case StarIO10Error.illegalDeviceState(_, let code) = error {
            return code == .bluetoothUnavailable
        }
        let message = error.localizedDescription.lowercased()
        return message.contains("bluetoothunavailable")
            || message.contains("bluetooth unavailable")
            || message.contains("bluetooth is off")
    }

    private func friendlyMessage(for error: Error?) -> String {
        guard let error else {
            return "Could not reach the printer. Power it on, pair it, and try again."
        }
        if isFatalBluetoothUnavailable(error) {
            return "Bluetooth is off. Turn it on in iOS Settings and try again."
        }
        if isBusyOrAlreadyOpen(error) {
            return "Printer is busy. Close other Star apps, wait a second, and try again."
        }
        if isNotFoundOrCommunication(error) {
            return "Printer not found. Power it on, pair it with Pair Printer (PIN 1234), then try Connect First Available."
        }
        return error.localizedDescription
    }

    private func isPickerAlreadyConnected(_ error: Error) -> Bool {
        let ns = error as NSError
        return ns.domain == EABluetoothAccessoryPickerError.errorDomain
            && ns.code == EABluetoothAccessoryPickerError.Code.alreadyConnected.rawValue
    }

    private func isPickerCancelled(_ error: Error) -> Bool {
        let ns = error as NSError
        return ns.domain == EABluetoothAccessoryPickerError.errorDomain
            && ns.code == EABluetoothAccessoryPickerError.Code.resultCancelled.rawValue
    }

    private static func isBluetoothAddress(_ value: String) -> Bool {
        let parts = value.split(separator: ":")
        guard parts.count == 6 else { return false }
        return parts.allSatisfy { $0.count == 2 && $0.allSatisfy(\.isHexDigit) }
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
        return makeSettings(interfaceType: interfaceType, identifier: identifier, autoSwitch: true)
    }

    private func savedDiscoveredPrinter() -> DiscoveredPrinter? {
        guard let settings = loadSavedSettings() else { return nil }
        let name = UserDefaults.standard.string(forKey: Self.savedNameKey) ?? settings.identifier
        var alternates: [String] = []
        if settings.identifier.isEmpty {
            alternates = PrinterBluetoothNames.commonPortNames
        } else {
            for accessory in EAAccessoryManager.shared().connectedAccessories
            where accessory.protocolStrings.contains(Self.starEAProtocol) {
                if !accessory.name.isEmpty { alternates.append(accessory.name) }
                if !accessory.serialNumber.isEmpty { alternates.append(accessory.serialNumber) }
            }
        }
        return DiscoveredPrinter(
            identifier: settings.identifier,
            interfaceType: settings.interfaceType,
            model: name,
            alternateIdentifiers: alternates
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
