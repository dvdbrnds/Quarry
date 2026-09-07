import SwiftUI

struct PlateCorrectionView: View {
    @Environment(\.dismiss) private var dismiss

    let ocrPlate: String
    let scannedEntry: ScannedPlate?
    var onSaved: (() -> Void)?

    @State private var correctPlate = ""
    @State private var notes = ""
    @State private var isSaving = false
    @State private var saved = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            if saved {
                savedConfirmation
            } else {
                correctionForm
            }
        }
    }

    private var correctionForm: some View {
        Form {
            Section {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("OCR Read")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(ocrPlate)
                            .font(.system(.title2, design: .monospaced, weight: .bold))
                            .foregroundStyle(.red)
                    }
                    Spacer()
                    Image(systemName: "arrow.right")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("Correct Plate")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if correctPlate.isEmpty {
                            Text("Enter below")
                                .font(.system(.title2, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        } else {
                            Text(correctPlate)
                                .font(.system(.title2, design: .monospaced, weight: .bold))
                                .foregroundStyle(.green)
                        }
                    }
                }
            } header: {
                Text("Plate Correction")
            } footer: {
                Text("This helps us improve plate reading accuracy. No citation will be issued.")
            }

            if let permit = scannedEntry?.authStatus.permit {
                Section("Vehicle on File") {
                    if !permit.ownerName.isEmpty {
                        Label(permit.ownerName, systemImage: "person.fill")
                            .font(.subheadline)
                    }
                    if !permit.vehicleDescription.isEmpty {
                        Label(permit.vehicleDescription, systemImage: "car.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if !permit.permitType.isEmpty {
                        Label("\(permit.displayType) · \(permit.lotZone)", systemImage: "doc.text.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section("Correct Plate Number") {
                TextField("Enter the actual plate", text: $correctPlate)
                    .textInputAutocapitalization(.characters)
                    .font(.system(.title3, design: .monospaced))
                    .onChange(of: correctPlate) { _, newValue in
                        correctPlate = newValue.uppercased()
                    }
            }

            Section("Notes (optional)") {
                TextField("e.g. dirty plate, obstructed, angled", text: $notes, axis: .vertical)
                    .lineLimit(2...4)
            }

            if let err = errorMessage {
                Section {
                    Text(err)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
        }
        .navigationTitle("Correct Plate")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") { submitCorrection() }
                    .disabled(correctPlate.trimmingCharacters(in: .whitespaces).isEmpty || isSaving)
                    .bold()
            }
        }
    }

    private var savedConfirmation: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)

            Text("Correction Saved")
                .font(.title2.bold())

            VStack(spacing: 8) {
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
            }

            Text("Thank you! This correction will be used\nto improve plate reading accuracy.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Spacer()

            Button("Done") { dismiss() }
                .buttonStyle(.borderedProminent)
                .padding(.bottom, 32)
        }
        .padding()
        .navigationTitle("Correction Saved")
        .navigationBarTitleDisplayMode(.inline)
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
                    onSaved?()
                }
            } catch {
                await MainActor.run {
                    errorMessage = "Failed to save: \(error.localizedDescription)"
                    isSaving = false
                }
            }
        }
    }
}
