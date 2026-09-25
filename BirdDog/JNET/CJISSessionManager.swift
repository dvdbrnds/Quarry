import Foundation
import Combine

/// CJIS Security Policy v6.1 — AC-11, AC-12.
/// Tracks 30-minute inactivity timeout for JNET features.
/// Clears CJI data when the session expires.
@MainActor
final class CJISSessionManager: ObservableObject {
    static let shared = CJISSessionManager()

    /// Whether the JNET session is currently active (not timed out).
    @Published private(set) var isSessionActive = false

    /// Timestamp of the last JNET interaction.
    private var lastActivity: Date?

    /// Session timeout in seconds (30 minutes).
    private let timeoutSeconds: TimeInterval = 30 * 60

    private var timer: Timer?

    private init() {}

    /// Record a JNET interaction, resetting the inactivity timer.
    func recordActivity() {
        lastActivity = Date()
        isSessionActive = true
        startTimer()
    }

    /// Check if the session has timed out. Returns `true` if active.
    func checkSession() -> Bool {
        guard let last = lastActivity else {
            isSessionActive = false
            return false
        }

        if Date().timeIntervalSince(last) > timeoutSeconds {
            expireSession()
            return false
        }

        return true
    }

    /// Force-expire the session and clear all CJI data.
    func expireSession() {
        isSessionActive = false
        lastActivity = nil
        stopTimer()
        CJIDataStore.shared.clear()
    }

    /// Called when the app enters background or screen locks.
    func handleBackgroundTransition() {
        CJIDataStore.shared.clear()
    }

    /// Called when the app returns to foreground.
    func handleForegroundTransition() {
        if !checkSession() {
            // Session expired while in background
            CJIDataStore.shared.clear()
        }
    }

    /// Called on logout.
    func reset() {
        expireSession()
    }

    // MARK: - Timer

    private func startTimer() {
        stopTimer()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if !self.checkSession() {
                    self.stopTimer()
                }
            }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }
}
