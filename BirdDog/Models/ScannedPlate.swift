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
    var violationPhotoPath: String?
    /// The lot in which this plate was ticketed (nil if not ticketed)
    var ticketedInLot: String?
    /// Path to JPEG snapshot captured at the moment of plate confirmation
    /// (only populated when Diagnostic Captures is enabled in settings).
    var diagnosticImagePath: String?
    /// Legacy Omnigo record info, if this plate has history in the legacy dataset.
    var legacyInfo: LegacyPlateInfo?

    init(
        text: String,
        timestamp: Date,
        confidence: Float,
        framesConfirmed: Int,
        authStatus: PlateStatus,
        matchMethod: MatchMethod,
        matchedPlate: String,
        cameraName: String = "",
        detectionLatency: TimeInterval = 0,
        violationPhotoPath: String? = nil,
        ticketedInLot: String? = nil,
        diagnosticImagePath: String? = nil,
        legacyInfo: LegacyPlateInfo? = nil
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
        self.violationPhotoPath = violationPhotoPath
        self.ticketedInLot = ticketedInLot
        self.diagnosticImagePath = diagnosticImagePath
        self.legacyInfo = legacyInfo
    }
}

struct LegacyPlateInfo: Sendable, Codable, Equatable {
    let ownerName: String
    let permitType: String
    let lotZone: String
    let vehicleDescription: String
    let source: String
}

struct DiagnosticEntry: Sendable, Codable {
    let timestamp: Date
    let rawText: String
    let normalizedText: String
    let confidence: Float
    let boundingBox: CGRect
    let aspectRatio: Double
    let accepted: Bool
    let rejectionReason: String
}
