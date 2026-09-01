import Vision
import CoreMedia
import CoreImage

struct RecognitionResult: Sendable {
    let plates: [RecognizedPlate]
    let diagnostics: [DiagnosticEntry]
    let rectangleDetected: Bool
}

final class PlateRecognitionService {

    private let requestQueue = DispatchQueue(label: "com.birddog.recognition", qos: .utility)
    private let builtInScanRegion = CGRect(x: 0, y: 0.2, width: 1.0, height: 0.6)
    private let defaultExternalScanRegion = CGRect(x: 0.05, y: 0.15, width: 0.9, height: 0.7)
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    var isExternalCamera = false

    private var consecutiveEmptyFrames: Int = 0
    private var lastRectangleDetected = false

    private var recentPlateYPositions: [CGFloat] = []
    private var lastPlateDetectionTime: Date = .distantPast
    private let adaptiveROIHistory = 5
    private let adaptiveROITimeout: TimeInterval = 5.0
    private let adaptiveROIPadding: CGFloat = 0.20

    private var externalScanRegion: CGRect {
        guard isExternalCamera,
              !recentPlateYPositions.isEmpty,
              Date().timeIntervalSince(lastPlateDetectionTime) < adaptiveROITimeout else {
            return defaultExternalScanRegion
        }
        let avgY = recentPlateYPositions.reduce(0, +) / CGFloat(recentPlateYPositions.count)
        let minY = max(0, avgY - adaptiveROIPadding)
        let maxY = min(1.0, avgY + adaptiveROIPadding)
        return CGRect(x: 0, y: minY, width: 1.0, height: maxY - minY)
    }

    private var enhancedBuffer: CVPixelBuffer?
    private var downscaledBuffer: CVPixelBuffer?
    private let downscaleWidth = 960
    private let downscaleHeight = 540

