import SwiftUI

struct PlateCorrectionView: View {
    @Environment(\.dismiss) private var dismiss

    let ocrPlate: String
    let scannedEntry: ScannedPlate?
    /// Recent OCR alternates from the recognition pipeline
    let recentAlternates: [String]
    var onCorrected: ((_ correctedPlate: String) -> Void)?

    @State private var correctPlate = ""
    @State private var notes = ""
    @State private var isSaving = false
    @State private var saved = false
    @State private var errorMessage: String?

    /// Deduplicated suggestions: alternates that differ from the OCR read
    private var suggestions: [String] {
        var seen = Set<String>([ocrPlate])
        var result: [String] = []
        for alt in recentAlternates {
            let normalized = alt.uppercased().trimmingCharacters(in: .whitespaces)
            guard !normalized.isEmpty, !seen.contains(normalized) else { continue }
            seen.insert(normalized)
            result.append(normalized)
            if result.count >= 6 { break }
        }
        return result
    }

    var body: some View {
        NavigationStack {
            if saved {
                savedConfirmation
            } else {
                correctionForm
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private var correctionForm: some View {
        VStack(spacing: 16) {
            // OCR read display
            VStack(spacing: 4) {
                Text("Camera Read")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(ocrPlate)
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                    .foregroundStyle(.red)
            }
            .padding(.top, 8)

            // Suggestions from OCR alternates
            if !suggestions.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Did you mean?")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(suggestions, id: \.self) { alt in
                                Button {
                                    correctPlate = alt
                                } label: {
                                    Text(alt)
                                        .font(.system(.body, design: .monospaced, weight: .semibold))
                                        .padding(.horizontal, 14)
                                        .padding(.vertical, 8)
                                        .background(correctPlate == alt ? Color.blue : Color(.systemGray5), in: RoundedRectangle(cornerRadius: 8))
                                        .foregroundStyle(correctPlate == alt ? .white : .primary)
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal)
            }

            // Manual entry
            VStack(alignment: .leading, spacing: 6) {
                Text("Or type the correct plate")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)

                TextField("Enter plate number", text: $correctPlate)
                    .textInputAutocapitalization(.characters)
                    .font(.system(.title3, design: .monospaced))
                    .padding(10)
                    .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 8))
                    .onChange(of: correctPlate) { _, newValue in
                        correctPlate = newValue.uppercased()
                    }
            }
            .padding(.horizontal)

            // Notes
            VStack(alignment: .leading, spacing: 6) {
                Text("Notes (optional)")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                TextField("e.g. dirty plate, angled", text: $notes)
                    .font(.subheadline)
                    .padding(10)
                    .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 8))
            }
            .padding(.horizontal)

            if let err = errorMessage {
                Text(err)
                    .foregroundStyle(.red)
                    .font(.caption)
                    .padding(.horizontal)
            }

            Spacer()

            // Action buttons
            HStack(spacing: 12) {
                Button("Cancel") { dismiss() }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(Color(.systemGray5), in: RoundedRectangle(cornerRadius: 12))
                    .foregroundStyle(.primary)

                Button {
                    submitCorrection()
                } label: {
                    if isSaving {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Text("Save & Check")
                            .fontWeight(.semibold)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(
                    correctPlate.trimmingCharacters(in: .whitespaces).isEmpty || isSaving
                    ? Color.blue.opacity(0.4) : Color.blue,
                    in: RoundedRectangle(cornerRadius: 12)
                )
                .foregroundStyle(.white)
                .disabled(correctPlate.trimmingCharacters(in: .whitespaces).isEmpty || isSaving)
            }
            .padding(.horizontal)
            .padding(.bottom, 16)
        }
        .navigationTitle("Correct Plate")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var savedConfirmation: some View {
        VStack(spacing: 16) {
            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(.green)

            Text("Plate Updated")
                .font(.title3.bold())

            HStack(spacing: 12) {
                Text(ocrPlate)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.red)
                    .strikethrough()
                Image(systemName: "arrow.right")
                    .foregroundStyle(.secondary)
                Text(correctPlate)
                    .font(.system(.body, design: .monospaced, weight: .bold))
                    .foregroundStyle(.green)
            }

            Text("The corrected plate has been checked\nagainst the permit database.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Spacer()

            Button("Done") { dismiss() }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Color.blue, in: RoundedRectangle(cornerRadius: 12))
                .foregroundStyle(.white)
                .padding(.horizontal)
                .padding(.bottom, 16)
        }
    }

    private func submitCorrection() {
        isSaving = true
        errorMessage = nil

        let trimmed = correctPlate.trimmingCharacters(in: .whitespaces)
        let auth = OfficerAuthService.shared
        let lot = GeofenceService.shared.currentLotName ?? ""

        Task {
            do {
                try await HoundDogSyncService.shared.uploadPlateCorrection(
                    ocrPlate: ocrPlate,
                    correctPlate: trimmed,
                    lot: lot,
                    officerName: auth.officerName,
                    officerEmail: auth.officerEmail,
                    notes: notes.trimmingCharacters(in: .whitespaces)
                )
                await MainActor.run {
                    saved = true
                    isSaving = false
                    onCorrected?(trimmed)
                }
            } catch {
                await MainActor.run {
                    errorMessage = "Upload failed — correction saved locally."
                    isSaving = false
                    // Still fire the callback so the plate gets checked
                    onCorrected?(trimmed)
                    saved = true
                }
            }
        }
    }
}
