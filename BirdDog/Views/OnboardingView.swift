import SwiftUI

struct OnboardingView: View {
    @ObservedObject private var appSettings = AppSettings.shared
    @State private var showQRScanner = false
    var onComplete: () -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                Image(systemName: "car.side.front.open")
                    .font(.system(size: 72))
                    .foregroundStyle(Color.accentColor)

                VStack(spacing: 12) {
                    Text("Bird Dog")
                        .font(.largeTitle.bold())

                    Text("License Plate Enforcement")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }

                VStack(spacing: 8) {
                    Text("To get started, scan the pairing QR code from your school's Quarry dashboard.")
                        .font(.body)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }

                Spacer()

                Button {
                    showQRScanner = true
                } label: {
                    Label("Scan Pairing Code", systemImage: "qrcode.viewfinder")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.accentColor)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .padding(.horizontal, 32)

                Button("Configure Manually") {
                    onComplete()
                }
                .font(.callout)
                .foregroundStyle(.secondary)
                .padding(.bottom, 32)
            }
            .fullScreenCover(isPresented: $showQRScanner) {
                QRScannerView(isPresented: $showQRScanner, onPaired: onComplete)
            }
        }
    }
}
