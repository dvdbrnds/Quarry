import AVFoundation
import UIKit
import QuartzCore

protocol CameraServiceDelegate: AnyObject {
    func cameraService(_ service: CameraService, didOutput sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation)
}

enum CameraStatus: String {
    case externalActive = "EXT"
    case searchingExternal = "Searching..."
    case builtIn = "Built-in"
}

struct FrameMetrics: Sendable {
    var framesReceived: Int = 0
    var framesProcessed: Int = 0
    var framesSkipped: Int = 0
    var totalOCRTimeMs: Double = 0
    var peakOCRTimeMs: Double = 0
    var actualFPS: Double = 0
    var resolution: String = "—"
    var configuredFPS: Int = 0

    var skipRatio: Double {
        guard framesReceived > 0 else { return 0 }
        return Double(framesSkipped) / Double(framesReceived)
    }

    var avgOCRTimeMs: Double {
        guard framesProcessed > 0 else { return 0 }
        return totalOCRTimeMs / Double(framesProcessed)
    }

    var pixelThroughput: Double {
        let parts = resolution.split(separator: "x")
        guard parts.count == 2,
              let w = Double(parts[0]),
              let h = Double(parts[1]) else { return 0 }
        return w * h * actualFPS
    }
}

final class CameraService: NSObject, ObservableObject, @unchecked Sendable {

    let session = AVCaptureSession()
    weak var delegate: CameraServiceDelegate?

    private let sessionQueue = DispatchQueue(label: "com.birddog.camera.session")
    private let outputQueue = DispatchQueue(label: "com.birddog.camera.output", qos: .default)

    private var frameCount: UInt64 = 0
    private var frameSkip: Int = 2
    private var isProcessing = false
    private var cachedOrientation: CGImagePropertyOrientation = .right

    private(set) var isRunning = false
    private(set) var isUsingExternalCamera = false
    @Published var debugLog: [String] = []
    @Published var cameraSwitchCount: Int = 0
    @Published var cameraStatus: CameraStatus = .builtIn
    @Published var activeCameraName: String = "None"
    @Published var activeResolution: String = "—"
    @Published var activeFPS: String = "—"
    @Published var detectedDeviceCount: Int = 0
    @Published var exposureBias: Float = 0 {
        didSet { applyExposureBias() }
    }
    @Published var focusScore: Double = 0
    @Published var focusPeak: Double = 0
    @Published var exposureLocked: Bool = false
    @Published var liveMetrics = FrameMetrics()
    var focusMeterEnabled = false
    var highBandwidthMode = false

    private var metricsFrameTimestamps: [CFTimeInterval] = []
    private var metricsAccumulator = FrameMetrics()

    private var currentDevice: AVCaptureDevice?
    private var currentInput: AVCaptureDeviceInput?
    private var videoOutput: AVCaptureVideoDataOutput?
    private var systemPreferredObservation: Any?
    private var discoveryObservation: NSKeyValueObservation?
    private var discoverySession: AVCaptureDevice.DiscoverySession?
    private var hasSetInitialPreference = false
    private var pollTimer: Timer?
    private let baseSharpnessThreshold: Double = 12.0
    private var lastFrameSharpness: Double = 999
    private var recentSharpnessValues: [Double] = []
    private let sharpnessHistorySize = 30

    /// Adaptive sharpness threshold: rejects the bottom 20% of recent frames.
    /// Falls back to the base threshold until enough history is collected.
    private var adaptiveSharpnessThreshold: Double {
        guard recentSharpnessValues.count >= 10 else { return baseSharpnessThreshold }
        let sorted = recentSharpnessValues.sorted()
        let idx = sorted.count / 5
        return max(baseSharpnessThreshold, sorted[idx])
    }

    // Scene-change detection: skip OCR on frames where the scene hasn't changed
    private var lastProcessedFingerprint: [UInt8] = []
    private let sceneChangeThreshold: Double = 0.08
    /// Set when rectangle detector hints a plate-shaped object is visible
    var rectangleDetectedHint = false

    func start() {
        if !isRunning {
            logFileHandle?.closeFile()
            logFileHandle = nil
            try? FileManager.default.removeItem(at: Self.logFileURL)
        }
        log("START called (isRunning=\(isRunning))")
        startOrientationObserver()
        setupSystemPreferredCameraObserver()
        setupInterruptionObservers()
        sessionQueue.async { [weak self] in
            guard let self, !self.isRunning else {
                self?.log("START: already running, skipping")
                return
            }

            // Start immediately with built-in camera for fast launch.
            // External cameras through USB hubs need the session running
            // before the XPC pipe stabilizes — discovery and even input
            // creation succeed before the hardware is actually usable.
            self.configureSession()
            self.session.startRunning()
            self.isRunning = true

            if !self.isUsingExternalCamera {
                self.log("Started with built-in — waiting for external camera")
                self.startPollingIfNeeded()
            }
        }
    }

    func stop() {
        stopPolling()
        exposureLockTimer?.invalidate()
        exposureRefreshTimer?.invalidate()
        brightnessCheckTimer?.invalidate()
        sessionQueue.async { [weak self] in
            guard let self, self.isRunning else { return }
            self.session.stopRunning()
            self.isRunning = false
            self.latestSampleBuffer = nil
            self.logFileHandle?.closeFile()
            self.logFileHandle = nil
        }
    }

    // MARK: - Violation Photo Capture

    private var latestSampleBuffer: CMSampleBuffer?

    func captureViolationPhoto() -> String? {
        guard let buffer = latestSampleBuffer,
              let imageBuffer = CMSampleBufferGetImageBuffer(buffer) else { return nil }
        return saveBufferAsJPEG(imageBuffer)
    }

    private var oneShotCapture = false
    /// Set from main thread to immediately suppress all frame processing.
    /// Checked at the top of captureOutput before any work happens.
    var outputSuppressed = false

