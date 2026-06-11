import Foundation
import CoreGraphics

struct RecognizedPlate: Sendable {
    let text: String
    let confidence: Float
    let boundingBox: CGRect
    let timestamp: Date
    let alternates: [String]
}

struct ScannedPlate: Identifiable, Sendable, Codable {
    let id: UUID
    let text: String
    let timestamp: Date
    let confidence: Float
    let framesConfirmed: Int
    let authStatus: PlateStatus
    let matchMethod: MatchMethod
    let matchedPlate: String
    let cameraName: String
    /// Seconds between first candidate sighting and confirmation
    let detectionLatency: TimeInterval

    init(
        text: String,
        timestamp: Date,
        confidence: Float,
        framesConfirmed: Int,
        authStatus: PlateStatus,
        matchMethod: MatchMethod,
        matchedPlate: String,
        cameraName: String = "",
        detectionLatency: TimeInterval = 0
    ) {
        self.id = UUID()
        self.text = text
        self.timestamp = timestamp
        self.confidence = confidence
        self.framesConfirmed = framesConfirmed
        self.authStatus = authStatus
        self.matchMethod = matchMethod
        self.matchedPlate = matchedPlate
        self.cameraName = cameraName
        self.detectionLatency = detectionLatency
    }
}

struct DiagnosticEntry: Sendable {
    let timestamp: Date
    let rawText: String
    let normalizedText: String
    let confidence: Float
    let boundingBox: CGRect
    let aspectRatio: Double
    let accepted: Bool
    let rejectionReason: String
}
