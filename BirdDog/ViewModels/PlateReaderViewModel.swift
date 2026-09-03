import Foundation
import UIKit
import AVFoundation
import AudioToolbox

extension Notification.Name {
    static let ocrEngineChanged = Notification.Name("ocrEngineChanged")
}

@MainActor
final class PlateReaderViewModel: ObservableObject {

    @Published var currentPlates: [RecognizedPlate] = []
    @Published var scanLog: [ScannedPlate] = []
    @Published var isScanning = false
    @Published private(set) var isScanningPaused = false
    @Published var cameraPermission: AVAuthorizationStatus = .notDetermined
    @Published var latestAuthStatus: PlateStatus = .unchecked
    @Published var audioAlertsEnabled = true
    @Published var activeSession: ScanSession?
    @Published var sessionHistory: [ScanSession] = []

    var uniquePlateCount: Int {
        Set(scanLog.map(\.text)).count
    }

    var authorizedCount: Int {
        scanLog.filter { if case .authorized = $0.authStatus { return true }; return false }.count
    }

    var wrongLotCount: Int {
        scanLog.filter { if case .wrongLot = $0.authStatus { return true }; return false }.count
    }

    var expiredCount: Int {
        scanLog.filter { if case .expired = $0.authStatus { return true }; return false }.count
    }

    var unknownCount: Int {
        scanLog.filter { if case .unknown = $0.authStatus { return true }; return false }.count
    }

    var sessionStats: (count: Int, avgLatency: Double, platesPerMin: Double) {
        guard !scanLog.isEmpty else { return (0, 0, 0) }
        let latencies = scanLog.map(\.detectionLatency)
        let avg = latencies.reduce(0, +) / Double(latencies.count)
        let sorted = scanLog.sorted { $0.timestamp < $1.timestamp }
        if let first = sorted.first, let last = sorted.last {
            let mins = last.timestamp.timeIntervalSince(first.timestamp) / 60.0
            let rate = mins > 0.1 ? Double(scanLog.count) / mins : Double(scanLog.count)
            return (scanLog.count, avg, rate)
        }
        return (scanLog.count, avg, Double(scanLog.count))
    }

    private(set) var diagnosticLog: [DiagnosticEntry] = []

    let sessionStartTime = Date()

    let cameraService = CameraService()
    let geofenceService = GeofenceService.shared
    private let authService = PlateAuthService()
    private let sessionManager = SessionHistoryManager.shared
    private let motionService = MotionSpeedService.shared

    nonisolated(unsafe) private let recognitionService = PlateRecognitionService()
    nonisolated(unsafe) private var cloudService: PlateRecognizerService?
    private let hapticMedium = UIImpactFeedbackGenerator(style: .medium)
    private let hapticHeavy = UIImpactFeedbackGenerator(style: .heavy)
    private let hapticLight = UIImpactFeedbackGenerator(style: .light)
    private(set) var ticketedPlates: [String: String] = [:]
    private var seenPlates: [(text: String, time: Date)] = []
    private let confirmationThreshold = 2
    private let dedupWindow: TimeInterval = 30
    private var candidateCounts: [String: (count: Int, bestConfidence: Float)] = [:]
    private var candidateFirstSeen: [String: Date] = [:]
    private let candidateVoter = CandidateVoter()
    private var regionLastSeen: [String: Date] = [:]

    private var alertPlayer: AVAudioPlayer?
    private var currentDayStart: Date = Calendar.current.startOfDay(for: Date())

    private var engineObserver: Any?

