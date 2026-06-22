import Foundation
import CoreMedia
import CoreVideo
import UIKit
import CoreImage

/// Sends camera frames to the PlateRecognizer cloud API and returns results
/// in the same format as the on-device PlateRecognitionService.
final class PlateRecognizerService {

    private let apiURL = URL(string: "https://api.platerecognizer.com/v1/plate-reader/")!
    private let apiKey: String
    private let session: URLSession
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    private var inFlight = false
    private let lock = NSLock()

    init(apiKey: String) {
        self.apiKey = apiKey
        print("[PlateRecognizer] Initialized with key: \(apiKey.prefix(8))...")
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        self.session = URLSession(configuration: config)
    }

    func recognizePlates(in sampleBuffer: CMSampleBuffer,
                         completion: @escaping (RecognitionResult) -> Void) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            print("[PlateRecognizer] No pixel buffer")
            completion(RecognitionResult(plates: [], diagnostics: []))
            return
        }
        let imageWidth = CVPixelBufferGetWidth(pixelBuffer)
        let imageHeight = CVPixelBufferGetHeight(pixelBuffer)

        lock.lock()
        if inFlight {
            lock.unlock()
            completion(RecognitionResult(plates: [], diagnostics: []))
            return
        }
        inFlight = true
        lock.unlock()

        guard let jpegData = pixelBufferToJPEG(pixelBuffer, quality: 0.80) else {
            print("[PlateRecognizer] JPEG conversion failed")
            lock.lock(); inFlight = false; lock.unlock()
            completion(RecognitionResult(plates: [], diagnostics: []))
            return
        }

        print("[PlateRecognizer] Sending frame (\(jpegData.count / 1024)KB)...")

        let boundary = UUID().uuidString
        var request = URLRequest(url: apiURL)
        request.httpMethod = "POST"
        request.setValue("Token \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"regions\"\r\n\r\n".data(using: .utf8)!)
        body.append("[\"us-pa\", \"us-nj\"]\r\n".data(using: .utf8)!)

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"upload\"; filename=\"frame.jpg\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(jpegData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let task = session.dataTask(with: request) { [weak self] data, response, error in
            guard let self else { return }
            self.lock.lock(); self.inFlight = false; self.lock.unlock()

            if let error = error {
                print("[PlateRecognizer] Network error: \(error.localizedDescription)")
                completion(RecognitionResult(plates: [], diagnostics: []))
                return
            }

            if let httpResponse = response as? HTTPURLResponse {
                print("[PlateRecognizer] HTTP \(httpResponse.statusCode)")
                if httpResponse.statusCode != 200 {
                    if let data = data, let body = String(data: data, encoding: .utf8) {
                        print("[PlateRecognizer] Response: \(body.prefix(500))")
                    }
                    completion(RecognitionResult(plates: [], diagnostics: []))
                    return
                }
            }

            guard let data = data else {
                print("[PlateRecognizer] No data in response")
                completion(RecognitionResult(plates: [], diagnostics: []))
                return
            }

            do {
                let result = try self.parseResponse(data, imageWidth: imageWidth, imageHeight: imageHeight)
                print("[PlateRecognizer] Found \(result.plates.count) plates")
                completion(result)
            } catch {
                print("[PlateRecognizer] Parse error: \(error)")
                if let raw = String(data: data, encoding: .utf8) {
                    print("[PlateRecognizer] Raw: \(raw.prefix(500))")
                }
                completion(RecognitionResult(plates: [], diagnostics: []))
            }
        }
        task.resume()
    }

    private func parseResponse(_ data: Data, imageWidth: Int = 1920, imageHeight: Int = 1080) throws -> RecognitionResult {
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            print("[PlateRecognizer] Could not parse JSON")
            return RecognitionResult(plates: [], diagnostics: [])
        }

        let now = Date()
        var plates: [RecognizedPlate] = []
        var diagnostics: [DiagnosticEntry] = []

        guard let results = json["results"] as? [[String: Any]] else {
            if let detail = json["detail"] as? String {
                print("[PlateRecognizer] API error detail: \(detail)")
            } else {
                print("[PlateRecognizer] No 'results' key in response: \(json.keys)")
            }
            return RecognitionResult(plates: [], diagnostics: [])
        }

        for result in results {
            guard let plateText = result["plate"] as? String,
                  let score = result["score"] as? Double else {
                print("[PlateRecognizer] Missing plate/score in result")
                continue
            }

            let dscore = (result["dscore"] as? Double) ?? 0
            let box = (result["box"] as? [String: Any]) ?? [:]

            let normalized = PlatePatternMatcher.normalize(plateText.uppercased())

            let xmin = (box["xmin"] as? Double) ?? 0
            let ymin = (box["ymin"] as? Double) ?? 0
            let xmax = (box["xmax"] as? Double) ?? 0
            let ymax = (box["ymax"] as? Double) ?? 0
            let w = xmax - xmin
            let h = ymax - ymin
            let imgW = Double(imageWidth > 0 ? imageWidth : 1920)
            let imgH = Double(imageHeight > 0 ? imageHeight : 1080)
            let boundingBox = CGRect(x: xmin / imgW, y: ymin / imgH, width: w / imgW, height: h / imgH)
            let aspect = h > 0 ? w / h : 0

            let candidates = (result["candidates"] as? [[String: Any]]) ?? []
            let alternates = candidates.dropFirst().prefix(4).compactMap { c -> String? in
                guard let p = c["plate"] as? String else { return nil }
                let norm = PlatePatternMatcher.normalize(p.uppercased())
                return norm != normalized ? norm : nil
            }

            let confidence = Float(score)

            diagnostics.append(DiagnosticEntry(
                timestamp: now,
                rawText: plateText.uppercased(),
                normalizedText: normalized,
                confidence: confidence,
                boundingBox: boundingBox,
                aspectRatio: aspect,
                accepted: true,
                rejectionReason: ""
            ))

            plates.append(RecognizedPlate(
                text: normalized,
                confidence: confidence,
                boundingBox: boundingBox,
                timestamp: now,
                alternates: alternates
            ))

            let region = (result["region"] as? [String: Any])?["code"] as? String ?? "?"
            print("[PlateRecognizer] PLATE: \(normalized) conf=\(String(format: "%.3f", score)) det=\(String(format: "%.3f", dscore)) region=\(region)")
        }

        return RecognitionResult(plates: plates, diagnostics: diagnostics)
    }

    private func pixelBufferToJPEG(_ pixelBuffer: CVPixelBuffer, quality: CGFloat) -> Data? {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = ciContext.createCGImage(ciImage, from: ciImage.extent) else {
            print("[PlateRecognizer] CIContext.createCGImage failed")
            return nil
        }
        let uiImage = UIImage(cgImage: cgImage)
        let data = uiImage.jpegData(compressionQuality: quality)
        if data == nil {
            print("[PlateRecognizer] jpegData returned nil")
        }
        return data
    }
}
