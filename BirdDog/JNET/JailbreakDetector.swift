import Foundation
import UIKit

/// CJIS Security Policy v6.1 — 5.20.
/// Detects jailbroken devices. If any check fails, JNET features are disabled.
struct JailbreakDetector {

    /// Returns `true` if the device appears to be jailbroken.
    static func isJailbroken() -> Bool {
        // 1. Check for known jailbreak app URL schemes
        if canOpenJailbreakApps() { return true }

        // 2. Check for jailbreak file paths
        if jailbreakFilesExist() { return true }

        // 3. Check if we can write outside the sandbox
        if canWriteOutsideSandbox() { return true }

        // 4. Check for dylib injection (DYLD environment)
        if isDylibInjected() { return true }

        return false
    }

    // MARK: - Checks

    private static func canOpenJailbreakApps() -> Bool {
        let schemes = [
            "cydia://",
            "sileo://",
            "zebra://",
            "undecimus://",
            "filza://",
        ]
        for scheme in schemes {
            if let url = URL(string: scheme),
               UIApplication.shared.canOpenURL(url) {
                return true
            }
        }
        return false
    }

    private static func jailbreakFilesExist() -> Bool {
        let paths = [
            "/Applications/Cydia.app",
            "/Applications/Sileo.app",
            "/Applications/Zebra.app",
            "/Library/MobileSubstrate/MobileSubstrate.dylib",
            "/usr/sbin/sshd",
            "/usr/bin/ssh",
            "/usr/libexec/sftp-server",
            "/bin/bash",
            "/etc/apt",
            "/private/var/lib/apt",
            "/private/var/lib/cydia",
            "/private/var/stash",
            "/private/var/mobile/Library/SBSettings/Themes",
            "/usr/sbin/frida-server",
            "/usr/bin/cycript",
            "/usr/local/bin/cycript",
            "/usr/lib/libcycript.dylib",
        ]
        let fm = FileManager.default
        for path in paths {
            if fm.fileExists(atPath: path) {
                return true
            }
        }
        return false
    }

    private static func canWriteOutsideSandbox() -> Bool {
        let testPath = "/private/jailbreak_test_\(UUID().uuidString)"
        do {
            try "test".write(toFile: testPath, atomically: true, encoding: .utf8)
            try FileManager.default.removeItem(atPath: testPath)
            return true
        } catch {
            return false
        }
    }

    private static func isDylibInjected() -> Bool {
        // Check DYLD_INSERT_LIBRARIES environment variable
        if let _ = getenv("DYLD_INSERT_LIBRARIES") {
            return true
        }

        // Check loaded dylib count for suspicious libraries
        let suspiciousLibs = [
            "MobileSubstrate",
            "SubstrateLoader",
            "cycript",
            "SSLKillSwitch",
            "FridaGadget",
            "frida",
            "libReveal",
        ]

        for i in 0..<_dyld_image_count() {
            if let name = _dyld_get_image_name(i) {
                let imageName = String(cString: name)
                for lib in suspiciousLibs {
                    if imageName.lowercased().contains(lib.lowercased()) {
                        return true
                    }
                }
            }
        }

        return false
    }
}
