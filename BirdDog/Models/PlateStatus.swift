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

    var displayType: String {
        let primary = permitType.components(separatedBy: ",").first?
            .trimmingCharacters(in: .whitespaces) ?? permitType
        return primary.capitalized
    }
}

enum PlateStatus: Sendable, Equatable, Codable {
    case authorized(permit: PermitInfo)
    case wrongLot(permit: PermitInfo, expectedLot: String, actualLot: String)
    case expired(permit: PermitInfo)
    case unknown
    case unchecked

    var label: String {
        switch self {
        case .authorized: return "Authorized"
        case .wrongLot: return "Wrong Lot"
        case .expired: return "Expired"
        case .unknown: return "Unknown"
        case .unchecked: return ""
        }
    }

    var color: Color {
        switch self {
        case .authorized: return .green
        case .wrongLot: return .orange
        case .expired: return .yellow
        case .unknown: return .red
        case .unchecked: return .white
        }
    }

    var systemImage: String {
        switch self {
        case .authorized: return "checkmark.shield.fill"
        case .wrongLot: return "location.slash.fill"
        case .expired: return "exclamationmark.triangle.fill"
        case .unknown: return "xmark.shield.fill"
        case .unchecked: return "shield.slash"
        }
    }

    var permit: PermitInfo? {
        switch self {
        case .authorized(let p), .wrongLot(let p, _, _), .expired(let p):
            return p
        case .unknown, .unchecked:
            return nil
        }
    }
}