    private static var scanLogURL: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .appendingPathComponent("active_scan_log.json")
    }

    init() {
        cameraService.delegate = self
        cameraService.highBandwidthMode = AppSettings.shared.highBandwidthMode
        engineObserver = NotificationCenter.default.addObserver(
            forName: .ocrEngineChanged, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.updateCloudService()
            }
        }
        Task { @MainActor [weak self] in
            self?.configureAudioSession()
            self?.hapticMedium.prepare()
            self?.hapticHeavy.prepare()
            self?.hapticLight.prepare()
            self?.updateCloudService()
            self?.loadPersistedScanLog()
            self?.reloadHistory()
        }
    }

    private func configureAudioSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: .mixWithOthers)
            try session.setActive(true)
        } catch {
            print("Audio session setup failed: \(error)")
        }
    }

    func checkPermissionAndStart() {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        cameraPermission = status

        switch status {
        case .authorized:
            startScanning()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                Task { @MainActor in
                    self?.cameraPermission = granted ? .authorized : .denied
                    if granted { self?.startScanning() }
                }
            }
        default:
            break
        }
    }

    func startScanning() {
        if activeSession == nil {
            let cam = cameraService.activeCameraName
            let df = DateFormatter()
            df.dateFormat = "h:mma"
            let label = cam.isEmpty || cam == "None" ? "Scan \(df.string(from: Date()))" : "\(cam) \(df.string(from: Date()))"
            let session = ScanSession(label: label)
            activeSession = session
        }
        authService.clearCache()
        if PlateDatabase.isReady {
            PlateDatabase.shared.warmLengthCache()
        }
        cameraService.start()
        motionService.start()
        isScanning = true
    }

    func stopScanning() {
        cameraService.stop()
        motionService.stop()
        isScanning = false
        isScanningPaused = false
        finalizeSession()
    }

    func pauseScanning() {
        guard isScanning, !isScanningPaused else { return }
        cameraService.outputSuppressed = true
        cameraService.stop()
        isScanningPaused = true
    }

    func resumeScanning() {
        guard isScanningPaused else { return }
        isScanningPaused = false
        cameraService.outputSuppressed = false
        cameraService.start()
    }

    private func finalizeSession() {
        guard var session = activeSession else { return }
        session.endTime = Date()
        session.plates = scanLog
        session.diagnostics = diagnosticLog

        let metrics = cameraService.snapshotAndResetMetrics()
        session.deviceModel = DeviceInfo.modelName
        session.deviceChip = DeviceInfo.chipName
        session.deviceIdentifier = DeviceInfo.modelIdentifier
        session.connectionType = cameraService.isUsingExternalCamera ? "External (USB)" : "Built-in"
        session.cameraResolution = metrics.resolution
        session.cameraFPS = metrics.configuredFPS
        session.avgActualFPS = metrics.actualFPS
        session.avgOCRTimeMs = metrics.avgOCRTimeMs
        session.peakOCRTimeMs = metrics.peakOCRTimeMs
        session.framesProcessed = metrics.framesProcessed
        session.framesSkipped = metrics.framesSkipped
        session.pixelThroughput = metrics.pixelThroughput
        session.cameraHardware = cameraService.activeCameraName

        sessionManager.save(session)
        activeSession = nil
        reloadHistory()
    }

    func clearLog() {
        scanLog.removeAll()
        seenPlates.removeAll()
        candidateCounts.removeAll()
        candidateVoter.removeAll()
        diagnosticLog.removeAll()
        ticketedPlates.removeAll()
        currentPlates = []
        latestAuthStatus = .unchecked
        deletePersistedScanLog()
    }

    func markPlateTicketed(_ plate: String, lot: String? = nil) {
        let normalized = plate.uppercased().trimmingCharacters(in: .whitespaces)
        let ticketLot = lot ?? geofenceService.currentLotName ?? ""
        ticketedPlates[normalized] = ticketLot

        for i in scanLog.indices where scanLog[i].text.uppercased() == normalized {
            let old = scanLog[i]
            scanLog[i] = ScannedPlate(
                text: old.text,
                timestamp: old.timestamp,
                confidence: old.confidence,
                framesConfirmed: old.framesConfirmed,
                authStatus: .ticketed,
                matchMethod: old.matchMethod,
                matchedPlate: old.matchedPlate,
                cameraName: old.cameraName,
                detectionLatency: old.detectionLatency,
                violationPhotoPath: old.violationPhotoPath,
                ticketedInLot: ticketLot
            )
        }

        persistScanLog()
    }

    func startNewSession() {
        finalizeSession()
        clearLog()
    }

    func endSessionIfActive() {
        finalizeSession()
    }

    func reloadHistory() {
        sessionHistory = sessionManager.loadAll()
    }

    func deleteSession(_ session: ScanSession) {
        sessionManager.delete(session)
        reloadHistory()
    }

    func deleteAllSessions() {
        sessionManager.deleteAll()
        reloadHistory()
    }

    private func pruneExpiredSeenPlates() {
        let activeDedupWindow = motionService.dedupWindow
        let cutoff = Date().addingTimeInterval(-activeDedupWindow)
        seenPlates.removeAll { $0.time < cutoff }
        regionLastSeen = regionLastSeen.filter { $0.value > cutoff }
    }

    private func handleResult(_ result: RecognitionResult) {
        currentPlates = result.plates
        diagnosticLog.append(contentsOf: result.diagnostics)

        // Feed rectangle-detection hint back to camera for scene-change bypass
        cameraService.rectangleDetectedHint = result.rectangleDetected

        // Predictive burst: rectangle detected but no plates read yet means a
        // plate is approaching readability. Pre-burst to capture more frames.
        if result.rectangleDetected && result.plates.isEmpty && cameraService.isUsingExternalCamera {
            cameraService.triggerBurst(duration: 0.8)
        }

        // Update camera frame skip floor based on current motion state
        cameraService.motionMinFrameSkip = motionService.frameSkipFloor

        let now = Date()
        let todayStart = Calendar.current.startOfDay(for: now)
        if todayStart > currentDayStart {
            currentDayStart = todayStart
            startNewSession()
        }

        pruneExpiredSeenPlates()
        candidateVoter.pruneExpired()

        let isExternal = cameraService.isUsingExternalCamera

        for plate in result.plates {
            let voterKey = findVoterKey(for: plate.text) ?? plate.text
            guard !isFuzzyDuplicate(voterKey) else { continue }

            // Region-based suppression: when stationary/walking, don't re-process
            // the same physical area of the frame within the cooldown period.
            let regionKey = regionKeyForBoundingBox(plate.boundingBox)
            if let lastTime = regionLastSeen[regionKey],
               Date().timeIntervalSince(lastTime) < motionService.regionCooldown {
                continue
            }

            candidateVoter.record(
                key: voterKey,
                ballot: CandidateVoter.Ballot(
                    primary: plate.text,
                    alternates: plate.alternates,
                    confidence: plate.confidence
                )
            )

            if candidateFirstSeen[voterKey] == nil {
                candidateFirstSeen[voterKey] = now
            }

            let existing = candidateCounts[voterKey]
            let newCount = (existing?.count ?? 0) + 1
            let bestConf = max(existing?.bestConfidence ?? 0, plate.confidence)
            candidateCounts[voterKey] = (newCount, bestConf)

            var threshold: Int
            if PlatePatternMatcher.isLocalFormat(voterKey) {
                threshold = 1
            } else {
                let motionThreshold = motionService.confirmationThreshold
                threshold = isExternal ? 2 : motionThreshold
            }

            if newCount == 1 && isExternal {
                cameraService.triggerBurst()
            }

            // Single-frame instant confirm for external camera:
            // high confidence + known NA format = reliable enough for 1-frame.
            // Guard 1: don't instant-confirm when the read differs in length
            // from the voter key (merged with longer/shorter variant).
            // Guard 2: don't instant-confirm 6-char reads that could be a
            // clipped 7-char local plate (leading char dropped by OCR).
            let lengthMismatch = plate.text.count != voterKey.count
            let couldBeClipped = plate.text.count == 6
                && !PlatePatternMatcher.isLocalFormat(plate.text)
                && PlatePatternMatcher.couldBeClippedLocalPlate(plate.text)

            if newCount == 1 && isExternal && plate.confidence >= 0.90
                && PlatePatternMatcher.matchesAnyNAFormat(voterKey)
                && !PlatePatternMatcher.isVanityPlate(voterKey)
                && !lengthMismatch
                && !couldBeClipped {
                threshold = 1
            }

            // Single-frame instant confirm: high-confidence exact or fuzzy DB match.
            // Uses quickCheck (exact+fuzzy only) to avoid expensive smartLookup on main thread.
            if newCount == 1 && plate.confidence >= 0.85 && !PlatePatternMatcher.isVanityPlate(voterKey) {
                let dbHit = authService.quickCheck(plate: voterKey, currentLot: nil)
                if dbHit.matchMethod == .exact || dbHit.matchMethod == .fuzzy {
                    threshold = 1
                }
            }

            // Parallel alternate verification: while accumulating frames,
            // pre-check alternates against the DB and boost the voter if any
            // alternate is an exact hit. This accelerates convergence.
            // Uses quickCheck to avoid blocking main thread with smartLookup.
            if newCount < threshold && isExternal {
                for alt in plate.alternates {
                    let altHit = authService.quickCheck(plate: alt, currentLot: nil)
                    if altHit.matchMethod == .exact {
                        candidateVoter.record(
                            key: voterKey,
                            ballot: CandidateVoter.Ballot(
                                primary: alt,
                                alternates: [],
                                confidence: plate.confidence + 0.1
                            )
                        )
                        break
                    }
                }
            }

            guard newCount >= threshold else { continue }

            var consensusText = candidateVoter.consensus(for: voterKey) ?? voterKey

            // For external cameras with potential focus issues, check if any
            // alternate reading is an exact DB hit when the consensus isn't.
            // Uses quickCheck for the fast speculative pass to avoid main thread blocking.
            if isExternal {
                let consensusHit = authService.quickCheck(plate: consensusText, currentLot: nil)
                if consensusHit.matchMethod != .exact {
                    let allAlts = plate.alternates + [plate.text]
                    for alt in allAlts where alt != consensusText {
                        let altHit = authService.quickCheck(plate: alt, currentLot: nil)
                        if altHit.matchMethod == .exact {
                            consensusText = alt
                            break
                        }
                    }
                }
            }

            seenPlates.append((text: consensusText, time: now))
            regionLastSeen[regionKey] = now
            let frames = newCount

            let firstSeen = candidateFirstSeen[voterKey] ?? now
            let latency = now.timeIntervalSince(firstSeen)

            candidateCounts.removeAll()
            candidateVoter.removeAll()
            candidateFirstSeen.removeAll()

            let authResult = authService.checkDetailed(plate: consensusText, currentLot: geofenceService.currentLotName)

            let normalizedPlate = consensusText.uppercased().trimmingCharacters(in: .whitespaces)
            let currentLotName = geofenceService.currentLotName ?? ""
            let isTicketedHere: Bool
            if let ticketedLot = ticketedPlates[normalizedPlate] {
                // Only show as ticketed if same lot (or either lot is unknown)
                isTicketedHere = ticketedLot.isEmpty || currentLotName.isEmpty || ticketedLot == currentLotName
            } else {
                isTicketedHere = false
            }
            let effectiveStatus = isTicketedHere ? .ticketed : authResult.status
            latestAuthStatus = effectiveStatus

            if authResult.matchedPlate != consensusText {
                seenPlates.append((text: authResult.matchedPlate, time: now))
            }

            let camName = cameraService.activeCameraName

            scanLog.insert(
                ScannedPlate(
                    text: consensusText,
                    timestamp: now,
                    confidence: bestConf,
                    framesConfirmed: frames,
                    authStatus: effectiveStatus,
                    matchMethod: authResult.matchMethod,
                    matchedPlate: authResult.matchedPlate,
                    cameraName: camName,
                    detectionLatency: latency
                ),
                at: 0
            )

            triggerFeedback(for: authResult.status)
            persistScanLog()
        }
    }

    /// Find an existing voter key that fuzzy-matches the given text,
    /// so multiple frame observations of the same plate merge into one ballot group.
    private func findVoterKey(for text: String) -> String? {
        for key in candidateCounts.keys {
            if isCandidateMerge(text, key) { return key }
        }
        return nil
    }

    private func triggerFeedback(for status: PlateStatus) {
        switch status {
        case .authorized:
            hapticLight.impactOccurred()
            hapticLight.prepare()
        case .wrongLot:
            hapticHeavy.impactOccurred(intensity: 0.8)
            hapticHeavy.prepare()
            if audioAlertsEnabled {
                playWrongLotTone()
            }
        case .expired:
            hapticMedium.impactOccurred()
            hapticMedium.prepare()
            if audioAlertsEnabled {
                playTone(frequency: 880, duration: 0.15)
            }
        case .unknown:
            hapticHeavy.impactOccurred(intensity: 1.0)
            hapticHeavy.prepare()
            if audioAlertsEnabled {
                playAlertTone()
            }
        case .unchecked:
            hapticMedium.impactOccurred()
            hapticMedium.prepare()
        case .ticketed:
            hapticLight.impactOccurred()
            hapticLight.prepare()
        }
    }

    private func playWrongLotTone() {
        playTone(frequency: 660, duration: 0.15)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { [weak self] in
            self?.playTone(frequency: 880, duration: 0.2)
        }
    }

    private func playAlertTone() {
        playTone(frequency: 1200, duration: 0.12)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            self?.playTone(frequency: 1200, duration: 0.12)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.30) { [weak self] in
            self?.playTone(frequency: 1500, duration: 0.2)
        }
    }

    private func playTone(frequency: Double, duration: Double) {
        let sampleRate: Double = 44100
        let samples = Int(sampleRate * duration)
        var data = Data()

        for i in 0..<samples {
            let t = Double(i) / sampleRate
            let envelope = min(1.0, min(t / 0.005, (duration - t) / 0.005))
            let sample = Int16(envelope * 0.6 * Double(Int16.max) * sin(2.0 * .pi * frequency * t))
            var s = sample.littleEndian
            data.append(Data(bytes: &s, count: 2))
        }

        let headerSize: UInt32 = 44
        let dataSize = UInt32(data.count)
        var wav = Data()

        func append(_ value: UInt32) { var v = value.littleEndian; wav.append(Data(bytes: &v, count: 4)) }
        func append16(_ value: UInt16) { var v = value.littleEndian; wav.append(Data(bytes: &v, count: 2)) }

        wav.append("RIFF".data(using: .ascii)!)
        append(headerSize + dataSize - 8)
        wav.append("WAVE".data(using: .ascii)!)
        wav.append("fmt ".data(using: .ascii)!)
        append(16)
        append16(1)
        append16(1)
        append(UInt32(sampleRate))
        append(UInt32(sampleRate) * 2)
        append16(2)
        append16(16)
        wav.append("data".data(using: .ascii)!)
        append(dataSize)
        wav.append(data)

        alertPlayer = try? AVAudioPlayer(data: wav)
        alertPlayer?.play()
    }

    private func isFuzzyDuplicate(_ text: String) -> Bool {
        let now = Date()
        for seen in seenPlates {
            // Use stricter match for older reads, looser for very recent ones
            let age = now.timeIntervalSince(seen.time)
            if age < 5.0 {
                if isFuzzyMatchRecent(text, seen.text) { return true }
            } else {
                if isFuzzyMatch(text, seen.text) { return true }
            }
        }
        for key in candidateCounts.keys where key != text {
            if isCandidateMerge(text, key) {
                let existing = candidateCounts.removeValue(forKey: key)!
                let merged = candidateCounts[text] ?? (count: 0, bestConfidence: 0)
                candidateCounts[text] = (
                    count: merged.count + existing.count,
                    bestConfidence: max(merged.bestConfidence, existing.bestConfidence)
                )
            }
        }
        return false
    }

    /// Dedup against already-logged plates.
    /// Catches same plate with OCR errors (dropped/added chars, substitutions).
    private func isFuzzyMatch(_ a: String, _ b: String) -> Bool {
        if a == b { return true }
        if a.contains(b) || b.contains(a) { return true }

        let lenDiff = abs(a.count - b.count)

        if lenDiff == 0 {
            let diffs = zip(a, b).filter { $0 != $1 }.count
            if diffs <= 1 { return true }
            if diffs <= 2 && PlatePatternMatcher.confusableDistance(a, b) <= 1.0 { return true }
            if PlatePatternMatcher.confusableDistance(a, b) <= 1.0 { return true }
        }

        if lenDiff <= 2 {
            if editDistance(Array(a), Array(b)) <= 2 { return true }
            if PlatePatternMatcher.confusableDistance(a, b) <= 1.5 { return true }
        }

        let aDigits = a.filter(\.isNumber)
        let bDigits = b.filter(\.isNumber)
        if aDigits.count >= 3 && aDigits == bDigits {
            let aLetters = a.filter(\.isLetter)
            let bLetters = b.filter(\.isLetter)
            if aLetters.count > 0 && bLetters.count > 0 {
                let letterDist = editDistance(Array(aLetters), Array(bLetters))
                if letterDist <= 2 { return true }
            }
        }

        return false
    }

    /// Looser fuzzy match for recent reads — if a plate was logged within the last
    /// few seconds, any nearby reading is almost certainly the same physical plate.
    private func isFuzzyMatchRecent(_ a: String, _ b: String) -> Bool {
        if isFuzzyMatch(a, b) { return true }

        let lenDiff = abs(a.count - b.count)
        if lenDiff <= 1 {
            if PlatePatternMatcher.confusableDistance(a, b) <= 2.0 { return true }
            if editDistance(Array(a), Array(b)) <= 3 { return true }
        }
        return false
    }

    /// Looser match for merging candidate frame counts (not yet logged).
    private func isCandidateMerge(_ a: String, _ b: String) -> Bool {
        if isFuzzyMatch(a, b) { return true }
        if abs(a.count - b.count) <= 1 {
            if editDistance(Array(a), Array(b)) <= 1 { return true }
        }
        return false
    }

    /// Quantize a bounding box into a grid cell key for region-based suppression.
    /// Divides the frame into a 4x4 grid — plates in the same cell are considered
    /// the "same region" for cooldown purposes.
    private func regionKeyForBoundingBox(_ box: CGRect) -> String {
        let col = Int(box.midX * 4)
        let row = Int(box.midY * 4)
        return "\(col),\(row)"
    }

    private func editDistance(_ a: [Character], _ b: [Character]) -> Int {
        let m = a.count, n = b.count
        var prev = Array(0...n)
        var curr = [Int](repeating: 0, count: n + 1)
        for i in 1...m {
            curr[0] = i
            for j in 1...n {
                if a[i-1] == b[j-1] {
                    curr[j] = prev[j-1]
                } else {
                    curr[j] = 1 + min(prev[j-1], prev[j], curr[j-1])
                }
            }
            prev = curr
        }
        return prev[n]
    }

    func updateCloudService() {
        let settings = AppSettings.shared
        if settings.useCloudOCR && !settings.plateRecognizerAPIKey.isEmpty {
            cloudService = PlateRecognizerService(apiKey: settings.plateRecognizerAPIKey)
        } else {
            cloudService = nil
        }
    }

    private func persistScanLog() {
        do {
            let data = try JSONEncoder().encode(scanLog)
            try data.write(to: Self.scanLogURL, options: .atomic)
        } catch {
            print("Failed to persist scan log: \(error)")
        }

        if var session = activeSession {
            session.plates = scanLog
            session.diagnostics = diagnosticLog
            sessionManager.save(session)
            activeSession = session
        }
    }

    private func loadPersistedScanLog() {
        guard FileManager.default.fileExists(atPath: Self.scanLogURL.path) else { return }
        do {
            let data = try Data(contentsOf: Self.scanLogURL)
            let restored = try JSONDecoder().decode([ScannedPlate].self, from: data)
            let todayOnly = restored.filter { $0.timestamp >= currentDayStart }
            if !todayOnly.isEmpty {
                scanLog = todayOnly
                for entry in todayOnly {
                    seenPlates.append((text: entry.text, time: entry.timestamp))
                    // Reconstruct ticketedPlates so the UI correctly marks already-ticketed plates.
                    if case .ticketed = entry.authStatus {
                        let plateKey = entry.text.uppercased().trimmingCharacters(in: .whitespaces)
                        ticketedPlates[plateKey] = entry.ticketedInLot ?? ""
                    }
                }
            }
            if todayOnly.count < restored.count {
                deletePersistedScanLog()
                if !todayOnly.isEmpty {
                    persistScanLog()
                }
            }
        } catch {
            print("Failed to load persisted scan log: \(error)")
        }
    }

    private func deletePersistedScanLog() {
        try? FileManager.default.removeItem(at: Self.scanLogURL)
    }
}

extension PlateReaderViewModel: CameraServiceDelegate {

    nonisolated func cameraService(_ service: CameraService, didOutput sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation) {
        let start = CACurrentMediaTime()

        if let cloud = cloudService {
            // Release the CameraService processing lock immediately so frames
            // keep flowing. The cloud service has its own inFlight guard.
            service.markProcessingComplete(elapsed: 0.05)

            cloud.recognizePlates(in: sampleBuffer) { [weak self] result in
                Task { @MainActor [weak self] in
                    self?.handleResult(result)
                }
            }
        } else {
            recognitionService.isExternalCamera = service.isUsingExternalCamera

            recognitionService.recognizePlates(in: sampleBuffer, orientation: orientation) { [weak self] result in
                let elapsed = CACurrentMediaTime() - start
                service.markProcessingComplete(elapsed: elapsed)

                Task { @MainActor [weak self] in
                    self?.handleResult(result)
                }
            }
        }
    }
}
