import Foundation
import StarIO10

@MainActor
final class PrinterService: ObservableObject {
    static let shared = PrinterService()

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
            model.isEmpty ? id : "\(model) (\(id))"
        }

        var interfaceLabel: String { "Bluetooth LE" }
    }

    private static let savedIdentifierKey = "PrinterService.identifier"
    private static let savedInterfaceKey = "PrinterService.interfaceType"
    private static let autoPrintKey = "PrinterService.autoPrint"

    private var printer: StarPrinter?
    private var discoveryManager: StarDeviceDiscoveryManager?

    private init() {
        self.autoPrintEnabled = UserDefaults.standard.bool(forKey: Self.autoPrintKey)
    }

    // MARK: - Discovery

    func startDiscovery() {
        stopDiscovery()
        discoveredPrinters = []
        isSearching = true

        do {
            let manager = try StarDeviceDiscoveryManagerFactory.create(
                interfaceTypes: [.bluetoothLE]
            )
            manager.discoveryTime = 10_000
            self.discoveryManager = manager

            let wrapper = DiscoveryDelegate { [weak self] found in
                Task { @MainActor in
                    guard let self else { return }
                    let dp = DiscoveredPrinter(
                        id: found.connectionSettings.identifier,
                        interfaceType: found.connectionSettings.interfaceType,
                        model: found.information?.model?.rawValue.description ?? ""
                    )
                    if !self.discoveredPrinters.contains(where: { $0.id == dp.id }) {
                        self.discoveredPrinters.append(dp)
                    }
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

    func stopDiscovery() {
        discoveryManager?.stopDiscovery()
        discoveryManager = nil
        isSearching = false
    }

    private var _discoveryDelegate: DiscoveryDelegate?

    // MARK: - Connect / Disconnect

    func connect(to discovered: DiscoveredPrinter) {
        Task {
            await disconnect()

            connectionState = .connecting
            lastError = nil

            let settings = StarConnectionSettings(
                interfaceType: discovered.interfaceType,
                identifier: discovered.id
            )
            let p = StarPrinter(settings)

            do {
                try await p.open()
                self.printer = p
                self.printerName = discovered.displayName
                self.connectionState = .connected

                UserDefaults.standard.set(discovered.id, forKey: Self.savedIdentifierKey)
                UserDefaults.standard.set(discovered.interfaceType.rawValue, forKey: Self.savedInterfaceKey)
            } catch {
                connectionState = .error
                lastError = error.localizedDescription
                await p.close()
            }
        }
    }

    func disconnect() async {
        if let p = printer {
            await p.close()
        }
        printer = nil
        connectionState = .disconnected
        printerName = ""
    }

    func reconnectSaved() {
        guard let identifier = UserDefaults.standard.string(forKey: Self.savedIdentifierKey),
              let rawInterface = UserDefaults.standard.object(forKey: Self.savedInterfaceKey) as? Int,
              let interfaceType = InterfaceType(rawValue: rawInterface) else {
            return
        }

        let discovered = DiscoveredPrinter(
            id: identifier,
            interfaceType: interfaceType,
            model: ""
        )
        connect(to: discovered)
    }

    // MARK: - Print

    func printCommands(_ commands: String) async throws {
        guard let p = printer else {
            throw PrintError.notConnected
        }

        isPrinting = true
        lastError = nil

        do {
            try await p.open()
            try await p.print(command: commands)
            await p.close()
            isPrinting = false
        } catch {
            isPrinting = false
            lastError = error.localizedDescription

            if connectionState == .connected {
                connectionState = .error
            }
            throw error
        }
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
    }

    // MARK: - Errors

    enum PrintError: LocalizedError {
        case notConnected

        var errorDescription: String? {
            switch self {
            case .notConnected: return "No printer connected"
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
