import Foundation
import SwiftData

@Model
final class PendingTicket {
    var ticketId: String
    var plate: String
    var lot: String
    var violationType: String
    var confidence: Double
    var cameraName: String
    var photoPath: String?
    var issuedAt: Date
    var uploaded: Bool

    init(
        plate: String,
        lot: String,
        violationType: String,
        confidence: Double,
        cameraName: String = "",
        photoPath: String? = nil
    ) {
        self.ticketId = UUID().uuidString
        self.plate = plate
        self.lot = lot
        self.violationType = violationType
        self.confidence = confidence
        self.cameraName = cameraName
        self.photoPath = photoPath
        self.issuedAt = Date()
        self.uploaded = false
    }
}
