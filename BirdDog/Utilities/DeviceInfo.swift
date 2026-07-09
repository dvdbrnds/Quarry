import Foundation
import UIKit

enum DeviceInfo {

    static var modelIdentifier: String {
        var size = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        var machine = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.machine", &machine, &size, nil, 0)
        return String(cString: machine)
    }

    static var modelName: String {
        mapIdentifier(modelIdentifier)
    }

    static var chipName: String {
        let id = modelIdentifier
        if id.hasPrefix("iPad16,") || id.hasPrefix("iPad14,") { return "Apple M2" }
        if id.hasPrefix("iPad13,") { return "Apple M1" }
        if id.hasPrefix("iPad15,") { return "Apple M4" }
        if id.hasPrefix("iPad12,") { return "Apple A14 Bionic" }
        if id.hasPrefix("iPad11,") { return "Apple A12 Bionic" }
        if id.hasPrefix("iPad8,")  { return "Apple A12X Bionic" }
        if id.hasPrefix("iPad7,")  { return "Apple A10X Fusion" }
        if id == "arm64" || id == "x86_64" { return "Simulator" }
        return "Unknown"
    }

    static var systemVersion: String {
        UIDevice.current.systemVersion
    }

    static var deviceModel: String {
        UIDevice.current.model
    }

    static var summary: String {
        "\(modelName) (\(chipName)) — iPadOS \(systemVersion)"
    }

    // MARK: - iPad identifier mapping

    private static func mapIdentifier(_ id: String) -> String {
        let known: [String: String] = [
            // iPad Pro M4
            "iPad16,3": "iPad Pro 13\" (M4)",
            "iPad16,4": "iPad Pro 13\" (M4)",
            "iPad16,5": "iPad Pro 11\" (M4)",
            "iPad16,6": "iPad Pro 11\" (M4)",
            // iPad Air M2
            "iPad14,8": "iPad Air 13\" (M2)",
            "iPad14,9": "iPad Air 13\" (M2)",
            "iPad14,10": "iPad Air 11\" (M2)",
            "iPad14,11": "iPad Air 11\" (M2)",
            // iPad Air M1
            "iPad13,16": "iPad Air 5th gen (M1)",
            "iPad13,17": "iPad Air 5th gen (M1)",
            // iPad Pro M2
            "iPad14,3": "iPad Pro 11\" (M2)",
            "iPad14,4": "iPad Pro 11\" (M2)",
            "iPad14,5": "iPad Pro 12.9\" (M2)",
            "iPad14,6": "iPad Pro 12.9\" (M2)",
            // iPad Pro M1
            "iPad13,4": "iPad Pro 11\" (M1)",
            "iPad13,5": "iPad Pro 11\" (M1)",
            "iPad13,6": "iPad Pro 11\" (M1)",
            "iPad13,7": "iPad Pro 11\" (M1)",
            "iPad13,8": "iPad Pro 12.9\" (M1)",
            "iPad13,9": "iPad Pro 12.9\" (M1)",
            "iPad13,10": "iPad Pro 12.9\" (M1)",
            "iPad13,11": "iPad Pro 12.9\" (M1)",
            // iPad 10th gen
            "iPad13,18": "iPad 10th gen (A14)",
            "iPad13,19": "iPad 10th gen (A14)",
            // iPad mini 6
            "iPad14,1": "iPad mini 6 (A15)",
            "iPad14,2": "iPad mini 6 (A15)",
            // iPad 9th gen
            "iPad12,1": "iPad 9th gen (A13)",
            "iPad12,2": "iPad 9th gen (A13)",
            // iPad Air 4
            "iPad13,1": "iPad Air 4th gen (A14)",
            "iPad13,2": "iPad Air 4th gen (A14)",
        ]
        return known[id] ?? "\(UIDevice.current.model) (\(id))"
    }
}
