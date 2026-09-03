import SwiftUI

struct OfficerLoginView: View {
    @ObservedObject private var auth = OfficerAuthService.shared
    @ObservedObject private var appSettings = AppSettings.shared
    @State private var showDemoLogin = false
    @State private var demoUsername = ""
    @State private var demoPassword = ""

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

            Button {
                showDemoLogin.toggle()
            } label: {
                Text("Demo Login")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()
                .frame(height: 40)
        }
        .sheet(isPresented: $showDemoLogin) {
            NavigationStack {
                VStack(spacing: 20) {
                    Text("Demo Access")
                        .font(.headline)
                        .padding(.top, 24)

                    Text("For app review purposes only.")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    TextField("Username", text: $demoUsername)
                        .textContentType(.username)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .padding()
                        .background(Color(.systemGray6))
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    SecureField("Password", text: $demoPassword)
                        .textContentType(.password)
                        .padding()
                        .background(Color(.systemGray6))
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    Button {
                        auth.demoLogin(username: demoUsername, password: demoPassword)
                        if auth.isLoggedIn {
                            showDemoLogin = false
                        }
                    } label: {
                        Text("Sign In")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.accentColor)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 14))
                    }

                    Spacer()
                }
                .padding(.horizontal, 32)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { showDemoLogin = false }
                    }
                }
            }
            .presentationDetents([.medium])
        }
    }
}