    /// Grab a photo from the camera. Uses the latest buffered frame if available,
    /// otherwise briefly restarts the camera to capture one fresh frame.
    func captureOneShotPhoto() async -> String? {
        // If session is running and we have a recent buffer, use it directly
        if isRunning && latestSampleBuffer != nil {
            return captureViolationPhoto()
        }

        // Need to start the session to get a fresh frame
        let wasRunning = isRunning
        let savedSuppressed = outputSuppressed
        oneShotCapture = true
        outputSuppressed = false
        await withCheckedContinuation { cont in
            sessionQueue.async { [weak self] in
                guard let self else { cont.resume(); return }
                if !self.isRunning {
                    self.session.startRunning()
                    self.isRunning = true
                }
                cont.resume()
            }
        }
        try? await Task.sleep(nanoseconds: 400_000_000)

        let path = captureViolationPhoto()

        // Only stop the session if it wasn't running before we started it
        if !wasRunning {
            await withCheckedContinuation { cont in
                sessionQueue.async { [weak self] in
                    guard let self, self.isRunning else { cont.resume(); return }
                    self.session.stopRunning()
                    self.isRunning = false
                    self.oneShotCapture = false
                    cont.resume()
                }
            }
        } else {
            oneShotCapture = false
        }
        outputSuppressed = savedSuppressed
        return path
    }

    private func saveBufferAsJPEG(_ imageBuffer: CVPixelBuffer) -> String? {
        let ciImage = CIImage(cvPixelBuffer: imageBuffer)
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return nil }

        let imageOrientation: UIImage.Orientation
        if isUsingExternalCamera {
            switch externalCameraOrientation {
            case .right: imageOrientation = .right
            case .down:  imageOrientation = .down
            case .left:  imageOrientation = .left
            default:     imageOrientation = .up
            }
        } else {
            imageOrientation = .right
        }
        let uiImage = UIImage(cgImage: cgImage, scale: 1.0, orientation: imageOrientation)
        let targetSize = CGSize(width: 640, height: 480)
        let renderer = UIGraphicsImageRenderer(size: targetSize)
        let resized = renderer.image { _ in uiImage.draw(in: CGRect(origin: .zero, size: targetSize)) }

        guard let jpegData = resized.jpegData(compressionQuality: 0.6) else { return nil }

        let dir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
            .appendingPathComponent("violation_photos", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        let filename = "violation_\(UUID().uuidString).jpg"
        let fileURL = dir.appendingPathComponent(filename)
        try? jpegData.write(to: fileURL)
        return fileURL.path
    }

    static func deleteViolationPhoto(at path: String) {
        try? FileManager.default.removeItem(atPath: path)
    }

