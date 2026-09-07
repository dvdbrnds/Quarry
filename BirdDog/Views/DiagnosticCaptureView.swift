import SwiftUI

struct DiagnosticCaptureView: View {
    let entry: ScannedPlate
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                if let path = entry.diagnosticImagePath,
                   let uiImage = UIImage(contentsOfFile: path) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                } else {
                    VStack(spacing: 12) {
                        Image(systemName: "photo.slash")
                            .font(.largeTitle)
                            .foregroundStyle(.secondary)
                        Text("Image not available")
                            .foregroundStyle(.secondary)
                    }
                }

                VStack {
                    Spacer()
                    VStack(spacing: 4) {
                        HStack(spacing: 12) {
                            Text("OCR Read:")
                                .font(.caption.bold())
                                .foregroundStyle(.white.opacity(0.7))
                            Text(entry.text)
                                .font(.system(.title2, design: .monospaced, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        if entry.matchedPlate != entry.text {
                            HStack(spacing: 12) {
                                Text("Matched:")
                                    .font(.caption.bold())
                                    .foregroundStyle(.white.opacity(0.7))
                                Text(entry.matchedPlate)
                                    .font(.system(.body, design: .monospaced, weight: .semibold))
                                    .foregroundStyle(.green)
                                Text("(\(entry.matchMethod.rawValue))")
                                    .font(.caption)
                                    .foregroundStyle(.green.opacity(0.7))
                            }
                        }
                        HStack(spacing: 16) {
                            Label(String(format: "%.0f%%", entry.confidence * 100), systemImage: "gauge.high")
                                .font(.caption)
                            Label("\(entry.framesConfirmed)f", systemImage: "square.stack.3d.up")
                                .font(.caption)
                            Label(entry.authStatus.label, systemImage: entry.authStatus.systemImage)
                                .font(.caption)
                                .foregroundStyle(entry.authStatus.color)
                        }
                        .foregroundStyle(.white.opacity(0.7))
                    }
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(.ultraThinMaterial)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text(entry.text)
                        .font(.headline.monospaced())
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    if let path = entry.diagnosticImagePath,
                       let uiImage = UIImage(contentsOfFile: path) {
                        ShareLink(
                            item: Image(uiImage: uiImage),
                            preview: SharePreview(entry.text, image: Image(uiImage: uiImage))
                        )
                    }
                }
            }
        }
    }
}
