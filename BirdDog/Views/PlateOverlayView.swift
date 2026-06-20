import SwiftUI

struct PlateOverlayView: View {

    let plates: [RecognizedPlate]
    let authStatus: PlateStatus

    private var latestPlate: String? {
        plates.first?.text
    }

    private var backgroundColor: Color {
        switch authStatus {
        case .authorized: return .green.opacity(0.75)
        case .wrongLot: return .orange.opacity(0.8)
        case .expired: return .yellow.opacity(0.75)
        case .unknown: return .red.opacity(0.8)
        case .ticketed: return .purple.opacity(0.75)
        case .unchecked: return .black.opacity(0.65)
        }
    }

    private var textColor: Color {
        switch authStatus {
        case .expired: return .black
        default: return .white
        }
    }

    var body: some View {
        VStack {
            Spacer()
            if let plate = latestPlate {
                VStack(spacing: 4) {
                    Text(plate)
                        .font(.system(size: 36, weight: .bold, design: .monospaced))
                        .foregroundStyle(textColor)

                    if authStatus != .unchecked {
                        HStack(spacing: 4) {
                            Image(systemName: authStatus.systemImage)
                                .font(.caption)
                            Text(authStatus.label.uppercased())
                                .font(.caption.bold())
                        }
                        .foregroundStyle(textColor)
                    }

                    if case .wrongLot(let permit, let expected, let actual) = authStatus {
                        Text("Permit: \(expected) — Here: \(actual)")
                            .font(.caption.bold())
                            .foregroundStyle(textColor)
                        if !permit.ownerName.isEmpty {
                            Text(permit.ownerName)
                                .font(.caption)
                                .foregroundStyle(textColor.opacity(0.9))
                        }
                    }

                    if case .authorized(let permit) = authStatus, !permit.ownerName.isEmpty {
                        Text(permit.ownerName)
                            .font(.caption)
                            .foregroundStyle(textColor.opacity(0.9))
                    }
                    if case .expired(let permit) = authStatus, !permit.ownerName.isEmpty {
                        Text(permit.ownerName)
                            .font(.caption)
                            .foregroundStyle(textColor.opacity(0.9))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
                .background(backgroundColor, in: RoundedRectangle(cornerRadius: 12))
                .transition(.opacity.combined(with: .scale(scale: 0.9)))
                .id(plate)
            }
        }
        .padding(.bottom, 16)
        .animation(.easeInOut(duration: 0.25), value: latestPlate)
    }
}
