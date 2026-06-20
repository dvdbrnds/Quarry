import SwiftUI

struct OfficerLoginView: View {
    @ObservedObject private var auth = OfficerAuthService.shared
    @ObservedObject private var appSettings = AppSettings.shared

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "shield.checkered")
                .font(.system(size: 72))
                .foregroundStyle(Color.accentColor)

            VStack(spacing: 12) {
                Text("Bird Dog")
                    .font(.largeTitle.bold())

                Text("Officer Sign-In Required")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }

            VStack(spacing: 8) {
                Text("Sign in with your campus credentials to issue and sign tickets.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            if let error = auth.loginError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            Spacer()

            Button {
                auth.login()
            } label: {
                HStack(spacing: 10) {
                    if auth.isLoggingIn {
                        ProgressView()
                            .tint(.white)
                    }
                    Image(systemName: "person.badge.key.fill")
                    Text("Sign In with SSO")
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.accentColor)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            }
            .padding(.horizontal, 32)
            .disabled(auth.isLoggingIn || !appSettings.isOktaConfigured)

            if !appSettings.isOktaConfigured {
                Text("Pair this device with your Quarry server first.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            Spacer()
                .frame(height: 40)
        }
    }
}
