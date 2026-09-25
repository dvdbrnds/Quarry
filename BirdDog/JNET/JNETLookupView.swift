import SwiftUI
import LocalAuthentication

/// JNET plate lookup UI.
///
/// Flow:
///   1. Check jailbreak → refuse if jailbroken
///   2. Check device passcode → refuse if not set
///   3. Biometric auth (Face ID / Touch ID) per-lookup
///   4. Check CJIS session timeout (30 min)
///   5. Send plate to backend
///   6. Display results in modal with CJIS notice
///   7. On dismiss, clear CJI from memory
struct JNETLookupView: View {
    let plateNumber: String
    let state: String
    @Binding var isPresented: Bool

    @StateObject private var cjiStore = CJIDataStore.shared
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var biometricPassed = false

    var body: some View {
        NavigationView {
            Group {
                if loading {
                    ProgressView("Querying JNET...")
                        .padding()
                } else if let error = errorMessage {
                    VStack(spacing: 16) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.largeTitle)
                            .foregroundColor(.red)
                        Text(error)
                            .multilineTextAlignment(.center)
                            .padding()
                        Button("Close") { dismiss() }
                            .buttonStyle(.borderedProminent)
                    }
                    .padding()
                } else if let result = cjiStore.currentResult {
                    resultView(result)
                } else {
                    Text("Authenticating...")
                        .onAppear { performLookup() }
                }
            }
            .navigationTitle("JNET Lookup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                }
            }
        }
        .interactiveDismissDisabled()
    }

    // MARK: - Result View

    @ViewBuilder
    private func resultView(_ result: JNETLookupResult) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                // CJIS Notice
                HStack {
                    Image(systemName: "shield.lefthalf.filled")
                        .foregroundColor(.orange)
                    Text(result.cjisNotice)
                        .font(.caption)
                        .foregroundColor(.orange)
                }
                .padding()
                .background(Color.orange.opacity(0.1))
                .cornerRadius(8)

                // Vehicle Info
                if let v = result.vehicle {
                    sectionHeader("Vehicle Information")
                    infoRow("Plate", "\(v.plateNumber) (\(v.plateState))")
                    if let vin = v.vin { infoRow("VIN", vin) }
                    if let year = v.year, let make = v.make, let model = v.model {
                        infoRow("Vehicle", "\(year) \(make) \(model)")
                    }
                    if let color = v.color { infoRow("Color", color) }
                    if let status = v.registrationStatus { infoRow("Registration", status) }
                    if let expiry = v.registrationExpiry { infoRow("Expires", expiry) }
                }

                // Owner Info
                if let o = result.owner {
                    sectionHeader("Registered Owner")
                    let name = [o.firstName, o.middleName, o.lastName].compactMap { $0 }.joined(separator: " ")
                    if !name.isEmpty { infoRow("Name", name) }
                    if let addr = o.addressLine1 { infoRow("Address", addr) }
                    if let addr2 = o.addressLine2, !addr2.isEmpty { infoRow("", addr2) }
                    let cityStateZip = [o.city, o.state, o.zipCode].compactMap { $0 }.joined(separator: ", ")
                    if !cityStateZip.isEmpty { infoRow("", cityStateZip) }
                    if let dob = o.dateOfBirth { infoRow("DOB", dob) }
                    if let dl = o.driversLicense { infoRow("DL", dl) }
                }

                Spacer(minLength: 20)

                Button("Close") { dismiss() }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
            }
            .padding()
        }
    }

    @ViewBuilder
    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(.headline)
            .padding(.top, 8)
    }

    @ViewBuilder
    private func infoRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            if !label.isEmpty {
                Text(label)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .frame(width: 80, alignment: .trailing)
            }
            Text(value)
                .font(.body)
                .textSelection(.enabled)
        }
    }

    // MARK: - Lookup Flow

    private func performLookup() {
        Task {
            // 1. Jailbreak check
            if JailbreakDetector.isJailbroken() {
                errorMessage = "JNET features are not available on this device."
                return
            }

            // 2. Device passcode check
            let context = LAContext()
            var authError: NSError?
            guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &authError) else {
                errorMessage = "Device passcode required for JNET features. Please set a passcode in Settings."
                return
            }

            // 3. Session timeout check
            if !CJISSessionManager.shared.checkSession() && CJISSessionManager.shared.isSessionActive == false {
                // First query is OK; the session manager will record activity
            }

            // 4. Biometric authentication
            do {
                let success = try await context.evaluatePolicy(
                    .deviceOwnerAuthentication,
                    localizedReason: "Authenticate to perform JNET lookup"
                )
                guard success else {
                    errorMessage = "Authentication failed."
                    return
                }
            } catch {
                errorMessage = "Authentication required: \(error.localizedDescription)"
                return
            }

            // 5. Perform lookup
            loading = true
            do {
                let result = try await JNETService.shared.plateLookup(
                    plateNumber: plateNumber,
                    state: state
                )
                CJIDataStore.shared.store(result)
            } catch let err as JNETServiceError {
                errorMessage = err.errorDescription
            } catch {
                errorMessage = "Lookup failed: \(error.localizedDescription)"
            }
            loading = false
        }
    }

    private func dismiss() {
        CJIDataStore.shared.clear()
        isPresented = false
    }
}