    /// Force a full session teardown and rebuild. Exposed for the admin
    /// "Reconnect Camera" button and internal hub retry logic.
    func forceReconnect() {
        log("FORCE RECONNECT requested")
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.isReconnecting = true

            // 1. Full teardown: stop session, strip all inputs/outputs,
            //    nil every device reference so the system can release the
            //    USB device's XPC connection completely.
            self.session.stopRunning()
            self.session.beginConfiguration()
            for input in self.session.inputs { self.session.removeInput(input) }
            for output in self.session.outputs { self.session.removeOutput(output) }
            self.session.commitConfiguration()
            self.currentInput = nil
            self.currentDevice = nil
            self.videoOutput = nil
            self.isUsingExternalCamera = false

            // 2. Start the session empty. An empty running session keeps
            //    the AVCaptureSession's USB subsystem active, which primes
            //    the hub's transaction translator for the device.
            self.session.startRunning()
            self.log("RECONNECT: session running empty, waiting for hub to settle")
            Thread.sleep(forTimeInterval: 1.5)

            // 3. Now try adding the camera to the running session.
            //    Fresh discovery after the sleep gives the hub time to
            //    fully re-enumerate the device and its endpoints.
            let maxAttempts = 5
            var connected = false
            for attempt in 1...maxAttempts {
                let discovery = AVCaptureDevice.DiscoverySession(
                    deviceTypes: [.external],
                    mediaType: .video,
                    position: .unspecified
                )
                guard let camera = discovery.devices.first else {
                    self.log("RECONNECT attempt \(attempt)/\(maxAttempts): no external camera visible")
                    Thread.sleep(forTimeInterval: 2.0)
                    continue
                }

                self.log("RECONNECT attempt \(attempt)/\(maxAttempts): found \(camera.localizedName), adding to running session")

                guard let input = try? AVCaptureDeviceInput(device: camera) else {
                    self.log("RECONNECT attempt \(attempt)/\(maxAttempts): AVCaptureDeviceInput failed")
                    Thread.sleep(forTimeInterval: 2.0)
                    continue
                }

                self.session.beginConfiguration()
                // Remove stale inputs/outputs from any previous attempt
                for i in self.session.inputs { self.session.removeInput(i) }
                for o in self.session.outputs { self.session.removeOutput(o) }

                guard self.session.canAddInput(input) else {
                    self.log("RECONNECT attempt \(attempt)/\(maxAttempts): canAddInput refused")
                    self.session.commitConfiguration()
                    Thread.sleep(forTimeInterval: 2.0)
                    continue
                }
                self.session.addInput(input)
                self.currentInput = input
                self.currentDevice = camera

                self.session.sessionPreset = .inputPriority
                self.configureCameraForStreetUse(camera, isExternal: true)
                self.cachedOrientation = self.externalCameraOrientation
                self.frameSkip = 2

                let output = AVCaptureVideoDataOutput()
                output.alwaysDiscardsLateVideoFrames = true
                output.videoSettings = [
                    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
                ]
                output.setSampleBufferDelegate(self, queue: self.outputQueue)
                if self.session.canAddOutput(output) {
                    self.session.addOutput(output)
                    self.videoOutput = output
                    if let conn = output.connection(with: .video), conn.isVideoMirroringSupported {
                        conn.automaticallyAdjustsVideoMirroring = false
                        conn.isVideoMirrored = false
                    }
                }
                self.session.commitConfiguration()

                // 4. Verify frames arrive — the definitive test that the
                //    XPC pipe is actually working.
                self.lastFrameTime = nil
                self.log("RECONNECT attempt \(attempt)/\(maxAttempts): config committed, verifying frames...")
                Thread.sleep(forTimeInterval: 2.0)

                if self.lastFrameTime != nil {
                    self.isUsingExternalCamera = true
                    self.cachedOrientation = self.externalCameraOrientation
                    self.lastConnectedAt = Date()
                    self.log("RECONNECT: external camera LIVE on attempt \(attempt)")
                    self.publishCameraInfo(camera)
                    DispatchQueue.main.async { [weak self] in
                        self?.cameraStatus = .externalActive
                        self?.cameraSwitchCount += 1
                        NotificationCenter.default.post(name: NSNotification.Name("BirdDogCameraDidChange"), object: nil)
                    }
                    connected = true
                    break
                } else {
                    self.log("RECONNECT attempt \(attempt)/\(maxAttempts): no frames — XPC pipe dead, retrying")
                    // Strip the dead input so next attempt starts clean
                    self.session.beginConfiguration()
                    for i in self.session.inputs { self.session.removeInput(i) }
                    for o in self.session.outputs { self.session.removeOutput(o) }
                    self.session.commitConfiguration()
                    self.currentInput = nil
                    self.currentDevice = nil
                    self.videoOutput = nil
                    Thread.sleep(forTimeInterval: 1.0)
                }
            }

            if !connected {
                self.log("RECONNECT: external camera unavailable after \(maxAttempts) attempts, falling back")
                // Fall back to built-in camera on the already-running session
                self.session.stopRunning()
                self.configureSession()
                self.session.startRunning()
            }

            self.isRunning = true
            self.isReconnecting = false
            if connected {
                self.stopPolling()
            } else {
                self.stopPolling()
                self.startPollingIfNeeded()
            }
        }
    }

    private var lastFrameTime: Date?
    private var burstUntil: Date = .distantPast

    /// Minimum frame skip set by motion/speed service to prevent over-scanning when stationary
    var motionMinFrameSkip: Int = 2

    func markProcessingComplete(elapsed: TimeInterval) {
        isProcessing = false

        let elapsedMs = elapsed * 1000.0
        metricsAccumulator.framesProcessed += 1
        metricsAccumulator.totalOCRTimeMs += elapsedMs
        if elapsedMs > metricsAccumulator.peakOCRTimeMs {
            metricsAccumulator.peakOCRTimeMs = elapsedMs
        }

        if Date() < burstUntil {
            frameSkip = 1
            return
        }

        let maxSkip = isUsingExternalCamera ? 6 : 8
        let minSkip = max(isUsingExternalCamera ? 1 : 2, motionMinFrameSkip)

        if elapsed > 0.20 {
            frameSkip = min(frameSkip + 1, maxSkip)
        } else if elapsed < 0.10, frameSkip > minSkip {
            frameSkip -= 1
        }
        if frameSkip < minSkip {
            frameSkip = minSkip
        }
    }

    /// Snapshot current metrics and reset accumulators for the next session.
    func snapshotAndResetMetrics() -> FrameMetrics {
        var snapshot = metricsAccumulator
        snapshot.actualFPS = Double(metricsFrameTimestamps.count)
        snapshot.resolution = activeResolution
        if let fps = Int(activeFPS.replacingOccurrences(of: "fps", with: "")) {
            snapshot.configuredFPS = fps
        }
        metricsAccumulator = FrameMetrics()
        metricsFrameTimestamps.removeAll()
        return snapshot
    }

    /// Temporarily drop to frameSkip=1 for a short burst to capture more
    /// frames of a plate that just appeared.
    func triggerBurst(duration: TimeInterval = 1.5) {
        burstUntil = Date().addingTimeInterval(duration)
        frameSkip = 1
    }

    // MARK: - Polling for External Camera (USB Hub Workaround)

    /// KVO and system-preferred-camera notifications can miss devices connected
    /// through USB hubs. This timer polls every 3 seconds until an external
    /// camera is found.
    private func startPollingIfNeeded() {
        guard !isUsingExternalCamera else {
            stopPolling()
            return
        }
        guard pollTimer == nil else { return }

        log("Starting external camera poll timer")
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.cameraStatus = .searchingExternal
            self.pollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
                self?.pollForExternalCamera()
            }
        }
    }

    private func stopPolling() {
        DispatchQueue.main.async { [weak self] in
            self?.pollTimer?.invalidate()
            self?.pollTimer = nil
        }
    }

    private var isReconnecting = false
    private var hubReconnectWork: DispatchWorkItem?
    private var pollIteration = 0
    /// Suppress reconnect triggers for a stability window after successful connection
    private var lastConnectedAt: Date = .distantPast
    private let stabilityWindow: TimeInterval = 30

    /// Debounced reconnect for hot-plug through USB hubs.
    /// When a camera is plugged in, multiple observers fire in rapid
    /// succession while the hub is still initializing the device's
    /// streaming endpoints. This coalesces them into a single attempt
    /// after a 5-second delay to let the hub fully enumerate.
    private func scheduleHubReconnect() {
        if isUsingExternalCamera && Date().timeIntervalSince(lastConnectedAt) < stabilityWindow {
            log("Ignoring reconnect trigger — within stability window")
            return
        }
        hubReconnectWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.isRunning, !self.isUsingExternalCamera else { return }
            self.log("Hub settle delay elapsed — starting reconnect")
            self.forceReconnect()
        }
        hubReconnectWork = work
        log("Reconnect scheduled in 2s (hub enumeration delay)")
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 2.0, execute: work)
    }

    private func pollForExternalCamera() {
        sessionQueue.async { [weak self] in
            guard let self, self.isRunning, !self.isUsingExternalCamera, !self.isReconnecting else {
                return
            }

            self.pollIteration += 1

            // Discover ALL video device types to catch any misclassification
            let allTypes: [AVCaptureDevice.DeviceType] = [
                .external,
                .builtInWideAngleCamera,
                .builtInUltraWideCamera,
                .builtInTelephotoCamera,
            ]
            let allDevices = AVCaptureDevice.DiscoverySession(
                deviceTypes: allTypes,
                mediaType: .video,
                position: .unspecified
            ).devices

            let externalDevices = allDevices.filter { $0.deviceType == .external }

            // Log full details every 5th poll, summary otherwise
            if self.pollIteration % 5 == 1 {
                self.log("POLL #\(self.pollIteration): \(allDevices.count) device(s), \(externalDevices.count) external")
                for d in allDevices {
                    self.log("  -> \(d.localizedName) type=\(d.deviceType) pos=\(d.position.rawValue) id=\(d.uniqueID)")
                }
            } else {
                self.log("POLL #\(self.pollIteration): \(allDevices.count) dev, \(externalDevices.count) ext")
            }

            DispatchQueue.main.async { [weak self] in
                self?.detectedDeviceCount = allDevices.count
            }

            if let external = externalDevices.first {
                self.log("POLL: found \(external.localizedName) — scheduling hub reconnect")
                self.stopPolling()
                self.scheduleHubReconnect()
            }
        }
    }

    // MARK: - Session Interruption Handling

    private func setupInterruptionObservers() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(sessionWasInterrupted),
            name: AVCaptureSession.wasInterruptedNotification,
            object: session
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(sessionInterruptionEnded),
            name: AVCaptureSession.interruptionEndedNotification,
            object: session
        )
    }

    @objc private func sessionWasInterrupted(_ notification: Notification) {
        guard !isReconnecting else { return }

        // If we recently connected and are getting frames, this is spurious
        if isUsingExternalCamera && Date().timeIntervalSince(lastConnectedAt) < stabilityWindow {
            log("SESSION INTERRUPTED (suppressed — within stability window)")
            return
        }

        var reasonStr = "unknown"
        if let rawValue = (notification.userInfo?[AVCaptureSessionInterruptionReasonKey] as? NSNumber)?.intValue,
           let reason = AVCaptureSession.InterruptionReason(rawValue: rawValue) {
            switch reason {
            case .videoDeviceNotAvailableInBackground:
                reasonStr = "background"
            case .videoDeviceNotAvailableWithMultipleForegroundApps:
                reasonStr = "multitask"
            case .videoDeviceNotAvailableDueToSystemPressure:
                reasonStr = "system_pressure"
            case .audioDeviceInUseByAnotherClient:
                reasonStr = "audio_in_use"
            case .videoDeviceInUseByAnotherClient:
                reasonStr = "video_in_use"
            case .sensitiveContentMitigationActivated:
                reasonStr = "sensitive_content"
            @unknown default:
                reasonStr = "reason_\(rawValue)"
            }
        } else {
            reasonStr = "device_disconnected"
        }
        log("SESSION INTERRUPTED: \(reasonStr)")

        isUsingExternalCamera = false
        DispatchQueue.main.async { [weak self] in
            self?.cameraStatus = .searchingExternal
        }
        startPollingIfNeeded()
    }

    @objc private func sessionInterruptionEnded(_ notification: Notification) {
        guard !isReconnecting else { return }
        // If within stability window, the camera is fine — don't tear it down
        if isUsingExternalCamera && Date().timeIntervalSince(lastConnectedAt) < stabilityWindow {
            log("SESSION INTERRUPTION ENDED (suppressed — within stability window)")
            return
        }
        log("SESSION INTERRUPTION ENDED — full reconnect to reacquire camera")
        forceReconnect()
    }

    // MARK: - Hot-Plug Camera Detection

    /// Uses two complementary observers:
    /// 1. systemPreferredCamera (Apple's recommended WWDC23 approach)
    /// 2. DiscoverySession.devices (backup, watches for external cameras directly)
    private func setupSystemPreferredCameraObserver() {
        if !hasSetInitialPreference {
            let backCamera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
            if let external = findExternalCamera() {
                AVCaptureDevice.userPreferredCamera = external
            } else if let backCamera {
                AVCaptureDevice.userPreferredCamera = backCamera
            }
            hasSetInitialPreference = true
        }

        systemPreferredObservation = NotificationCenter.default.addObserver(
            forName: NSNotification.Name("AVCaptureDeviceSystemPreferredCameraDidChangeNotification"),
            object: nil,
            queue: nil
        ) { [weak self] _ in
            guard let self else { return }
            guard !self.isReconnecting else { return }
            // Suppress if camera is stable
            if self.isUsingExternalCamera && Date().timeIntervalSince(self.lastConnectedAt) < self.stabilityWindow { return }
            guard let newCamera = AVCaptureDevice.systemPreferredCamera else { return }
            if newCamera.deviceType == .external, !self.isUsingExternalCamera, !self.isReconnecting {
                self.log("System preferred external camera — scheduling reconnect")
                self.scheduleHubReconnect()
            } else if newCamera.deviceType != .external, !self.isUsingExternalCamera {
                self.sessionQueue.async {
                    self.switchToCamera(newCamera)
                }
            }
        }

        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.external, .builtInWideAngleCamera],
            mediaType: .video,
            position: .unspecified
        )
        self.discoverySession = discovery

        discoveryObservation = discovery.observe(
            \.devices,
            options: [.new]
        ) { [weak self] session, _ in
            guard let self else { return }
            guard !self.isReconnecting else { return }
            // Suppress if camera is connected and stable
            if self.isUsingExternalCamera && Date().timeIntervalSince(self.lastConnectedAt) < self.stabilityWindow { return }
            let devices = session.devices
            let external = devices.first(where: { $0.deviceType == .external })

            self.log("DEVICES CHANGED: \(devices.map { "\($0.localizedName) (\($0.deviceType == .external ? "EXTERNAL" : "built-in"))" }.joined(separator: ", "))")

            if let external {
                AVCaptureDevice.userPreferredCamera = external
                if !self.isUsingExternalCamera, !self.isReconnecting {
                    self.log("External camera appeared — scheduling reconnect")
                    self.scheduleHubReconnect()
                }
            } else if !self.isUsingExternalCamera {
                let best = devices.first(where: { $0.position == .back }) ?? devices.first
                if let best {
                    AVCaptureDevice.userPreferredCamera = best
                    self.sessionQueue.async { self.switchToCamera(best) }
                }
            }
        }
    }

    private func findExternalCamera() -> AVCaptureDevice? {
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.external],
            mediaType: .video,
            position: .unspecified
        )
        return discovery.devices.first
    }

    /// Switch the active camera while the session is running.
    private func switchToCamera(_ camera: AVCaptureDevice) {
        guard camera.uniqueID != currentDevice?.uniqueID else { return }

        guard let newInput = try? AVCaptureDeviceInput(device: camera) else {
            log("FAILED input for: \(camera.localizedName)")
            return
        }

        session.beginConfiguration()

        if let currentInput {
            session.removeInput(currentInput)
        }

        if session.canAddInput(newInput) {
            session.addInput(newInput)
            self.currentInput = newInput
            self.currentDevice = camera

            let isExternal = camera.deviceType == .external
            self.isUsingExternalCamera = isExternal

            if isExternal {
                session.sessionPreset = .inputPriority
            } else {
                let preset: AVCaptureSession.Preset = .high
                if session.canSetSessionPreset(preset) {
                    session.sessionPreset = preset
                }
            }

            configureCameraForStreetUse(camera, isExternal: isExternal)

            if isExternal {
                cachedOrientation = externalCameraOrientation
                frameSkip = 2
            } else {
                updateOrientationFromDevice()
                frameSkip = 2
            }

            if isExternal, let videoOut = self.videoOutput,
               let connection = videoOut.connection(with: .video) {
                if connection.isVideoMirroringSupported {
                    connection.automaticallyAdjustsVideoMirroring = false
                    connection.isVideoMirrored = false
                }
            }

            log("SWITCHED TO: \(camera.localizedName) (\(isExternal ? "EXTERNAL" : "built-in"))")
            publishCameraInfo(camera)
            if isExternal {
                stopPolling()
                lastConnectedAt = Date()
            }
            DispatchQueue.main.async { [weak self] in
                self?.cameraSwitchCount += 1
                self?.cameraStatus = isExternal ? .externalActive : .builtIn
            }
        } else {
            if let currentInput {
                session.addInput(currentInput)
            }
            log("FAILED to add: \(camera.localizedName) — hub may need session restart")
        }

        session.commitConfiguration()
    }

    // MARK: - Session Configuration

    private func configureSession() {
        session.beginConfiguration()

        // External camera always wins — that's the whole point of the golf cart setup.
        // Only fall back to built-in if no external camera is connected.
        let allDevices = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.external, .builtInWideAngleCamera],
            mediaType: .video,
            position: .unspecified
        ).devices

        log("discovered \(allDevices.count) camera(s)")
        for d in allDevices {
            log("  \(d.localizedName) | \(d.deviceType == .external ? "EXTERNAL" : "built-in") | pos=\(d.position.rawValue)")
        }

        let camera = allDevices.first(where: { $0.deviceType == .external })
            ?? allDevices.first(where: { $0.position == .back })
            ?? allDevices.first

        guard let camera,
              let input = try? AVCaptureDeviceInput(device: camera),
              session.canAddInput(input) else {
            log("no usable camera found")
            session.commitConfiguration()
            return
        }
        session.addInput(input)
        currentInput = input
        currentDevice = camera

        let isExternal = camera.deviceType == .external
        isUsingExternalCamera = isExternal

        if isExternal {
            session.sessionPreset = .inputPriority
        } else {
            let preset: AVCaptureSession.Preset = .high
            if session.canSetSessionPreset(preset) {
                session.sessionPreset = preset
            } else {
                session.sessionPreset = .medium
            }
        }

        configureCameraForStreetUse(camera, isExternal: isExternal)

        if isExternal {
            cachedOrientation = externalCameraOrientation
            frameSkip = 2
        }

        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        output.setSampleBufferDelegate(self, queue: outputQueue)
        guard session.canAddOutput(output) else {
            session.commitConfiguration()
            return
        }
        session.addOutput(output)
        videoOutput = output

        if isExternal, let connection = output.connection(with: .video) {
            if connection.isVideoMirroringSupported {
                connection.automaticallyAdjustsVideoMirroring = false
                connection.isVideoMirrored = false
                log("disabled video mirroring")
            }
        }

        session.commitConfiguration()

        log("ACTIVE: \(camera.localizedName) (\(isExternal ? "EXTERNAL" : "built-in")) preset=\(session.sessionPreset.rawValue)")
        publishCameraInfo(camera)
        DispatchQueue.main.async { [weak self] in
            self?.cameraStatus = isExternal ? .externalActive : .builtIn
            self?.detectedDeviceCount = allDevices.count
        }
        if isExternal { stopPolling() }
    }

    private func publishCameraInfo(_ camera: AVCaptureDevice) {
        let dims = CMVideoFormatDescriptionGetDimensions(camera.activeFormat.formatDescription)
        let fps = camera.activeFormat.videoSupportedFrameRateRanges.map(\.maxFrameRate).max() ?? 0
        let name = camera.localizedName
        let res = "\(dims.width)x\(dims.height)"
        let fpsStr = "\(Int(fps))fps"
        log("ACTIVE: \(name) \(res)@\(fpsStr)")
        DispatchQueue.main.async { [weak self] in
            self?.activeCameraName = name
            self?.activeResolution = res
            self?.activeFPS = fpsStr
        }
    }

    private static let logFileURL: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        return docs.appendingPathComponent("camera_debug.log")
    }()

    private static let logDateFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        return f
    }()

    private var logFileHandle: FileHandle?

    private func log(_ message: String) {
        let ts = Self.logDateFormatter.string(from: Date())
        let line = "[\(ts)] \(message)"

        if let data = (line + "\n").data(using: .utf8) {
            if logFileHandle == nil {
                if !FileManager.default.fileExists(atPath: Self.logFileURL.path) {
                    FileManager.default.createFile(atPath: Self.logFileURL.path, contents: nil)
                }
                logFileHandle = try? FileHandle(forWritingTo: Self.logFileURL)
                logFileHandle?.seekToEndOfFile()
            }
            logFileHandle?.write(data)
        }

        DispatchQueue.main.async { [weak self] in
            self?.debugLog.append(line)
            if (self?.debugLog.count ?? 0) > 100 {
                self?.debugLog.removeFirst()
            }
        }
    }

    private func configureCameraForStreetUse(_ camera: AVCaptureDevice, isExternal: Bool) {
        try? camera.lockForConfiguration()
        if camera.isFocusModeSupported(.continuousAutoFocus) {
            camera.focusMode = .continuousAutoFocus
        }
        if camera.isExposureModeSupported(.continuousAutoExposure) {
            camera.exposureMode = .continuousAutoExposure
        }
        if !isExternal && camera.isAutoFocusRangeRestrictionSupported {
            camera.autoFocusRangeRestriction = .near
        }

        if isExternal {
            camera.videoZoomFactor = camera.minAvailableVideoZoomFactor
            selectBestExternalFormat(for: camera)

            if camera.isFocusModeSupported(.locked) {
                camera.focusMode = .locked
                log("focus mode: locked (manual focus lens)")
            }

            if camera.isWhiteBalanceModeSupported(.locked) {
                camera.whiteBalanceMode = .locked
                log("white balance: locked")
            } else if camera.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                camera.whiteBalanceMode = .continuousAutoWhiteBalance
            }

            let bias = max(camera.minExposureTargetBias, min(exposureBias, camera.maxExposureTargetBias))
            camera.setExposureTargetBias(bias, completionHandler: nil)
            log("exposure bias: \(bias)")

            // Start with auto-exposure, then lock after it settles to prevent
            // the bright/dim flicker cycle that hurts OCR accuracy.
            if camera.isExposureModeSupported(.continuousAutoExposure) {
                camera.exposureMode = .continuousAutoExposure
                log("exposure: auto (will lock after settling)")
            }
        }

        camera.unlockForConfiguration()

        if isExternal {
            scheduleExposureLock(for: camera)
        }
    }

    private var exposureLockTimer: Timer?
    private var exposureRefreshTimer: Timer?
    private var brightnessCheckTimer: Timer?
    /// Mean brightness (0-1) at the time exposure was locked. Used to detect
    /// lighting changes that warrant an immediate exposure refresh.
    private var lockedBrightnessBaseline: Double = 0.5
    @Published var lastFrameBrightness: Double = 0.5

    private func scheduleExposureLock(for camera: AVCaptureDevice) {
        exposureLockTimer?.invalidate()
        exposureRefreshTimer?.invalidate()
        brightnessCheckTimer?.invalidate()
        DispatchQueue.main.async { [weak self] in
            self?.exposureLocked = false
        }
        exposureLockTimer = Timer.scheduledTimer(withTimeInterval: 3.5, repeats: false) { [weak self] _ in
            self?.lockExposureAndRecordBaseline(camera)
            self?.startExposureRefreshCycle(for: camera)
            self?.startBrightnessMonitoring(for: camera)
        }
    }

    private func startExposureRefreshCycle(for camera: AVCaptureDevice) {
        exposureRefreshTimer?.invalidate()
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let interval: TimeInterval = MotionSpeedService.shared.mode == .vehicle ? 25.0 : 45.0
            self.exposureRefreshTimer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
                self?.refreshExposure(camera)
            }
        }
    }

    /// Checks frame brightness every 2 seconds and forces an exposure refresh
    /// if brightness has drifted more than 30% from when exposure was locked.
    private func startBrightnessMonitoring(for camera: AVCaptureDevice) {
        brightnessCheckTimer?.invalidate()
        brightnessCheckTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            guard let self, self.exposureLocked, self.isUsingExternalCamera else { return }
            let delta = abs(self.lastFrameBrightness - self.lockedBrightnessBaseline)
            if delta > 0.30 {
                self.log("exposure: brightness drift \(String(format: "%.0f%%", delta * 100)) — forcing refresh")
                self.refreshExposure(camera)
            }
        }
    }

    /// Briefly unlock auto-exposure to adapt to lighting changes
    /// (sun/shade transitions, clouds), then re-lock.
    private func refreshExposure(_ camera: AVCaptureDevice) {
        sessionQueue.async { [weak self] in
            guard let self, self.isUsingExternalCamera else { return }
            guard camera.isExposureModeSupported(.continuousAutoExposure),
                  camera.isExposureModeSupported(.locked) else { return }

            try? camera.lockForConfiguration()
            camera.exposureMode = .continuousAutoExposure
            camera.unlockForConfiguration()
            self.log("exposure: unlocked for refresh")

            DispatchQueue.main.async { [weak self] in
                self?.exposureLocked = false
            }

            DispatchQueue.global().asyncAfter(deadline: .now() + 3.0) { [weak self] in
                self?.lockExposureAndRecordBaseline(camera)
            }
        }
    }

    private func lockExposure(_ camera: AVCaptureDevice) {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            guard camera.isExposureModeSupported(.locked) else {
                self.log("exposure: camera does not support locked mode")
                return
            }
            try? camera.lockForConfiguration()
            camera.exposureMode = .locked
            camera.unlockForConfiguration()
            self.log("exposure: LOCKED at current level (ISO=\(camera.iso), shutter=\(camera.exposureDuration.seconds)s)")
            DispatchQueue.main.async {
                self.exposureLocked = true
            }
        }
    }

    private func lockExposureAndRecordBaseline(_ camera: AVCaptureDevice) {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            guard camera.isExposureModeSupported(.locked) else {
                self.log("exposure: camera does not support locked mode")
                return
            }
            try? camera.lockForConfiguration()
            camera.exposureMode = .locked
            camera.unlockForConfiguration()
            self.lockedBrightnessBaseline = self.lastFrameBrightness
            self.log("exposure: LOCKED (ISO=\(camera.iso), shutter=\(camera.exposureDuration.seconds)s, brightness baseline=\(String(format: "%.2f", self.lockedBrightnessBaseline)))")
            DispatchQueue.main.async {
                self.exposureLocked = true
            }
        }
    }

    private func applyExposureBias() {
        sessionQueue.async { [weak self] in
            guard let self, let camera = self.currentDevice, self.isUsingExternalCamera else { return }
            try? camera.lockForConfiguration()
            let clamped = max(camera.minExposureTargetBias, min(self.exposureBias, camera.maxExposureTargetBias))
            camera.setExposureTargetBias(clamped, completionHandler: nil)

            if camera.isExposureModeSupported(.continuousAutoExposure) {
                camera.exposureMode = .continuousAutoExposure
            }
            camera.unlockForConfiguration()
            self.log("exposure bias → \(clamped), re-evaluating")

            DispatchQueue.main.async { [weak self] in
                self?.exposureLocked = false
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + 3.0) { [weak self] in
                self?.lockExposure(camera)
            }
        }
    }

    private func selectBestExternalFormat(for camera: AVCaptureDevice) {
        let allFormats = camera.formats
        log("external camera: \(allFormats.count) formats total")

        for (i, f) in allFormats.enumerated() {
            let d = CMVideoFormatDescriptionGetDimensions(f.formatDescription)
            let fps = f.videoSupportedFrameRateRanges.map(\.maxFrameRate).max() ?? 0
            let sub = CMFormatDescriptionGetMediaSubType(f.formatDescription)
            let fourCC = String(format: "%c%c%c%c",
                                (sub >> 24) & 0xFF, (sub >> 16) & 0xFF,
                                (sub >> 8) & 0xFF, sub & 0xFF)
            log("  [\(i)] \(d.width)x\(d.height) \(Int(fps))fps \(fourCC)")
        }

        struct Candidate {
            let format: AVCaptureDevice.Format
            let width: Int32
            let height: Int32
            let maxFPS: Float64
        }

        let candidates: [Candidate] = allFormats.compactMap { format in
            let dims = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            let maxFPS = format.videoSupportedFrameRateRanges
                .map(\.maxFrameRate)
                .max() ?? 0
            guard dims.width > 0, maxFPS > 0 else { return nil }
            return Candidate(format: format, width: dims.width, height: dims.height, maxFPS: maxFPS)
        }

        let pick: Candidate?
        let fpsCap: Float64

        if highBandwidthMode {
            // USB4/Thunderbolt direct connection — no bandwidth bottleneck.
            // Prefer highest resolution at 60fps, then 30fps.
            let uhd4k_60 = candidates
                .filter { $0.height >= 2160 && $0.maxFPS >= 60 }
                .max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }
            let uhd4k_30 = candidates
                .filter { $0.height >= 2160 && $0.maxFPS >= 30 }
                .max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }
            let hd1080_60 = candidates
                .filter { $0.height == 1080 && $0.maxFPS >= 60 }
                .min { abs($0.maxFPS - 60) < abs($1.maxFPS - 60) }
            let hd1080_30 = candidates
                .filter { $0.height == 1080 && $0.maxFPS >= 30 }
                .min { abs($0.maxFPS - 30) < abs($1.maxFPS - 30) }
            let fallback = candidates.max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }

            pick = uhd4k_60 ?? uhd4k_30 ?? hd1080_60 ?? hd1080_30 ?? fallback
            fpsCap = 60
            log("HIGH BANDWIDTH MODE: selecting best available format")
        } else {
            // USB 2.0 hub — cap at 1080p@30fps to avoid XPC pipe failures.
            let hd1080_30 = candidates
                .filter { $0.height == 1080 && $0.maxFPS >= 30 }
                .min { abs($0.maxFPS - 30) < abs($1.maxFPS - 30) }
            let hd1080_any = candidates
                .filter { $0.height == 1080 }
                .min { $0.maxFPS < $1.maxFPS }
            let hd720_30 = candidates
                .filter { $0.height == 720 && $0.maxFPS >= 30 }
                .min { abs($0.maxFPS - 30) < abs($1.maxFPS - 30) }
            let subHD = candidates
                .filter { $0.height <= 1080 && $0.maxFPS >= 15 }
                .max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }
            let fallback = candidates.max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }

            pick = hd1080_30 ?? hd1080_any ?? hd720_30 ?? subHD ?? fallback
            fpsCap = 30
        }

        guard let pick else {
            log("NO usable format found")
            return
        }

        camera.activeFormat = pick.format

        let targetFPS = min(pick.maxFPS, fpsCap)
        camera.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CMTimeScale(targetFPS))
        camera.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CMTimeScale(targetFPS))

        log("LOCKED: \(pick.width)x\(pick.height) @ \(Int(targetFPS))fps\(highBandwidthMode ? " [HIGH BW]" : "")")
    }

    // MARK: - Orientation

    private func startOrientationObserver() {
        UIDevice.current.beginGeneratingDeviceOrientationNotifications()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(orientationChanged),
            name: UIDevice.orientationDidChangeNotification,
            object: nil
        )
    }

    @objc private func orientationChanged() {
        guard !isUsingExternalCamera else { return }
        updateOrientationFromDevice()
    }

    private func updateOrientationFromDevice() {
        let deviceOrientation = UIDevice.current.orientation
        switch deviceOrientation {
        case .portrait:            cachedOrientation = .right
        case .portraitUpsideDown:  cachedOrientation = .left
        case .landscapeLeft:       cachedOrientation = .up
        case .landscapeRight:      cachedOrientation = .down
        default: break
        }
    }

    private var externalCameraOrientation: CGImagePropertyOrientation {
        let degrees = UserDefaults.standard.integer(forKey: "AppSettings.externalCameraRotation")
        switch degrees {
        case 90:  return .right
        case 180: return .down
        case 270: return .left
        default:  return .up
        }
    }
}

