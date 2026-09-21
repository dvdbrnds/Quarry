import Foundation
import SwiftUI

struct PermitInfo: Sendable, Equatable, Codable {
    let ownerName: String
    let permitNumber: String
    let permitType: String
    let permitStatus: String
    let lotZone: String
    let vehicleDescription: String
    let plateState: String
    let issuedDate: Date
    let hcStatus: String
    let hcExpiry: Date?

    private static let displayNames: [String: String] = [
        "commuter_undergrad": "Commuter (Undergrad)",
        "commuter_grad": "Commuter (Grad)",
        "premium_commuter": "Premium Commuter",
        "north_premium_resident": "North Premium Resident",
        "north_guaranteed_resident": "North Guaranteed Resident",
        "steel_field_resident": "Steel Field Resident",
        "south_premium_resident": "South Premium Resident",
        "south_guaranteed_resident": "South Guaranteed Resident",
        "south_standalone": "South Third Party",
        "faculty_staff": "Faculty/Staff",
        "contracted_staff": "Contracted Staff",
        "local_resident": "Local Resident",
        "visitor_day": "Visitor (Day)",
        "visitor_vendor": "Vendor",
        "visitor_vendor_longterm": "Vendor (Long-term)",
        "visitor_contracted_staff": "Contracted Staff",
        "student_guest": "Student Guest",
        "vehicle_tag": "Vehicle Tag",
    ]

    var displayType: String {
        let primary = permitType.components(separatedBy: ",").first?
            .trimmingCharacters(in: .whitespaces) ?? permitType
        if let name = Self.displayNames[primary.lowercased()] {
            return name
        }
        return primary.replacingOccurrences(of: "_", with: " ").capitalized
    }

    var isHC: Bool {
        hcStatus == "temporary" || hcStatus == "permanent"
    }

    var isHCExpired: Bool {
        guard hcStatus == "temporary", let expiry = hcExpiry else { return false }
        return expiry < Date()
    }
}

enum PlateStatus: Sendable, Equatable, Codable {
    case authorized(permit: PermitInfo)
    case wrongLot(permit: PermitInfo, expectedLot: String, actualLot: String)
    case expired(permit: PermitInfo)
    case tagOnly(permit: PermitInfo)
    case unknown
    case unchecked
    case ticketed

    /// Brand signal green for plates allowed to park in this lot right now.
    static let allowedGreen = Color("BDSignalGreen")

    var label: String {
        switch self {
        case .authorized: return "Allowed"
        case .wrongLot: return "Wrong Lot"
        case .expired: return "Expired"
        case .tagOnly: return "No Permit"
        case .unknown: return "Unknown"
        case .unchecked: return ""
        case .ticketed: return "Ticketed"
        }
    }

    var color: Color {
        switch self {
        case .authorized: return Self.allowedGreen
        case .wrongLot: return .orange
        case .expired: return .yellow
        case .tagOnly: return .cyan
        case .unknown: return .red
        case .unchecked: return .white
        case .ticketed: return .purple
        }
    }

    var systemImage: String {
        switch self {
        case .authorized: return "checkmark.shield.fill"
        case .wrongLot: return "location.slash.fill"
        case .expired: return "exclamationmark.triangle.fill"
        case .tagOnly: return "person.badge.shield.checkmark.fill"
        case .unknown: return "xmark.shield.fill"
        case .unchecked: return "shield.slash"
        case .ticketed: return "doc.text.fill"
        }
    }

    var permit: PermitInfo? {
        switch self {
        case .authorized(let p), .wrongLot(let p, _, _), .expired(let p), .tagOnly(let p):
            return p
        case .unknown, .unchecked, .ticketed:
            return nil
        }
    }
}
