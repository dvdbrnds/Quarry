import SwiftUI
import SwiftData
import UIKit
import os.log

private let bootLog = OSSignposter(subsystem: "com.birddog", category: "Boot")
private let bootClock = ContinuousClock()
private var processStart: ContinuousClock.Instant = .now

@main
struct BirdDogApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appSettings = AppSettings.shared
    @StateObject private var officerAuth = OfficerAuthService.shared
    @State private var onboardingComplete = false

    init() {
        processStart = .now
        print("[BOOT] App struct init at \(processStart)")
    }

    var body: some Scene {
        WindowGroup {
            if !(appSettings.isServerConfigured || onboardingComplete) {
                OnboardingView {
                    onboardingComplete = true
                    HoundDogSyncService.shared.startIfConfigured()
                }
            } else if !officerAuth.isLoggedIn {
                OfficerLoginView()
            } else {
                ContentView()
                    .task { await backgroundInit() }
                    .onAppear {
                        let elapsed = bootClock.now - processStart
                        print("[BOOT] ✅ ContentView VISIBLE after \(elapsed)")
                    }
            }
        }
    }
}

extension BirdDogApp {
    @MainActor
    private func backgroundInit() async {
        print("[BOOT] backgroundInit started at \(bootClock.now - processStart)")

        let container = await Task.detached(priority: .userInitiated) {
            let t = ContinuousClock().now
            let c = PlateDatabase.createContainer()
            print("[BOOT]   createContainer took \(ContinuousClock().now - t)")
            return c
        }.value

        print("[BOOT] container ready at \(bootClock.now - processStart)")
        PlateDatabase.warmUp(container: container)
        print("[BOOT] warmUp done at \(bootClock.now - processStart)")

        GeofenceService.shared.configure(container: container)
        print("[BOOT] geofence configured at \(bootClock.now - processStart)")
        GeofenceService.shared.requestPermissionAndStart()

        HoundDogSyncService.shared.startIfConfigured()
        print("[BOOT] sync started at \(bootClock.now - processStart)")

        Task {
            PlateDatabase.shared.seedIfNeeded()
            print("[BOOT] seedIfNeeded done at \(bootClock.now - processStart)")
            PlateDatabase.shared.pruneExpiredPermits()
            if PrinterService.shared.hasSavedPrinter {
                PrinterService.shared.reconnectSaved()
            }
        }
    }
}

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        print("[BOOT] didFinishLaunching at \(bootClock.now - processStart)")
        UIApplication.shared.registerForRemoteNotifications()
        return true
    }

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        return [.portrait, .portraitUpsideDown]
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        let token = deviceToken.map { String(format: "%02.2hhx", $0) }.joined()
        Task { @MainActor in
            await PushTokenService.shared.registerToken(token)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        print("[Push] Registration failed: \(error.localizedDescription)")
    }

    func application(
        _ application: UIApplication,
        didReceiveRemoteNotification userInfo: [AnyHashable: Any],
        fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void
    ) {
        Task { @MainActor in
            await HoundDogSyncService.shared.syncNow()
            completionHandler(.newData)
        }
    }
}