extension CameraService: AVCaptureVideoDataOutputSampleBufferDelegate {

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard !outputSuppressed else { return }

        latestSampleBuffer = sampleBuffer
        lastFrameTime = Date()

        // One-shot mode: only capture the buffer, skip all OCR processing.
        guard !oneShotCapture else { return }

        frameCount += 1

        // Track FPS via rolling 1-second window
        let now = CACurrentMediaTime()
        metricsAccumulator.framesReceived += 1
        metricsFrameTimestamps.append(now)
        let cutoff = now - 1.0
        metricsFrameTimestamps.removeAll { $0 < cutoff }
        let currentFPS = Double(metricsFrameTimestamps.count)

        if frameCount % 15 == 0 {
            var snapshot = metricsAccumulator
            snapshot.actualFPS = currentFPS
            snapshot.resolution = activeResolution
            if let fps = Int(activeFPS.replacingOccurrences(of: "fps", with: "")) {
                snapshot.configuredFPS = fps
            }
            DispatchQueue.main.async { [weak self] in
                self?.liveMetrics = snapshot
            }
        }

        // Sharpness + brightness check runs early for external cameras so blurry
        // frames never consume a processing slot. Computed every 4th raw frame.
        if isUsingExternalCamera && frameCount % 4 == 0,
           let buf = CMSampleBufferGetImageBuffer(sampleBuffer) {
            let score = laplacianVariance(buf)
            if focusMeterEnabled {
                DispatchQueue.main.async { [weak self] in
                    guard let self else { return }
                    self.focusScore = score
                    if score > self.focusPeak { self.focusPeak = score }
                }
            }
            lastFrameSharpness = score
            lastFrameBrightness = sampleMeanBrightness(buf)
        }

