import Vision
import CoreMedia
import CoreImage

struct RecognitionResult: Sendable {
    let plates: [RecognizedPlate]
    let diagnostics: [DiagnosticEntry]
}

final class PlateRecognitionService {

    private let requestQueue = DispatchQueue(label: "com.birddog.recognition", qos: .utility)
    private let builtInScanRegion = CGRect(x: 0, y: 0.2, width: 1.0, height: 0.6)
    private let defaultExternalScanRegion = CGRect(x: 0, y: 0.0, width: 1.0, height: 1.0)
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    var isExternalCamera = false

    private var consecutiveEmptyFrames: Int = 0

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

    func recognizePlates(in sampleBuffer: CMSampleBuffer,
                         orientation: CGImagePropertyOrientation,
                         completion: @escaping (RecognitionResult) -> Void) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            completion(RecognitionResult(plates: [], diagnostics: []))
            return
        }

        let useExternal = isExternalCamera

        requestQueue.async { [self] in
            let roi = useExternal ? externalScanRegion : builtInScanRegion

            func runOCR(on buffer: CVPixelBuffer, level: VNRequestTextRecognitionLevel = .accurate) -> [VNRecognizedTextObservation] {
                let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: orientation)
                let req = VNRecognizeTextRequest()
                req.recognitionLevel = level
                req.usesLanguageCorrection = false
                req.revision = VNRecognizeTextRequestRevision3
                req.regionOfInterest = roi
                try? handler.perform([req])
                return req.results ?? []
            }

            let rawObs = runOCR(on: pixelBuffer)

            // Only fall back to enhanced grayscale if the fast pass found nothing
            // — avoids doubling OCR cost on every single frame.
            let observations: [VNRecognizedTextObservation]
            if useExternal && rawObs.isEmpty, let enhanced = enhanceFrameReusing(pixelBuffer) {
                let grayObs = runOCR(on: enhanced)
                observations = grayObs
            } else if useExternal && !rawObs.isEmpty {
                let hasPlateCandidate = rawObs.contains { obs in
                    guard let text = obs.topCandidates(1).first?.string else { return false }
                    let norm = PlatePatternMatcher.normalize(text)
                    return PlatePatternMatcher.evaluatePlate(norm) == nil
                }
                if hasPlateCandidate {
                    observations = rawObs
                } else if let enhanced = enhanceFrameReusing(pixelBuffer) {
                    let grayObs = runOCR(on: enhanced)
                    observations = mergeObservations(primary: rawObs, secondary: grayObs)
                } else {
                    observations = rawObs
                }
            } else {
                observations = rawObs
            }

            guard !observations.isEmpty else {
                self.consecutiveEmptyFrames += 1
                completion(RecognitionResult(plates: [], diagnostics: []))
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

            completion(RecognitionResult(plates: plates, diagnostics: diagnostics))
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

    /// High-contrast grayscale pipeline tuned for colored plates (yellow NJ,
    /// green specialty). Reuses a single pixel buffer across frames to avoid
    /// allocating ~8MB of BGRA memory on every call.
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

        if enhancedBuffer == nil
            || CVPixelBufferGetWidth(enhancedBuffer!) != width
            || CVPixelBufferGetHeight(enhancedBuffer!) != height {
            let attrs: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ]
            var buf: CVPixelBuffer?
            CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA, attrs as CFDictionary, &buf)
            enhancedBuffer = buf
        }

        guard let output = enhancedBuffer else { return nil }
        ciContext.render(highContrast, to: output)
        return output
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
