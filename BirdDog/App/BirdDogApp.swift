import SwiftUI
import SwiftData
import UIKit

@main
struct BirdDogApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appSettings = AppSettings.shared
    @State private var onboardingComplete = false

    init() {
        GeofenceService.shared.configure(container: PlateDatabase.shared.container)
        GeofenceService.shared.requestPermissionAndStart()
        HoundDogSyncService.shared.startIfConfigured()
    }

    var body: some Scene {
        WindowGroup {
            if appSettings.isServerConfigured || onboardingComplete {
                ContentView()
            } else {
                OnboardingView {
                    onboardingComplete = true
                    HoundDogSyncService.shared.startIfConfigured()
                }
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
