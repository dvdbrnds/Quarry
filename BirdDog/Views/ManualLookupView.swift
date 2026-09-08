import SwiftUI

struct ManualLookupView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var plateText = ""
    @FocusState private var isFocused: Bool

    let onLookup: (String) -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                VStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 40))
                        .foregroundStyle(.blue)
                    Text("Manual Plate Lookup")
                        .font(.title3.bold())
                    Text("Enter a license plate to check against the permit database.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .padding(.top, 20)

                TextField("License plate", text: $plateText)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(.title2, design: .monospaced))
                    .multilineTextAlignment(.center)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .focused($isFocused)
                    .onChange(of: plateText) { _, newValue in
                        plateText = newValue.uppercased()
                            .replacingOccurrences(of: " ", with: "")
                            .replacingOccurrences(of: "-", with: "")
                    }
                    .padding(.horizontal, 32)

                Button {
                    let plate = plateText.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !plate.isEmpty else { return }
                    onLookup(plate)
                    dismiss()
                } label: {
                    Label("Look Up", systemImage: "magnifyingglass")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(plateText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .padding(.horizontal, 32)

                Spacer()
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .onAppear { isFocused = true }
    }
}