        // Gate on sharpness before frameSkip to avoid wasting OCR slots on blur
        if isUsingExternalCamera && lastFrameSharpness < adaptiveSharpnessThreshold {
            metricsAccumulator.framesSkipped += 1
            return
        }

        guard frameCount % UInt64(frameSkip) == 0 else {
            metricsAccumulator.framesSkipped += 1
            return
        }
        guard !isProcessing else {
            metricsAccumulator.framesSkipped += 1
            return
        }

        // Track sharpness of frames that pass all gates for adaptive threshold
        if isUsingExternalCamera {
            recentSharpnessValues.append(lastFrameSharpness)
            if recentSharpnessValues.count > sharpnessHistorySize {
                recentSharpnessValues.removeFirst()
            }
        }

        // Scene-change detection: skip unchanged frames unless in burst or
        // rectangle-detected mode (something new entering the view).
        if isUsingExternalCamera && Date() >= burstUntil && !rectangleDetectedHint,
           let buf = CMSampleBufferGetImageBuffer(sampleBuffer) {
            let fp = sceneFingerprint(buf)
            if !lastProcessedFingerprint.isEmpty {
                let delta = fingerprintDelta(fp, lastProcessedFingerprint)
                if delta < sceneChangeThreshold {
                    metricsAccumulator.framesSkipped += 1
                    return
                }
            }
            lastProcessedFingerprint = fp
        }

