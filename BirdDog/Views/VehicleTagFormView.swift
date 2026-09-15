import SwiftUI

/// Lets an officer tag an unknown vehicle directly from BirdDog.
/// The plate is pre-filled from the camera scan; the officer adds
/// whatever they know about the vehicle and owner.
struct VehicleTagFormView: View {
    @Environment(\.dismiss) private var dismiss

    let prefilledPlate: String

    @State private var plates: String = ""
    @State private var ownerName = ""
    @State private var ownerAddress = ""
    @State private var studentName = ""
    @State private var studentEmail = ""
    @State private var vehicleMake = ""
    @State private var vehicleModel = ""
    @State private var vehicleColor = ""
    @State private var vehicleYear = ""
    @State private var source = "officer"
    @State private var notes = ""

    @State private var isSubmitting = false
    @State private var submitted = false
    @State private var errorMessage: String?

    // Student search
    @State private var studentSearch = ""
    @State private var studentResults: [HoundDogSyncService.StudentSearchResult] = []
    @State private var isSearching = false
    @State private var searchTask: Task<Void, Never>?

    private let sources = [
        ("officer", "Officer Observation"),
        ("JNET", "JNET"),
        ("CLEAN", "CLEAN"),
        ("other", "Other"),
    ]

    var body: some View {
        NavigationStack {
            if submitted {
                successView
            } else {
                formView
            }
        }
    }

    private var formView: some View {
        Form {
            Section {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                    Text("Unknown Vehicle")
                        .font(.headline)
                    Spacer()
                    Text(prefilledPlate)
                        .font(.system(.title3, design: .monospaced, weight: .bold))
                }
            }

            Section {
                TextField("Plate number(s)", text: $plates)
                    .textInputAutocapitalization(.characters)
                    .font(.system(.body, design: .monospaced))
            } header: {
                Text("License Plate(s)")
            } footer: {
                Text("Separate multiple plates with commas.")
            }

            Section("Vehicle Details") {
                TextField("Year", text: $vehicleYear)
                    .keyboardType(.numberPad)
                TextField("Color", text: $vehicleColor)
                    .textInputAutocapitalization(.words)
                TextField("Make (e.g. Honda)", text: $vehicleMake)
                    .textInputAutocapitalization(.words)
                TextField("Model (e.g. Civic)", text: $vehicleModel)
                    .textInputAutocapitalization(.words)
            }

            Section("Owner (if known)") {
                TextField("Owner name", text: $ownerName)
                    .textInputAutocapitalization(.words)
                TextField("Owner address", text: $ownerAddress)
                    .textInputAutocapitalization(.words)
            }

            Section("Student (if identified)") {
                TextField("Search by name, email, or ID…", text: $studentSearch)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onChange(of: studentSearch) { _, newVal in
                        searchTask?.cancel()
                        let trimmed = newVal.trimmingCharacters(in: .whitespaces)
                        guard trimmed.count >= 2 else {
                            studentResults = []
                            return
                        }
                        searchTask = Task {
                            isSearching = true
                            defer { isSearching = false }
                            try? await Task.sleep(for: .milliseconds(300))
                            guard !Task.isCancelled else { return }
                            let results = (try? await HoundDogSyncService.shared.searchStudents(query: trimmed)) ?? []
                            guard !Task.isCancelled else { return }
                            await MainActor.run { studentResults = results }
                        }
                    }

                if isSearching {
                    HStack {
                        ProgressView()
                            .scaleEffect(0.7)
                        Text("Searching…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                ForEach(studentResults) { result in
                    Button {
                        studentName = result.name
                        studentEmail = result.email
                        studentSearch = ""
                        studentResults = []
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(result.name)
                                .font(.body)
                                .foregroundStyle(.primary)
                            HStack(spacing: 8) {
                                Text(result.email)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                if !result.plates.isEmpty {
                                    Text(result.plates.joined(separator: ", "))
                                        .font(.caption)
                                        .foregroundStyle(.cyan)
                                }
                            }
                        }
                    }
                }

                TextField("Student name", text: $studentName)
                    .textInputAutocapitalization(.words)
                TextField("Student email", text: $studentEmail)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }

            Section("Source") {
                Picker("Source", selection: $source) {
                    ForEach(sources, id: \.0) { code, label in
                        Text(label).tag(code)
                    }
                }
                .pickerStyle(.menu)
            }

            Section {
                TextEditor(text: $notes)
                    .frame(minHeight: 60)
            } header: {
                Text("Notes")
            } footer: {
                Text("JNET/CLEAN results, officer observations, or reason for tagging.")
            }

            if let err = errorMessage {
                Section {
                    Text(err)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
        }
        .navigationTitle("Tag Vehicle")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save Tag") { submitTag() }
                    .disabled(plates.trimmingCharacters(in: .whitespaces).isEmpty || isSubmitting)
                    .bold()
            }
        }
        .onAppear {
            plates = prefilledPlate
        }
    }

    private var successView: some View {
        VStack(spacing: 24) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.cyan)

            Text("Vehicle Tagged")
                .font(.title2.bold())

            Text(plates)
                .font(.system(.title, design: .monospaced).bold())

            if !ownerName.isEmpty {
                Text(ownerName)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if !studentName.isEmpty || !studentEmail.isEmpty {
                VStack(spacing: 2) {
                    if !studentName.isEmpty {
                        Text("Student: \(studentName)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if !studentEmail.isEmpty {
                        Text(studentEmail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Text("This vehicle will now appear as\n\"Known Vehicle — No Permit\"\nwhen scanned.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button("Done") { dismiss() }
                .buttonStyle(.bordered)
                .padding(.top)
        }
        .padding()
        .navigationTitle("Vehicle Tagged")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Done") { dismiss() }
            }
        }
    }

    private func submitTag() {
        isSubmitting = true
        errorMessage = nil

        let plateList = plates
            .components(separatedBy: ",")
            .map { $0.trimmingCharacters(in: .whitespaces).uppercased() }
            .filter { !$0.isEmpty }

        guard !plateList.isEmpty else {
            errorMessage = "Enter at least one plate number."
            isSubmitting = false
            return
        }

        Task {
            do {
                _ = try await HoundDogSyncService.shared.createVehicleTag(
                    plates: plateList,
                    ownerName: ownerName.trimmingCharacters(in: .whitespaces),
                    ownerAddress: ownerAddress.trimmingCharacters(in: .whitespaces),
                    studentName: studentName.trimmingCharacters(in: .whitespaces),
                    studentEmail: studentEmail.trimmingCharacters(in: .whitespaces),
                    vehicleMake: vehicleMake.trimmingCharacters(in: .whitespaces),
                    vehicleModel: vehicleModel.trimmingCharacters(in: .whitespaces),
                    vehicleColor: vehicleColor.trimmingCharacters(in: .whitespaces),
                    vehicleYear: vehicleYear.trimmingCharacters(in: .whitespaces),
                    source: source,
                    notes: notes.trimmingCharacters(in: .whitespaces)
                )

                await MainActor.run {
                    submitted = true
                    isSubmitting = false
                }
            } catch {
                await MainActor.run {
                    errorMessage = error.localizedDescription
                    isSubmitting = false
                }
            }
        }
    }
}
