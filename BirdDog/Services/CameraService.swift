import AVFoundation
import UIKit

protocol CameraServiceDelegate: AnyObject {
    func cameraService(_ service: CameraService, didOutput sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation)
}

enum CameraStatus: String {
    case externalActive = "EXT"
    case searchingExternal = "Searching..."
    case builtIn = "Built-in"
}

final class CameraService: NSObject, ObservableObject {

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
    var focusMeterEnabled = false
    private var currentDevice: AVCaptureDevice?
    private var currentInput: AVCaptureDeviceInput?
    private var videoOutput: AVCaptureVideoDataOutput?
    private var systemPreferredObservation: Any?
    private var discoveryObservation: NSKeyValueObservation?
    private var discoverySession: AVCaptureDevice.DiscoverySession?
    private var hasSetInitialPreference = false
    private var pollTimer: Timer?
    private let sharpnessThreshold: Double = 50.0
    private var lastFrameSharpness: Double = 999

    func start() {
        if !isRunning {
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
            self.configureSession()
            self.session.startRunning()
            self.isRunning = true

            // USB cameras through hubs often enumerate slowly after an app
            // install. If we didn't find an external camera on the first try,
            // wait briefly and retry once before falling back to polling.
            if !self.isUsingExternalCamera {
                self.log("No external camera on first pass — retrying in 1.5s")
                Thread.sleep(forTimeInterval: 1.5)
                if let ext = self.findExternalCamera() {
                    self.log("Found external on retry: \(ext.localizedName)")
                    self.switchToCamera(ext)
                }
            }

            self.startPollingIfNeeded()
        }
    }

    func stop() {
        stopPolling()
        sessionQueue.async { [weak self] in
            guard let self, self.isRunning else { return }
            self.session.stopRunning()
            self.isRunning = false
        }
    }

    // MARK: - Violation Photo Capture

    private var latestSampleBuffer: CMSampleBuffer?

    func captureViolationPhoto() -> String? {
        guard let buffer = latestSampleBuffer,
              let imageBuffer = CMSampleBufferGetImageBuffer(buffer) else { return nil }

        let ciImage = CIImage(cvPixelBuffer: imageBuffer)
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return nil }

        let uiImage = UIImage(cgImage: cgImage, scale: 1.0, orientation: .right)
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
            self.session.stopRunning()

            self.session.beginConfiguration()
            for input in self.session.inputs { self.session.removeInput(input) }
            for output in self.session.outputs { self.session.removeOutput(output) }
            self.session.commitConfiguration()

            self.currentInput = nil
            self.currentDevice = nil
            self.videoOutput = nil
            self.isUsingExternalCamera = false

            // USB devices through hubs need time to re-enumerate after
            // the session releases them. Retry up to 3 times with increasing delays.
            var connected = false
            for attempt in 1...3 {
                let delay = TimeInterval(attempt)
                self.log("RECONNECT: waiting \(Int(delay))s before attempt \(attempt)...")
                Thread.sleep(forTimeInterval: delay)

                self.configureSession()

                if self.isUsingExternalCamera {
                    self.log("RECONNECT: external camera acquired on attempt \(attempt)")
                    connected = true
                    break
                } else {
                    self.log("RECONNECT: attempt \(attempt) — no external camera, will retry")
                    // Tear down again for a clean retry
                    self.session.beginConfiguration()
                    for input in self.session.inputs { self.session.removeInput(input) }
                    for output in self.session.outputs { self.session.removeOutput(output) }
                    self.session.commitConfiguration()
                    self.currentInput = nil
                    self.currentDevice = nil
                    self.videoOutput = nil
                }
            }

            if !connected {
                self.log("RECONNECT: all attempts failed, falling back to built-in")
                self.configureSession()
            }

