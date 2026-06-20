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

    // Moving violation fields
    var ticketCategory: String
    var locationLat: Double?
    var locationLng: Double?
    var locationText: String?
    var vehicleDescription: String?
    var officerNotes: String?
    var driverName: String?
    var driverLicense: String?

    // Officer identity (ticket signature)
    var officerName: String?
    var officerEmail: String?

    // Permit holder info (when available from scan)
    var ownerName: String?
    var permitNumber: String?

    // Response from server
    var paymentUrl: String?
    var fineAmount: String?
    var offenseNumber: Int?

    init(
        plate: String,
        lot: String,
        violationType: String,
        confidence: Double,
        cameraName: String = "",
        photoPath: String? = nil,
        ticketCategory: String = "parking",
        locationLat: Double? = nil,
        locationLng: Double? = nil,
        locationText: String? = nil,
        vehicleDescription: String? = nil,
        officerNotes: String? = nil,
        driverName: String? = nil,
        driverLicense: String? = nil,
        officerName: String? = nil,
        officerEmail: String? = nil,
        ownerName: String? = nil,
        permitNumber: String? = nil
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
        self.ticketCategory = ticketCategory
        self.locationLat = locationLat
        self.locationLng = locationLng
        self.locationText = locationText
        self.vehicleDescription = vehicleDescription
        self.officerNotes = officerNotes
        self.driverName = driverName
        self.driverLicense = driverLicense
        self.officerName = officerName
        self.officerEmail = officerEmail
        self.ownerName = ownerName
        self.permitNumber = permitNumber
    }
}
