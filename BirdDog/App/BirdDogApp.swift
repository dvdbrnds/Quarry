import SwiftUI
import SwiftData
import UIKit

@main
struct BirdDogApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appSettings = AppSettings.shared
    @StateObject private var officerAuth = OfficerAuthService.shared
    @State private var onboardingComplete = false

    init() {
        let container = PlateDatabase.shared.container
        GeofenceService.shared.configure(container: container)
        GeofenceService.shared.requestPermissionAndStart()
        HoundDogSyncService.shared.startIfConfigured()
        Task.detached(priority: .utility) { @MainActor in
            PlateDatabase.shared.pruneExpiredPermits()
        }
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
            }
        }
        .modelContainer(PlateDatabase.shared.container)
    }
}

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UIApplication.shared.registerForRemoteNotifications()
        return true
    }

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        // Info.plist declares all orientations (Apple requirement) but the
        // enforcement UI is portrait-only. Allow upside-down for the vehicle
        // mount where the iPad is inverted.
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