            self.session.startRunning()
            self.isRunning = true
            self.isReconnecting = false
            self.startPollingIfNeeded()
        }
    }

    private var burstUntil: Date = .distantPast

    func markProcessingComplete(elapsed: TimeInterval) {
        isProcessing = false

        if Date() < burstUntil {
            frameSkip = 1
            return
        }

        // External cameras (especially global shutter) produce clean frames
        // at high FPS — allow processing every other frame (minSkip 1 at 60fps
        // = 30 processed fps). Built-in stays more conservative.
        let maxSkip = isUsingExternalCamera ? 6 : 8
        let minSkip = isUsingExternalCamera ? 1 : 2

        if elapsed > 0.20 {
            frameSkip = min(frameSkip + 1, maxSkip)
        } else if elapsed < 0.10, frameSkip > minSkip {
            frameSkip -= 1
        }
    }

    /// Temporarily drop to frameSkip=1 for a short burst to capture more
    /// frames of a plate that just appeared.
    func triggerBurst(duration: TimeInterval = 0.5) {
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
            self.pollTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
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
    private var pollIteration = 0

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
                self.log("POLL: found \(external.localizedName) — attempting switch")

                Thread.sleep(forTimeInterval: 0.5)
                self.switchToCamera(external)

                if self.isUsingExternalCamera {
                    self.log("POLL: switch succeeded")
                    self.stopPolling()
                } else {
                    self.log("POLL: switch failed, queuing full reconnect")
                    self.isReconnecting = true
                    DispatchQueue.main.async { [weak self] in
                        self?.forceReconnect()
                    }
                }
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
        log("SESSION INTERRUPTION ENDED — checking for external camera")
        sessionQueue.async { [weak self] in
            guard let self else { return }
            if let external = self.findExternalCamera() {
                self.switchToCamera(external)
            }
            self.startPollingIfNeeded()
        }
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
            guard let newCamera = AVCaptureDevice.systemPreferredCamera else { return }
            self.sessionQueue.async {
                self.switchToCamera(newCamera)
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
            let devices = session.devices
            let external = devices.first(where: { $0.deviceType == .external })
            let best = external ?? devices.first(where: { $0.position == .back }) ?? devices.first

            if let best {
                AVCaptureDevice.userPreferredCamera = best
                self.sessionQueue.async {
                    self.switchToCamera(best)
                }
            }
            self.log("DEVICES CHANGED: \(devices.map { "\($0.localizedName) (\($0.deviceType == .external ? "EXTERNAL" : "built-in"))" }.joined(separator: ", "))")
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
                cachedOrientation = .up
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
            if isExternal { stopPolling() }
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
            cachedOrientation = .up
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

    private func log(_ message: String) {
        let ts = ISO8601DateFormatter().string(from: Date())
        let line = "[\(ts)] \(message)"
        print("CameraService: \(message)")

        let logLine = line + "\n"
        if let data = logLine.data(using: .utf8) {
            if let fh = try? FileHandle(forWritingTo: Self.logFileURL) {
                fh.seekToEndOfFile()
                fh.write(data)
                fh.closeFile()
            } else {
                try? data.write(to: Self.logFileURL, options: .atomic)
            }
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

            // Manual-focus lens: lock focus if the camera reports it supports
            // locked mode. This stops AVFoundation from hunting on a fixed lens.
            if camera.isFocusModeSupported(.locked) {
                camera.focusMode = .locked
                log("focus mode: locked (manual focus lens)")
            }

            let bias = max(camera.minExposureTargetBias, min(exposureBias, camera.maxExposureTargetBias))
            camera.setExposureTargetBias(bias, completionHandler: nil)
            log("exposure bias: \(bias) (range \(camera.minExposureTargetBias)…\(camera.maxExposureTargetBias))")

            if camera.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                camera.whiteBalanceMode = .continuousAutoWhiteBalance
            }
        }

        camera.unlockForConfiguration()
    }

    private func applyExposureBias() {
        sessionQueue.async { [weak self] in
            guard let self, let camera = self.currentDevice, self.isUsingExternalCamera else { return }
            try? camera.lockForConfiguration()
            let clamped = max(camera.minExposureTargetBias, min(self.exposureBias, camera.maxExposureTargetBias))
            camera.setExposureTargetBias(clamped, completionHandler: nil)
            camera.unlockForConfiguration()
            self.log("exposure bias → \(clamped)")
        }
    }

    private func selectBestExternalFormat(for camera: AVCaptureDevice) {
        let allFormats = camera.formats
        log("external camera: \(allFormats.count) formats total")

        // Log every format so we can see exactly what the camera offers
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

        // Priority 1: 4K at 24+ fps — more pixels = better OCR at distance
        let uhd4k = candidates.filter { $0.height >= 2160 && $0.maxFPS >= 24 }
            .max { $0.maxFPS < $1.maxFPS }
        // Priority 2: 1080p at highest fps
        let hd1080_best = candidates.filter { $0.height == 1080 }.max { $0.maxFPS < $1.maxFPS }
        // Priority 3: 720p at high fps (e-con does 120fps at 720p)
        let hd720_fast = candidates.filter { $0.height == 720 && $0.maxFPS >= 60 }.max { $0.maxFPS < $1.maxFPS }
        // Priority 4: highest resolution that can do 24+ fps
        let highRes = candidates.filter { $0.maxFPS >= 24 }
            .max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }
        // Priority 5: whatever has the most pixels
        let fallback = candidates.max { Int($0.width) * Int($0.height) < Int($1.width) * Int($1.height) }

        let pick = uhd4k ?? hd1080_best ?? hd720_fast ?? highRes ?? fallback

        guard let pick else {
            log("NO usable format found")
            return
        }

        camera.activeFormat = pick.format

        // Cap at 60fps — higher than that burns USB bandwidth for marginal gain
        // since Vision OCR can't keep up with 120fps anyway.
        let targetFPS = min(pick.maxFPS, 60)
        camera.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CMTimeScale(targetFPS))
        camera.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CMTimeScale(targetFPS))

        log("LOCKED: \(pick.width)x\(pick.height) @ \(Int(targetFPS))fps")
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
}

extension CameraService: AVCaptureVideoDataOutputSampleBufferDelegate {

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        latestSampleBuffer = sampleBuffer
        frameCount += 1

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
        }

        guard frameCount % UInt64(frameSkip) == 0 else { return }
        guard !isProcessing else { return }

        if isUsingExternalCamera && lastFrameSharpness < sharpnessThreshold {
            return
        }

        isProcessing = true
        delegate?.cameraService(self, didOutput: sampleBuffer, orientation: cachedOrientation)
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
