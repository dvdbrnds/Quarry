import SwiftUI

struct CameraLogView: View {

    @ObservedObject var cameraService: CameraService

    var body: some View {
        List {
            Section("Status") {
                LabeledContent("Camera", value: cameraService.activeCameraName)
                LabeledContent("Status", value: cameraService.cameraStatus.rawValue)
                LabeledContent("Resolution", value: cameraService.activeResolution)
                LabeledContent("FPS", value: cameraService.activeFPS)
                LabeledContent("Devices Detected", value: "\(cameraService.detectedDeviceCount)")
                LabeledContent("Using External", value: cameraService.isUsingExternalCamera ? "Yes" : "No")
            }

            if cameraService.isUsingExternalCamera {
                Section("Focus Meter") {
                    Toggle("Enable Focus Meter", isOn: Binding(
                        get: { cameraService.focusMeterEnabled },
                        set: { cameraService.focusMeterEnabled = $0 }
                    ))

                    if cameraService.focusMeterEnabled {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("Sharpness")
                                    .font(.caption)
                                Spacer()
                                Text(String(format: "%.0f", cameraService.focusScore))
                                    .font(.system(.title, design: .monospaced))
                                    .bold()
                                    .foregroundStyle(focusColor)
                            }

                            ProgressView(value: min(cameraService.focusScore, cameraService.focusPeak > 0 ? cameraService.focusPeak : 1000), total: max(cameraService.focusPeak, 1))
                                .tint(focusColor)

                            HStack {
                                Text("Peak: \(String(format: "%.0f", cameraService.focusPeak))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Button("Reset Peak") {
                                    cameraService.focusPeak = 0
                                }
                                .font(.caption)
                            }
                        }

                        Text("Point at a license plate ~6-8ft away. Turn the focus ring slowly. Lock the set screw when the number peaks.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section {
                Button("Force Reconnect") {
                    cameraService.forceReconnect()
                }
                .bold()
            }

            Section("Debug Log") {
                if cameraService.debugLog.isEmpty {
                    Text("No log entries yet")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(Array(cameraService.debugLog.enumerated()), id: \.offset) { _, entry in
                        Text(entry)
                            .font(.system(.caption, design: .monospaced))
                    }
                }
            }
        }
        .navigationTitle("Camera Debug")
        .onDisappear {
            cameraService.focusMeterEnabled = false
        }
    }

    private var focusColor: Color {
        let ratio = cameraService.focusPeak > 0 ? cameraService.focusScore / cameraService.focusPeak : 0
        if ratio > 0.9 { return .green }
        if ratio > 0.6 { return .yellow }
        return .red
    }
}
