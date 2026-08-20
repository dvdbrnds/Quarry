import Foundation
import CoreMotion

@MainActor
final class MotionSpeedService: ObservableObject {
    nonisolated static let shared = MotionSpeedService()

    enum MovementMode: String {
        case stationary = "Stationary"
        case walking = "Walking"
        case vehicle = "Vehicle"
    }

    @Published private(set) var mode: MovementMode = .stationary {
        didSet {
            switch mode {
            case .stationary: _frameSkipFloor.value = 4
            case .walking: _frameSkipFloor.value = 3
            case .vehicle: _frameSkipFloor.value = 1
            }
        }
    }
    @Published private(set) var speedMPS: Double = 0

    /// Adaptive scanning parameters driven by motion state
    var confirmationThreshold: Int {
        switch mode {
        case .stationary: return 3
        case .walking: return 2
        case .vehicle: return 2
        }
    }

    var dedupWindow: TimeInterval {
        switch mode {
        case .stationary: return 60
        case .walking: return 45
        case .vehicle: return 15
        }
    }

    /// Thread-safe: read from any queue via atomic backing store
    nonisolated var frameSkipFloor: Int {
        _frameSkipFloor.value
    }

    /// Minimum seconds between processing the same bounding-box region
    var regionCooldown: TimeInterval {
        switch mode {
        case .stationary: return 8
        case .walking: return 4
        case .vehicle: return 0.5
        }
    }

    private let _frameSkipFloor = AtomicInt(2)

    private let motionManager = CMMotionActivityManager()
    private let pedometer = CMPedometer()
    private var accelerometerTimer: Timer?

    private let accelManager = CMMotionManager()
    private var accelSamples: [Double] = []
    private let sampleWindow = 20

    private init() {}

    func start() {
        guard CMMotionActivityManager.isActivityAvailable() else {
            startAccelerometerFallback()
            return
        }

        motionManager.startActivityUpdates(to: .main) { [weak self] activity in
            guard let activity, let self else { return }
            Task { @MainActor in
                self.updateFromActivity(activity)
            }
        }

        startAccelerometerFallback()
    }

    func stop() {
        motionManager.stopActivityUpdates()
        accelManager.stopAccelerometerUpdates()
        accelerometerTimer?.invalidate()
        accelerometerTimer = nil
    }

    private func updateFromActivity(_ activity: CMMotionActivity) {
        if activity.automotive {
            mode = .vehicle
        } else if activity.walking || activity.running || activity.cycling {
            mode = .walking
        } else if activity.stationary {
            mode = .stationary
        }
    }

    /// Use raw accelerometer magnitude variance to estimate movement when
    /// CMMotionActivity is slow to update or unavailable.
    private func startAccelerometerFallback() {
        guard accelManager.isAccelerometerAvailable else { return }
        accelManager.accelerometerUpdateInterval = 0.1

        accelManager.startAccelerometerUpdates(to: .main) { [weak self] data, _ in
            guard let data, let self else { return }
            let magnitude = sqrt(
                data.acceleration.x * data.acceleration.x +
                data.acceleration.y * data.acceleration.y +
                data.acceleration.z * data.acceleration.z
            )
            Task { @MainActor in
                self.processAccelSample(magnitude)
            }
        }
    }

    private func processAccelSample(_ magnitude: Double) {
        accelSamples.append(magnitude)
        if accelSamples.count > sampleWindow {
            accelSamples.removeFirst()
        }
        guard accelSamples.count >= sampleWindow else { return }

        let mean = accelSamples.reduce(0, +) / Double(accelSamples.count)
        let variance = accelSamples.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / Double(accelSamples.count)

        // Variance thresholds calibrated for iPhone in hand vs. vehicle mount:
        // - Stationary/table: variance < 0.002
        // - Walking: 0.002 – 0.05
        // - Vehicle: > 0.05 (road vibration + turns produce high variance)
        let inferred: MovementMode
        if variance < 0.002 {
            inferred = .stationary
        } else if variance < 0.05 {
            inferred = .walking
        } else {
            inferred = .vehicle
        }

        // Only override CMMotionActivity if it's stuck on stationary but accel
        // clearly shows movement (CMMotionActivity can lag a few seconds).
        if mode == .stationary && inferred != .stationary {
            mode = inferred
        } else if mode == .walking && inferred == .vehicle {
            mode = .vehicle
        } else if inferred == .stationary && mode != .stationary {
            // Require sustained stillness before downgrading
            let recentVariances = accelSamples.suffix(sampleWindow)
            let allCalm = recentVariances.allSatisfy { abs($0 - 1.0) < 0.05 }
            if allCalm {
                mode = .stationary
            }
        }

        speedMPS = variance * 20 // rough proportional estimate for UI display
    }
}

/// Simple lock-free atomic integer for cross-queue access.
final class AtomicInt: @unchecked Sendable {
    private var _value: Int
    private let lock = NSLock()

    init(_ initial: Int) { _value = initial }

    var value: Int {
        get { lock.withLock { _value } }
        set { lock.withLock { _value = newValue } }
    }
}
