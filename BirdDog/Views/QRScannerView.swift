import SwiftUI
import AVFoundation

struct QRScannerView: View {
    @Binding var isPresented: Bool
    var onPaired: () -> Void

    @State private var scannedPayload: PairingPayload?
    @State private var errorMessage: String?
    @State private var isPairing = false
    @State private var cameraFailed = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                QRCameraPreview(onCodeScanned: handleScanned, onCameraFailed: {
                    cameraFailed = true
                })
                .ignoresSafeArea()

                VStack {
                    Spacer()

                    if cameraFailed {
                        VStack(spacing: 12) {
                            Image(systemName: "camera.metering.unknown")
                                .font(.system(size: 48))
                                .foregroundStyle(.orange)
                            Text("Camera Unavailable")
                                .font(.title3.bold())
                                .foregroundStyle(.white)
                            Text("Close this screen and try again. Make sure BirdDog has camera permission in Settings.")
                                .font(.callout)
                                .foregroundStyle(.white.opacity(0.8))
                                .multilineTextAlignment(.center)
                        }
                        .padding(24)
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
                        .padding()
                    } else if let error = errorMessage {
                        Text(error)
                            .font(.callout)
                            .foregroundStyle(.white)
                            .padding()
                            .background(.red.opacity(0.8), in: RoundedRectangle(cornerRadius: 12))
                            .padding()
                    }

                    if let payload = scannedPayload {
                        confirmationCard(payload)
                    } else if !cameraFailed {
                        instructionCard
                    }
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }
                        .foregroundStyle(.white)
                }
            }
        }
    }

    private var instructionCard: some View {
        VStack(spacing: 12) {
            Image(systemName: "qrcode.viewfinder")
                .font(.system(size: 48))
                .foregroundStyle(.white)
            Text("Scan Pairing QR Code")
                .font(.title3.bold())
                .foregroundStyle(.white)
            Text("Open the Quarry dashboard on a computer and go to Devices to generate a pairing code.")
                .font(.callout)
                .foregroundStyle(.white.opacity(0.8))
                .multilineTextAlignment(.center)
        }
        .padding(24)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
        .padding()
    }

    private func confirmationCard(_ payload: PairingPayload) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 40))
                .foregroundStyle(.green)

            Text(payload.name.isEmpty ? "Server Found" : payload.name)
                .font(.title3.bold())
                .foregroundStyle(.primary)

            Text(payload.url)
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                Button("Cancel") {
                    scannedPayload = nil
                    errorMessage = nil
                }
                .buttonStyle(.bordered)

                Button("Connect") {
                    pair(payload)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isPairing)
            }
        }
        .padding(24)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .padding()
    }

    private func handleScanned(_ code: String) {
        guard scannedPayload == nil else { return }

        guard let data = code.data(using: .utf8),
              let payload = try? JSONDecoder().decode(PairingPayload.self, from: data) else {
            errorMessage = "Invalid QR code. Use the code from your Quarry dashboard."
            return
        }

        guard !payload.url.isEmpty, !payload.key.isEmpty else {
            errorMessage = "QR code is missing server information."
            return
        }

        errorMessage = nil
        scannedPayload = payload
    }

    private func pair(_ payload: PairingPayload) {
        isPairing = true
        let settings = AppSettings.shared
        settings.houndDogURL = payload.url
        settings.houndDogAPIKey = payload.key
        if !payload.name.isEmpty {
            settings.schoolName = payload.name
        }
        if !payload.oktaIssuer.isEmpty {
            settings.oktaIssuer = payload.oktaIssuer
        }
        if !payload.oktaClientId.isEmpty {
            settings.oktaClientId = payload.oktaClientId
        }

        HoundDogSyncService.shared.resetSyncDates()
        HoundDogSyncService.shared.startIfConfigured()
        isPairing = false
        isPresented = false
        onPaired()
    }
}

