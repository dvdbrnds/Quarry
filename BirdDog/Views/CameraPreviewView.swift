import SwiftUI
import AVFoundation

struct CameraPreviewView: UIViewRepresentable {

    let session: AVCaptureSession
    var cameraSwitchCount: Int

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {
        uiView.configureForCurrentCamera()
    }

    final class PreviewUIView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

        private var sessionObserver: NSObjectProtocol?
        private var retryTimer: Timer?

        private var configObserver: NSObjectProtocol?

        override func didMoveToWindow() {
            super.didMoveToWindow()

            sessionObserver = NotificationCenter.default.addObserver(
                forName: .AVCaptureSessionDidStartRunning,
                object: previewLayer.session,
                queue: .main
            ) { [weak self] _ in
                self?.configureWithRetries()
            }

            configObserver = NotificationCenter.default.addObserver(
                forName: NSNotification.Name("BirdDogCameraDidChange"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                self?.configureWithRetries()
            }

            configureForCurrentCamera()
        }

        deinit {
            retryTimer?.invalidate()
            if let observer = sessionObserver {
                NotificationCenter.default.removeObserver(observer)
            }
            if let observer = configObserver {
                NotificationCenter.default.removeObserver(observer)
            }
        }

        private func configureWithRetries() {
            configureForCurrentCamera()

            var attempts = 0
            retryTimer?.invalidate()
            retryTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] timer in
                attempts += 1
                self?.configureForCurrentCamera()
                if attempts >= 6 {
                    timer.invalidate()
                }
            }
        }

        func configureForCurrentCamera() {
            guard let connection = previewLayer.connection,
                  let session = previewLayer.session,
                  let deviceInput = session.inputs.compactMap({ $0 as? AVCaptureDeviceInput }).first else {
                return
            }

            let isExternal = deviceInput.device.deviceType == .external

            if isExternal {
                if connection.isVideoMirroringSupported {
                    connection.automaticallyAdjustsVideoMirroring = false
                    connection.isVideoMirrored = false
                }

                // External cameras deliver landscape frames. The built-in camera
                // default rotation is 90° (landscape sensor → portrait display),
                // which is wrong for external cameras. Reset to 0 so the landscape
                // frame displays as-is, matching what the camera actually sees.
                if connection.isVideoRotationAngleSupported(0) {
                    connection.videoRotationAngle = 0
                }
            }
        }
    }
}