        isProcessing = true
        let effectiveOrientation: CGImagePropertyOrientation = isUsingExternalCamera ? externalCameraOrientation : cachedOrientation
        delegate?.cameraService(self, didOutput: sampleBuffer, orientation: effectiveOrientation)
    }

    /// Fast mean brightness estimate from a sparse grid sample (0.0-1.0).
    private func sampleMeanBrightness(_ pixelBuffer: CVPixelBuffer) -> Double {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return 0.5 }
        let ptr = base.assumingMemoryBound(to: UInt8.self)

        let gridSize = 6
        let stepX = width / gridSize
        let stepY = height / gridSize
        var total: Double = 0, count: Double = 0
        for row in 0..<gridSize {
            for col in 0..<gridSize {
                let x = col * stepX + stepX / 2
                let y = row * stepY + stepY / 2
                total += Double(ptr[y * bytesPerRow + x * 4 + 1])
                count += 1
            }
        }
        return count > 0 ? total / count / 255.0 : 0.5
    }

    /// Cheap scene fingerprint: sample a sparse grid of green-channel pixel values.
    /// Comparing two fingerprints tells us how much the scene has changed.
    private func sceneFingerprint(_ pixelBuffer: CVPixelBuffer) -> [UInt8] {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return [] }
        let ptr = base.assumingMemoryBound(to: UInt8.self)

        let gridSize = 8
        let stepX = width / gridSize
        let stepY = height / gridSize
        var fingerprint = [UInt8](repeating: 0, count: gridSize * gridSize)
        for row in 0..<gridSize {
            for col in 0..<gridSize {
                let x = col * stepX + stepX / 2
                let y = row * stepY + stepY / 2
                fingerprint[row * gridSize + col] = ptr[y * bytesPerRow + x * 4 + 1]
            }
        }
        return fingerprint
    }

    /// Normalized mean absolute difference between two fingerprints (0.0 = identical, 1.0 = max change).
    private func fingerprintDelta(_ a: [UInt8], _ b: [UInt8]) -> Double {
        guard a.count == b.count, !a.isEmpty else { return 1.0 }
        var total: Int = 0
        for i in 0..<a.count {
            total += abs(Int(a[i]) - Int(b[i]))
        }
        return Double(total) / Double(a.count) / 255.0
    }

    /// Laplacian variance: high = sharp, low = blurry.
    /// Computed on a small center crop in grayscale for speed.
    private func laplacianVariance(_ pixelBuffer: CVPixelBuffer) -> Double {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return 0 }

        let ptr = base.assumingMemoryBound(to: UInt8.self)

        // Sample a center crop (1/4 of frame) with 4x step for speed
        let cropX = width / 4
        let cropY = height / 4
        let cropW = width / 2
        let cropH = height / 2
        let step = 4

        var sum: Double = 0
        var sumSq: Double = 0
        var count: Double = 0

        // Laplacian kernel: center=4, neighbors=-1 in cross pattern
        var y = cropY + step
        while y < cropY + cropH - step {
            var x = cropX + step
            while x < cropX + cropW - step {
                // BGRA format: use green channel (index 1) as luminance proxy
                let idx = y * bytesPerRow + x * 4 + 1
                let c = Double(ptr[idx])
                let t = Double(ptr[(y - step) * bytesPerRow + x * 4 + 1])
                let b = Double(ptr[(y + step) * bytesPerRow + x * 4 + 1])
                let l = Double(ptr[y * bytesPerRow + (x - step) * 4 + 1])
                let r = Double(ptr[y * bytesPerRow + (x + step) * 4 + 1])

                let lap = 4.0 * c - t - b - l - r
                sum += lap
                sumSq += lap * lap
                count += 1
                x += step
            }
            y += step
        }

        guard count > 0 else { return 0 }
        let mean = sum / count
        return (sumSq / count) - (mean * mean)
    }
}