    /// Renders the pixel buffer into a reusable half-resolution buffer for the
    /// cheap .fast OCR pass. Avoids allocating on every frame.
    private func downscaleForDetection(_ pixelBuffer: CVPixelBuffer) -> CVPixelBuffer? {
        let srcWidth = CVPixelBufferGetWidth(pixelBuffer)
        let srcHeight = CVPixelBufferGetHeight(pixelBuffer)
        guard srcWidth > downscaleWidth || srcHeight > downscaleHeight else { return pixelBuffer }

        if downscaledBuffer == nil
            || CVPixelBufferGetWidth(downscaledBuffer!) != downscaleWidth
            || CVPixelBufferGetHeight(downscaledBuffer!) != downscaleHeight {
            let attrs: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: downscaleWidth,
                kCVPixelBufferHeightKey as String: downscaleHeight,
            ]
            var buf: CVPixelBuffer?
            CVPixelBufferCreate(kCFAllocatorDefault, downscaleWidth, downscaleHeight, kCVPixelFormatType_32BGRA, attrs as CFDictionary, &buf)
            downscaledBuffer = buf
        }
        guard let output = downscaledBuffer else { return nil }

        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let scaleX = CGFloat(downscaleWidth) / CGFloat(srcWidth)
        let scaleY = CGFloat(downscaleHeight) / CGFloat(srcHeight)
        let scaled = ciImage.transformed(by: CGAffineTransform(scaleX: scaleX, y: scaleY))
        ciContext.render(scaled, to: output)
        return output
    }

    func recognizePlates(in sampleBuffer: CMSampleBuffer,
                         orientation: CGImagePropertyOrientation,
                         completion: @escaping (RecognitionResult) -> Void) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            completion(RecognitionResult(plates: [], diagnostics: [], rectangleDetected: lastRectangleDetected))
            return
        }

        let useExternal = isExternalCamera

        requestQueue.async { [self] in
            let roi = useExternal ? externalScanRegion : builtInScanRegion

            // Rectangle pre-filter: skip expensive OCR if no plate-shaped objects visible.
            // Uses the downscaled buffer for speed (~3-5ms).
            if useExternal {
                let detectBuffer = self.downscaleForDetection(pixelBuffer) ?? pixelBuffer
                let hasRects = self.detectPlateRectangles(in: detectBuffer, orientation: orientation, roi: roi)
                self.lastRectangleDetected = hasRects
                if !hasRects && self.consecutiveEmptyFrames > 2 {
                    self.consecutiveEmptyFrames += 1
                    completion(RecognitionResult(plates: [], diagnostics: [], rectangleDetected: false))
                    return
                }
            }

            func runOCR(on buffer: CVPixelBuffer, level: VNRequestTextRecognitionLevel = .accurate, region: CGRect? = nil) -> [VNRecognizedTextObservation] {
                let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: orientation)
                let req = VNRecognizeTextRequest()
                req.recognitionLevel = level
                req.usesLanguageCorrection = false
                req.revision = VNRecognizeTextRequestRevision3
                req.regionOfInterest = region ?? roi
                try? handler.perform([req])
                return req.results ?? []
            }

            // Two-stage OCR for external cameras: .fast on a downscaled buffer first,
            // .accurate on auto-levels-normalized full-res only when needed.
            let rawObs: [VNRecognizedTextObservation]
            if useExternal {
                let detectBuffer = self.downscaleForDetection(pixelBuffer) ?? pixelBuffer
                let fastObs = runOCR(on: detectBuffer, level: .fast)
                let fastHasPlate = fastObs.contains { obs in
                    guard let text = obs.topCandidates(1).first?.string else { return false }
                    let norm = PlatePatternMatcher.normalize(text)
                    return PlatePatternMatcher.evaluatePlate(norm) == nil
                }
                if fastHasPlate {
                    rawObs = fastObs
                } else if !fastObs.isEmpty {
                    let normalizedBuf = self.autoLevelsNormalize(pixelBuffer) ?? pixelBuffer
                    let accurateObs = runOCR(on: normalizedBuf, level: .accurate)
                    rawObs = mergeObservations(primary: fastObs, secondary: accurateObs)
                } else {
                    let normalizedBuf = self.autoLevelsNormalize(pixelBuffer) ?? pixelBuffer
                    rawObs = runOCR(on: normalizedBuf, level: .accurate)
                }
            } else {
                rawObs = runOCR(on: pixelBuffer)
            }

            let observations: [VNRecognizedTextObservation]
            if useExternal && rawObs.isEmpty, let enhanced = enhanceFrameReusing(pixelBuffer) {
                let grayObs = runOCR(on: enhanced, level: .fast)
                let grayHasPlate = grayObs.contains { obs in
                    guard let text = obs.topCandidates(1).first?.string else { return false }
                    let norm = PlatePatternMatcher.normalize(text)
                    return PlatePatternMatcher.evaluatePlate(norm) == nil
                }
                observations = grayHasPlate ? grayObs : (grayObs.isEmpty ? [] : runOCR(on: enhanced, level: .accurate))
            } else if useExternal && !rawObs.isEmpty {
                let hasPlateCandidate = rawObs.contains { obs in
                    guard let text = obs.topCandidates(1).first?.string else { return false }
                    let norm = PlatePatternMatcher.normalize(text)
                    return PlatePatternMatcher.evaluatePlate(norm) == nil
                }
                if hasPlateCandidate {
                    observations = rawObs
                } else if let enhanced = enhanceFrameReusing(pixelBuffer) {
                    let grayObs = runOCR(on: enhanced, level: .fast)
                    observations = mergeObservations(primary: rawObs, secondary: grayObs)
                } else {
                    observations = rawObs
                }
            } else {
                observations = rawObs
            }

            guard !observations.isEmpty else {
                self.consecutiveEmptyFrames += 1
                completion(RecognitionResult(plates: [], diagnostics: [], rectangleDetected: self.lastRectangleDetected))
                return
            }

            let dominant = dominantTextPerCluster(observations)
            let now = Date()
            var plates: [RecognizedPlate] = []
            var plateObservations: [VNRecognizedTextObservation] = []
            var diagnostics: [DiagnosticEntry] = []

            for observation in observations {
                let topN = observation.topCandidates(5)
                guard let candidate = topN.first else { continue }

                let rawText = candidate.string
                let normalized = PlatePatternMatcher.normalize(rawText)
                let box = observation.boundingBox
                let aspect: CGFloat
                if useExternal {
                    aspect = quadrilateralAspect(observation)
                } else {
                    aspect = box.height > 0 ? box.width / box.height : 0
                }
                let isDominant = dominant.contains(where: { $0 === observation })

                var reason = ""
                var accepted = false

                // Distant plates produce smaller bounding boxes and lower
                // confidence scores. Scale the threshold down for small detections.
                let boxArea = box.width * box.height
                let isDistant = useExternal && boxArea < 0.005
                let minConfidence: Float = isDistant ? 0.50 : (useExternal ? 0.65 : 0.8)

                let minAspect: CGFloat = useExternal ? 0.15 : 1.2
                let maxAspect: CGFloat = 10.0
                let passesAspect = aspect > minAspect && aspect < maxAspect

                var alternates = topN.dropFirst().compactMap { alt -> String? in
                    let norm = PlatePatternMatcher.normalize(alt.string)
                    return norm != normalized ? norm : nil
                }

                var plateText: String
                let rejection = PlatePatternMatcher.evaluatePlate(normalized)
                if rejection == .tooLong, normalized.count >= 8 {
                    plateText = self.trimToPlate(normalized) ?? normalized
                } else if rejection == .noFormatMatch || rejection == .noDigits || rejection == .tooFewDigits {
                    // Rim text merged with plate (e.g. "BKABC1234", "ABC1234PA")
                    // — try extracting a valid substring
                    plateText = self.trimToPlate(normalized) ?? normalized
                } else {
                    plateText = normalized
                }

                if PlatePatternMatcher.evaluatePlate(plateText) != nil {
                    let recovered = self.recoverFormatViaConfusables(plateText)
                    for alt in recovered where !alternates.contains(alt) {
                        alternates.append(alt)
                    }
                }

                let matchesFormat = PlatePatternMatcher.evaluatePlate(plateText) == nil
                let effectiveMinConf: Float
                if matchesFormat {
                    effectiveMinConf = isDistant ? 0.40 : (useExternal ? 0.50 : 0.6)
                } else {
                    effectiveMinConf = minConfidence
                }

                if candidate.confidence < effectiveMinConf {
                    reason = PlatePatternMatcher.RejectionReason.lowConfidence.rawValue
                } else if !isDominant {
                    reason = "not_dominant_text"
                } else if !passesAspect {
                    reason = PlatePatternMatcher.RejectionReason.badAspectRatio.rawValue
                } else if let rejection = PlatePatternMatcher.evaluatePlate(plateText) {
                    reason = rejection.rawValue
                } else {
                    accepted = true
                    plates.append(RecognizedPlate(
                        text: plateText,
                        confidence: candidate.confidence,
                        boundingBox: box,
                        timestamp: now,
                        alternates: alternates
                    ))
                    plateObservations.append(observation)
                }

                diagnostics.append(DiagnosticEntry(
                    timestamp: now,
                    rawText: rawText,
                    normalizedText: normalized,
                    confidence: candidate.confidence,
                    boundingBox: box,
                    aspectRatio: aspect,
                    accepted: accepted,
                    rejectionReason: reason
                ))
            }

            // Re-crop verification only for low-confidence plates
            if useExternal && !plates.isEmpty {
                var verifiedPlates = plates
                for (i, plate) in plates.enumerated() {
                    guard plate.confidence < 0.85 else { continue }
                    let obs = i < plateObservations.count ? plateObservations[i] : nil
                    let reCropText: String?
                    if let obs {
                        reCropText = self.perspectiveCorrectedReCropAndOCR(
                            pixelBuffer: pixelBuffer,
                            observation: obs,
                            orientation: orientation
                        )
                    } else {
                        reCropText = self.reCropAndOCR(
                            pixelBuffer: pixelBuffer,
                            boundingBox: plate.boundingBox,
                            orientation: orientation
                        )
                    }
                    if let reCropText, reCropText != plate.text,
                       PlatePatternMatcher.evaluatePlate(reCropText) == nil {
                        var newAlts = plate.alternates
                        if !newAlts.contains(reCropText) {
                            newAlts.append(reCropText)
                        }
                        verifiedPlates[i] = RecognizedPlate(
                            text: plate.text,
                            confidence: plate.confidence,
                            boundingBox: plate.boundingBox,
                            timestamp: plate.timestamp,
                            alternates: newAlts
                        )
                    }
                }
                plates = verifiedPlates
            }

            if plates.isEmpty {
                self.consecutiveEmptyFrames += 1
            } else {
                self.consecutiveEmptyFrames = 0
                for plate in plates {
                    self.updateAdaptiveROI(plateBox: plate.boundingBox)
                }
            }

            completion(RecognitionResult(plates: plates, diagnostics: diagnostics, rectangleDetected: self.lastRectangleDetected))
        }
    }

    /// Extracts a valid plate substring from OCR text that may include
    /// rim/frame text merged with the actual plate number. Scans all
    /// 5-7 character windows, preferring longer matches and rightmost
    /// position (rim text is usually a prefix from dealer name above).
    private func trimToPlate(_ text: String) -> String? {
        let chars = Array(text)
        guard chars.count >= 5 else { return nil }
        var best: String?
        var bestLen = 0

        for targetLen in stride(from: 7, through: 5, by: -1) {
            guard chars.count >= targetLen else { continue }
            for start in stride(from: chars.count - targetLen, through: 0, by: -1) {
                let sub = String(chars[start..<(start + targetLen)])
                let hasLetters = sub.contains(where: \.isLetter)
                let hasDigits = sub.contains(where: \.isNumber)
                guard hasLetters && hasDigits else { continue }
                if PlatePatternMatcher.evaluatePlate(sub) == nil {
                    if targetLen > bestLen {
                        best = sub
                        bestLen = targetLen
                    }
                    if targetLen == 7 { return best }
                }
            }
        }

        return best
    }

    private var normalizedBuffer: CVPixelBuffer?

    /// Lightweight auto-levels normalization: adjusts brightness and contrast
    /// based on the frame's actual luminance range. Always-on for external cameras
    /// to compensate for shadow/highlight variation without the cost of the full
    /// grayscale tone-curve pipeline.
    private func autoLevelsNormalize(_ pixelBuffer: CVPixelBuffer) -> CVPixelBuffer? {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let stats = frameBrightnessStats(pixelBuffer)
        let brightnessAdj = (0.5 - stats.mean) * 0.3
        let contrastAdj = stats.range < 0.4 ? 1.3 : (stats.range > 0.8 ? 0.9 : 1.1)

        guard let adjusted = CIFilter(name: "CIColorControls", parameters: [
            kCIInputImageKey: ciImage,
            "inputSaturation": 1.0,
            "inputContrast": NSNumber(value: contrastAdj),
            "inputBrightness": NSNumber(value: brightnessAdj),
        ])?.outputImage else { return nil }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let output = ensureBuffer(&normalizedBuffer, width: width, height: height)
        guard let output else { return nil }
        ciContext.render(adjusted, to: output)
        return output
    }

    /// Samples a sparse grid to estimate frame brightness statistics.
    private func frameBrightnessStats(_ pixelBuffer: CVPixelBuffer) -> (mean: Double, range: Double) {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return (0.5, 0.5) }
        let ptr = base.assumingMemoryBound(to: UInt8.self)

        let gridSize = 8
        let stepX = width / gridSize
        let stepY = height / gridSize
        var minVal: Double = 255, maxVal: Double = 0, total: Double = 0
        var count: Double = 0
        for row in 0..<gridSize {
            for col in 0..<gridSize {
                let x = col * stepX + stepX / 2
                let y = row * stepY + stepY / 2
                let g = Double(ptr[y * bytesPerRow + x * 4 + 1])
                total += g
                minVal = min(minVal, g)
                maxVal = max(maxVal, g)
                count += 1
            }
        }
        let mean = total / count / 255.0
        let range = (maxVal - minVal) / 255.0
        return (mean, range)
    }

    /// High-contrast grayscale pipeline tuned for colored plates (yellow NJ,
    /// green specialty) with CLAHE-style tiled contrast enhancement.
    /// Reuses a single pixel buffer across frames.
    private func enhanceFrameReusing(_ pixelBuffer: CVPixelBuffer) -> CVPixelBuffer? {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)

        guard let grayscale = CIFilter(name: "CIColorControls", parameters: [
            kCIInputImageKey: ciImage,
            "inputSaturation": 0.0,
            "inputContrast": 1.0,
            "inputBrightness": 0.0,
        ])?.outputImage else { return nil }

        guard let highContrast = CIFilter(name: "CIToneCurve", parameters: [
            kCIInputImageKey: grayscale,
            "inputPoint0": CIVector(x: 0.0, y: 0.0),
            "inputPoint1": CIVector(x: 0.20, y: 0.0),
            "inputPoint2": CIVector(x: 0.45, y: 0.15),
            "inputPoint3": CIVector(x: 0.65, y: 0.85),
            "inputPoint4": CIVector(x: 1.0, y: 1.0),
        ])?.outputImage else { return nil }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let output = ensureBuffer(&enhancedBuffer, width: width, height: height)
        guard let output else { return nil }
        ciContext.render(highContrast, to: output)

        applyTiledContrastEnhancement(output)
        return output
    }

    /// CLAHE-style tiled contrast enhancement for mixed shadow/sun conditions.
    /// Splits the buffer into a 4x4 grid, computes per-tile brightness offset,
    /// and applies a simple normalization pass.
    private func applyTiledContrastEnhancement(_ pixelBuffer: CVPixelBuffer) {
        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return }
        let ptr = base.assumingMemoryBound(to: UInt8.self)

        let tilesX = 4, tilesY = 4
        let tileW = width / tilesX
        let tileH = height / tilesY

        // Compute per-tile mean brightness
        var tileMeans = [[Double]](repeating: [Double](repeating: 0, count: tilesX), count: tilesY)
        for ty in 0..<tilesY {
            for tx in 0..<tilesX {
                var sum: Double = 0, count: Double = 0
                let step = 8
                var y = ty * tileH
                while y < (ty + 1) * tileH {
                    var x = tx * tileW
                    while x < (tx + 1) * tileW {
                        sum += Double(ptr[y * bytesPerRow + x * 4 + 1])
                        count += 1
                        x += step
                    }
                    y += step
                }
                tileMeans[ty][tx] = count > 0 ? sum / count : 128
            }
        }

        let globalMean = tileMeans.flatMap { $0 }.reduce(0, +) / Double(tilesX * tilesY)

        // Apply per-tile brightness correction toward the global mean
        for ty in 0..<tilesY {
            for tx in 0..<tilesX {
                let offset = Int(globalMean - tileMeans[ty][tx]) / 2
                guard abs(offset) > 5 else { continue }
                for y in (ty * tileH)..<min((ty + 1) * tileH, height) {
                    for x in (tx * tileW)..<min((tx + 1) * tileW, width) {
                        let idx = y * bytesPerRow + x * 4
                        for c in 0..<3 {
                            let val = Int(ptr[idx + c]) + offset
                            ptr[idx + c] = UInt8(max(0, min(255, val)))
                        }
                    }
                }
            }
        }
    }

    /// Allocates or reuses a BGRA pixel buffer at the given dimensions.
    private func ensureBuffer(_ buffer: inout CVPixelBuffer?, width: Int, height: Int) -> CVPixelBuffer? {
        if buffer == nil
            || CVPixelBufferGetWidth(buffer!) != width
            || CVPixelBufferGetHeight(buffer!) != height {
            let attrs: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ]
            var buf: CVPixelBuffer?
            CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA, attrs as CFDictionary, &buf)
            buffer = buf
        }
        return buffer
    }

    /// Groups text observations by vertical proximity, then keeps only the
    /// tallest observation in each group. On a license plate the plate number
    /// is always the largest text -- state names, slogans, and URLs are smaller.
    private func dominantTextPerCluster(_ observations: [VNRecognizedTextObservation]) -> [VNRecognizedTextObservation] {
        let clusterThreshold: CGFloat = 0.06

        let sorted = observations.sorted { $0.boundingBox.midY < $1.boundingBox.midY }
        var clusters: [[VNRecognizedTextObservation]] = []
        var current: [VNRecognizedTextObservation] = []

        for obs in sorted {
            if let last = current.last {
                let gap = abs(obs.boundingBox.midY - last.boundingBox.midY)
                if gap > clusterThreshold {
                    clusters.append(current)
                    current = [obs]
                } else {
                    current.append(obs)
                }
            } else {
                current.append(obs)
            }
        }
        if !current.isEmpty { clusters.append(current) }

        var dominant: [VNRecognizedTextObservation] = []
        for cluster in clusters {
            guard let tallest = cluster.max(by: { $0.boundingBox.height < $1.boundingBox.height }) else { continue }
            let threshold = tallest.boundingBox.height * 0.6
            for obs in cluster where obs.boundingBox.height >= threshold {
                dominant.append(obs)
            }
        }

        return dominant
    }

    /// Merge observations from raw and grayscale OCR passes.
    /// For each spatial region, keep the observation whose top candidate
    /// looks most like a license plate (has digits + letters, higher confidence).
    private func mergeObservations(
        primary: [VNRecognizedTextObservation],
        secondary: [VNRecognizedTextObservation]
    ) -> [VNRecognizedTextObservation] {
        if secondary.isEmpty { return primary }
        if primary.isEmpty { return secondary }

        var merged = primary
        let overlapThreshold: CGFloat = 0.3

        for secObs in secondary {
            let secBox = secObs.boundingBox
            let secText = secObs.topCandidates(1).first.map {
                PlatePatternMatcher.normalize($0.string)
            } ?? ""

            var foundOverlap = false
            for (i, priObs) in merged.enumerated() {
                let priBox = priObs.boundingBox
                let intersection = priBox.intersection(secBox)
                guard !intersection.isNull else { continue }
                let iou = (intersection.width * intersection.height) /
                    max(priBox.width * priBox.height, 0.0001)
                guard iou > overlapThreshold else { continue }

                foundOverlap = true
                let priText = priObs.topCandidates(1).first.map {
                    PlatePatternMatcher.normalize($0.string)
                } ?? ""

                let priScore = plateScore(priText, conf: priObs.topCandidates(1).first?.confidence ?? 0)
                let secScore = plateScore(secText, conf: secObs.topCandidates(1).first?.confidence ?? 0)

                if secScore > priScore {
                    merged[i] = secObs
                }
                break
            }

            if !foundOverlap {
                let secScore = plateScore(secText, conf: secObs.topCandidates(1).first?.confidence ?? 0)
                if secScore > 0 {
                    merged.append(secObs)
                }
            }
        }

        return merged
    }

    /// Higher score = more plate-like. Plates must have both letters and digits.
    private func plateScore(_ text: String, conf: Float) -> Float {
        guard text.count >= 5, text.count <= 7 else { return 0 }
        let hasLetters = text.contains(where: \.isLetter)
        let hasDigits = text.contains(where: \.isNumber)
        guard hasLetters && hasDigits else { return 0 }
        var score = conf
        if PlatePatternMatcher.evaluatePlate(text) == nil {
            score += 1.0
        }
        if PlatePatternMatcher.isLocalFormat(text) {
            score += 0.5
        }
        return score
    }

    // MARK: - Rectangle Pre-filter

    /// Fast check for plate-shaped rectangles before running expensive OCR.
    /// Returns true if at least one rectangle with plate-like aspect ratio is found.
    private func detectPlateRectangles(in pixelBuffer: CVPixelBuffer, orientation: CGImagePropertyOrientation, roi: CGRect) -> Bool {
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: orientation)
        let req = VNDetectRectanglesRequest()
        req.minimumAspectRatio = 0.15
        req.maximumAspectRatio = 0.85
        req.minimumSize = 0.02
        req.maximumObservations = 8
        req.regionOfInterest = roi
        try? handler.perform([req])
        guard let results = req.results, !results.isEmpty else { return false }
        return results.contains { obs in
            let box = obs.boundingBox
            let aspect = box.height > 0 ? box.width / box.height : 0
            return aspect > 1.5 && aspect < 8.0
        }
    }

    // MARK: - Quadrilateral Aspect Ratio

    /// Computes aspect ratio from the observation's actual corner points
    /// rather than the axis-aligned bounding box. This gives an accurate
    /// width/height ratio even when the plate is keystoned by the camera angle.
    private func quadrilateralAspect(_ observation: VNRecognizedTextObservation) -> CGFloat {
        let tl = observation.topLeft
        let tr = observation.topRight
        let bl = observation.bottomLeft
        let br = observation.bottomRight

        let topWidth = hypot(tr.x - tl.x, tr.y - tl.y)
        let bottomWidth = hypot(br.x - bl.x, br.y - bl.y)
        let leftHeight = hypot(tl.x - bl.x, tl.y - bl.y)
        let rightHeight = hypot(tr.x - br.x, tr.y - br.y)

        let avgWidth = (topWidth + bottomWidth) / 2
        let avgHeight = (leftHeight + rightHeight) / 2
        guard avgHeight > 0 else { return 0 }
        return avgWidth / avgHeight
    }

    // MARK: - Re-crop Verification

    /// Crops the frame to a plate's bounding box and re-runs OCR.
    /// For external cameras, applies perspective correction to dewarp
    /// keystoned plates before the second OCR pass.
    private func reCropAndOCR(pixelBuffer: CVPixelBuffer, boundingBox: CGRect, orientation: CGImagePropertyOrientation) -> String? {
        reCropAndOCR(pixelBuffer: pixelBuffer, boundingBox: boundingBox, observation: nil, orientation: orientation)
    }

    private func perspectiveCorrectedReCropAndOCR(pixelBuffer: CVPixelBuffer, observation: VNRecognizedTextObservation, orientation: CGImagePropertyOrientation) -> String? {
        reCropAndOCR(pixelBuffer: pixelBuffer, boundingBox: observation.boundingBox, observation: observation, orientation: orientation)
    }

    private func reCropAndOCR(pixelBuffer: CVPixelBuffer, boundingBox: CGRect, observation: VNRecognizedTextObservation?, orientation: CGImagePropertyOrientation) -> String? {
        let width = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let height = CGFloat(CVPixelBufferGetHeight(pixelBuffer))

        let ciImage: CIImage

        if let obs = observation {
            let pad: CGFloat = 0.04
            let tl = CGPoint(x: max(0, obs.topLeft.x - pad) * width,
                             y: max(0, obs.topLeft.y - pad) * height)
            let tr = CGPoint(x: min(1, obs.topRight.x + pad) * width,
                             y: max(0, obs.topRight.y - pad) * height)
            let bl = CGPoint(x: max(0, obs.bottomLeft.x - pad) * width,
                             y: min(1, obs.bottomLeft.y + pad) * height)
            let br = CGPoint(x: min(1, obs.bottomRight.x + pad) * width,
                             y: min(1, obs.bottomRight.y + pad) * height)

            let source = CIImage(cvPixelBuffer: pixelBuffer)
            guard let corrected = CIFilter(name: "CIPerspectiveCorrection", parameters: [
                kCIInputImageKey: source,
                "inputTopLeft": CIVector(cgPoint: tl),
                "inputTopRight": CIVector(cgPoint: tr),
                "inputBottomLeft": CIVector(cgPoint: bl),
                "inputBottomRight": CIVector(cgPoint: br),
            ])?.outputImage else { return nil }
            ciImage = corrected
        } else {
            let pad: CGFloat = 0.03
            let cropRect = CGRect(
                x: max(0, boundingBox.origin.x - pad) * width,
                y: max(0, boundingBox.origin.y - pad) * height,
                width: min(1.0, boundingBox.width + pad * 2) * width,
                height: min(1.0, boundingBox.height + pad * 2) * height
            )
            guard cropRect.width > 20, cropRect.height > 10 else { return nil }
            ciImage = CIImage(cvPixelBuffer: pixelBuffer).cropped(to: cropRect)
        }

        let handler = VNImageRequestHandler(ciImage: ciImage, orientation: orientation)
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .fast
        req.usesLanguageCorrection = false
        req.revision = VNRecognizeTextRequestRevision3
        try? handler.perform([req])

        guard let top = req.results?.first?.topCandidates(1).first else { return nil }
        let normalized = PlatePatternMatcher.normalize(top.string)
        guard normalized.count >= 5, normalized.count <= 7 else { return nil }
        return normalized
    }

    // MARK: - Confusable Format Recovery

    /// Tries single-character confusable substitutions to find a format-valid reading.
    private func recoverFormatViaConfusables(_ text: String) -> [String] {
        guard text.count >= 5, text.count <= 7 else { return [] }
        var recovered: [String] = []
        let chars = Array(text)

        for i in 0..<chars.count {
            guard let alts = PlatePatternMatcher.confusables[chars[i]] else { continue }
            for alt in alts {
                var modified = chars
                modified[i] = alt
                let variant = String(modified)
                if PlatePatternMatcher.evaluatePlate(variant) == nil,
                   !recovered.contains(variant) {
                    recovered.append(variant)
                    if recovered.count >= 3 { return recovered }
                }
            }
        }
        return recovered
    }

    // MARK: - Adaptive ROI

    private func updateAdaptiveROI(plateBox: CGRect) {
        let centerY = plateBox.midY
        recentPlateYPositions.append(centerY)
        if recentPlateYPositions.count > adaptiveROIHistory {
            recentPlateYPositions.removeFirst()
        }
        lastPlateDetectionTime = Date()
    }
}
