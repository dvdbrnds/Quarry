import SwiftUI
import AVFoundation

struct QRScannerView: View {
    @Binding var isPresented: Bool
    var onPaired: () -> Void

    @State private var scannedPayload: PairingPayload?
    @State private var errorMessage: String?
    @State private var isPairing = false

    var body: some View {
        ZStack {
            QRCameraPreview(onCodeScanned: handleScanned)
                .ignoresSafeArea()

            VStack {
                Spacer()

                if let error = errorMessage {
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(.white)
                        .padding()
                        .background(.red.opacity(0.8), in: RoundedRectangle(cornerRadius: 12))
                        .padding()
                }

                if let payload = scannedPayload {
                    confirmationCard(payload)
                } else {
                    instructionCard
                }
            }
        }
        .navigationBarTitleDisplayMode(.inline)
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

struct QRCameraPreview: UIViewRepresentable {
    var onCodeScanned: (String) -> Void

    func makeUIView(context: Context) -> QRPreviewUIView {
        let view = QRPreviewUIView()
        view.onCodeScanned = onCodeScanned
        return view
    }

    func updateUIView(_ uiView: QRPreviewUIView, context: Context) {}
}

class QRPreviewUIView: UIView, AVCaptureMetadataOutputObjectsDelegate {
    var onCodeScanned: ((String) -> Void)?
    private var captureSession: AVCaptureSession?
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var hasScanned = false

    override func layoutSubviews() {
        super.layoutSubviews()
        previewLayer?.frame = bounds
        if captureSession == nil {
            setupCamera()
        }
    }

    private func setupCamera() {
        let session = AVCaptureSession()
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return }

        session.addInput(input)

        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]

        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        preview.frame = bounds
        layer.addSublayer(preview)

        self.captureSession = session
        self.previewLayer = preview

        DispatchQueue.global(qos: .userInitiated).async {
            session.startRunning()
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
        onCodeScanned?(value)

        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            self?.hasScanned = false
        }
    }
}