struct PairingPayload: Decodable {
    let url: String
    let key: String
    let name: String
    let oktaIssuer: String
    let oktaClientId: String

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.url = try container.decode(String.self, forKey: .url)
        self.key = try container.decode(String.self, forKey: .key)
        self.name = try container.decodeIfPresent(String.self, forKey: .name) ?? ""
        self.oktaIssuer = try container.decodeIfPresent(String.self, forKey: .oktaIssuer) ?? ""
        self.oktaClientId = try container.decodeIfPresent(String.self, forKey: .oktaClientId) ?? ""
    }

    enum CodingKeys: String, CodingKey {
        case url, key, name
        case oktaIssuer = "okta_issuer"
        case oktaClientId = "okta_client_id"
    }
}

// MARK: - Camera Preview (UIViewRepresentable)

struct QRCameraPreview: UIViewRepresentable {
    var onCodeScanned: (String) -> Void
    var onCameraFailed: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onCodeScanned: onCodeScanned, onCameraFailed: onCameraFailed)
    }

    func makeUIView(context: Context) -> UIView {
        let container = UIView()
        container.backgroundColor = .black
        context.coordinator.containerView = container
        return container
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.startIfNeeded()
    }

    class Coordinator: NSObject, AVCaptureMetadataOutputObjectsDelegate {
        let onCodeScanned: (String) -> Void
        let onCameraFailed: () -> Void
        weak var containerView: UIView?
        private var captureSession: AVCaptureSession?
        private var previewLayer: AVCaptureVideoPreviewLayer?
        private var hasScanned = false
        private var didAttemptSetup = false

        init(onCodeScanned: @escaping (String) -> Void, onCameraFailed: @escaping () -> Void) {
            self.onCodeScanned = onCodeScanned
            self.onCameraFailed = onCameraFailed
        }

        deinit {
            captureSession?.stopRunning()
        }

        func startIfNeeded() {
            guard !didAttemptSetup, let container = containerView, container.bounds.width > 0 else { return }
            didAttemptSetup = true

            let authStatus = AVCaptureDevice.authorizationStatus(for: .video)
            switch authStatus {
            case .authorized:
                setupCamera(in: container)
            case .notDetermined:
                AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                    DispatchQueue.main.async {
                        if granted, let self, let container = self.containerView {
                            self.setupCamera(in: container)
                        } else {
                            self?.onCameraFailed()
                        }
                    }
                }
            default:
                onCameraFailed()
            }
        }

        private func setupCamera(in container: UIView) {
            let session = AVCaptureSession()
            session.beginConfiguration()

            if session.canSetSessionPreset(.high) {
                session.sessionPreset = .high
            } else if session.canSetSessionPreset(.medium) {
                session.sessionPreset = .medium
            }

            let device: AVCaptureDevice? =
                AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
                ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front)
                ?? AVCaptureDevice.default(for: .video)

            guard let camera = device else {
                session.commitConfiguration()
                DispatchQueue.main.async { self.onCameraFailed() }
                return
            }

            do {
                let input = try AVCaptureDeviceInput(device: camera)
                guard session.canAddInput(input) else {
                    session.commitConfiguration()
                    DispatchQueue.main.async { self.onCameraFailed() }
                    return
                }
                session.addInput(input)
            } catch {
                session.commitConfiguration()
                DispatchQueue.main.async { self.onCameraFailed() }
                return
            }

            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else {
                session.commitConfiguration()
                DispatchQueue.main.async { self.onCameraFailed() }
                return
            }
            session.addOutput(output)
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]

            session.commitConfiguration()

            let preview = AVCaptureVideoPreviewLayer(session: session)
            preview.videoGravity = .resizeAspectFill
            preview.frame = container.bounds
            container.layer.addSublayer(preview)

            self.captureSession = session
            self.previewLayer = preview

            DispatchQueue.global(qos: .userInitiated).async {
                session.startRunning()

                DispatchQueue.main.async { [weak self] in
                    self?.previewLayer?.frame = container.bounds
                }
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                guard let self, let container = self.containerView else { return }
                self.previewLayer?.frame = container.bounds
            }
        }

        func metadataOutput(
            _ output: AVCaptureMetadataOutput,
            didOutput metadataObjects: [AVMetadataObject],
            from connection: AVCaptureConnection
        ) {
            guard !hasScanned,
                  let object = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
                  let value = object.stringValue else { return }

            hasScanned = true
            AudioServicesPlaySystemSound(SystemSoundID(kSystemSoundID_Vibrate))
            onCodeScanned(value)

            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                self?.hasScanned = false
            }
        }
    }
}
