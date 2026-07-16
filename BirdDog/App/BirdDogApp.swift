import SwiftUI
import SwiftData
import UIKit

@main
struct BirdDogApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appSettings = AppSettings.shared
    @StateObject private var officerAuth = OfficerAuthService.shared
    @State private var onboardingComplete = false
    @State private var bootReady = false

    var body: some Scene {
        WindowGroup {
            if !bootReady {
                BootSplashView()
                    .task { await boot() }
            } else if !(appSettings.isServerConfigured || onboardingComplete) {
                OnboardingView {
                    onboardingComplete = true
                    HoundDogSyncService.shared.startIfConfigured()
                }
            } else if !officerAuth.isLoggedIn {
                OfficerLoginView()
            } else {
                ContentView()
                    .task { await deferredBootWork() }
            }
        }
    }
}

struct BootSplashView: View {
    var body: some View {
        ZStack {
            Color(red: 0.02, green: 0.04, blue: 0.10)
                .ignoresSafeArea()
            ProgressView()
                .tint(.white)
                .scaleEffect(1.5)
        }
        .preferredColorScheme(.dark)
    }
}

extension BirdDogApp {
    @MainActor
    private func boot() async {
        let container = await Task.detached(priority: .userInitiated) {
            PlateDatabase.createContainer()
        }.value

        PlateDatabase.warmUp(container: container)

        GeofenceService.shared.configure(container: container)
        GeofenceService.shared.requestPermissionAndStart()
        bootReady = true
    }

    @MainActor
    private func deferredBootWork() async {
        HoundDogSyncService.shared.startIfConfigured()
        PlateDatabase.shared.pruneExpiredPermits()
        if PrinterService.shared.hasSavedPrinter {
            PrinterService.shared.reconnectSaved()
        }
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
