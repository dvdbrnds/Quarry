import SwiftUI
import CoreImage.CIFilterBuiltins
import CoreLocation

struct MovingViolationView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var locationManager = TicketLocationManager()

    @State private var plate = ""
    @State private var driverName = ""
    @State private var driverLicense = ""
    @State private var vehicleDescription = ""
    @State private var locationText = ""
    @State private var selectedViolation = "speeding"
    @State private var officerNotes = ""
    @State private var isSubmitting = false
    @State private var submittedResult: HoundDogSyncService.TicketUploadResponse?
    @State private var errorMessage: String?
    @State private var isPrinting = false
    @State private var printError: String?
    @ObservedObject private var printerService = PrinterService.shared
    @ObservedObject private var officerAuth = OfficerAuthService.shared

    private let movingViolations = [
        ("speeding", "Speeding"),
        ("stop_sign", "Failure to Stop"),
        ("wrong_way", "Wrong Way"),
        ("reckless", "Reckless Driving"),
        ("crosswalk", "Crosswalk Violation"),
        ("no_headlights", "No Headlights"),
        ("distracted", "Distracted Driving"),
        ("other_moving", "Other Moving Violation"),
    ]

    var body: some View {
        NavigationStack {
            if let result = submittedResult {
                confirmationView(result)
            } else {
                formView
            }
        }
    }

    private var formView: some View {
        Form {
            Section("Driver Information") {
                TextField("Driver Name", text: $driverName)
                    .textInputAutocapitalization(.words)
                TextField("License Number", text: $driverLicense)
                    .textInputAutocapitalization(.characters)
            }

            Section("Vehicle") {
                TextField("License Plate", text: $plate)
                    .textInputAutocapitalization(.characters)
                    .font(.system(.body, design: .monospaced))
                TextField("Vehicle Description", text: $vehicleDescription)
                    .textInputAutocapitalization(.sentences)
            }

            Section("Violation") {
                Picker("Type", selection: $selectedViolation) {
                    ForEach(movingViolations, id: \.0) { code, label in
                        Text(label).tag(code)
                    }
                }
            }

            Section("Location") {
                TextField("Location Description", text: $locationText)
                    .textInputAutocapitalization(.sentences)
                if let lat = locationManager.latitude, let lng = locationManager.longitude {
                    HStack {
                        Image(systemName: "location.fill")
                            .foregroundStyle(.green)
                            .font(.caption)
                        Text(String(format: "%.5f, %.5f", lat, lng))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section("Officer Notes") {
                TextEditor(text: $officerNotes)
                    .frame(minHeight: 100)
            }

            if let err = errorMessage {
                Section {
                    Text(err)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
        }
        .navigationTitle("Moving Violation")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Issue") { submitViolation() }
                    .disabled(plate.isEmpty || driverName.isEmpty || isSubmitting)
                    .bold()
            }
        }
    }

    private func confirmationView(_ result: HoundDogSyncService.TicketUploadResponse) -> some View {
        VStack(spacing: 24) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)

            Text("Citation Issued")
                .font(.title2.bold())

            VStack(spacing: 8) {
                Text(driverName)
                    .font(.headline)
                Text(plate)
                    .font(.system(.title3, design: .monospaced).bold())
                Text("Fine: $\(result.fineAmount)")
                    .font(.headline)
                if result.offenseNumber > 1 {
                    Text("Offense #\(result.offenseNumber)")
                        .font(.subheadline)
                        .foregroundStyle(.orange)
                }
            }

            if !officerAuth.officerName.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "person.badge.shield.checkmark.fill")
                        .foregroundStyle(.blue)
                    Text("Issued by \(officerAuth.officerName)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if !result.paymentUrl.isEmpty {
                VStack(spacing: 8) {
                    Text("Payment QR Code")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let qrImage = generateQRCode(from: result.paymentUrl) {
                        Image(uiImage: qrImage)
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 200, height: 200)
                            .background(Color.white)
                            .cornerRadius(8)
                    }
                    Text(result.paymentUrl)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }

            if printerService.isConnected {
                Button {
                    printTicket(result)
                } label: {
                    HStack {
                        Image(systemName: "printer.fill")
                        Text(isPrinting ? "Printing…" : "Print Citation")
                    }
                }
                .buttonStyle(.bordered)
                .disabled(isPrinting)
            }

            if let printError {
                Text(printError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            Button("Done") { dismiss() }
                .buttonStyle(.borderedProminent)
                .padding(.top)
        }
        .padding()
        .navigationTitle("Citation Issued")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Done") { dismiss() }
            }
        }
        .onAppear {
            if printerService.autoPrintEnabled && printerService.isConnected {
                printTicket(result)
            }
        }
    }

    private func submitViolation() {
        isSubmitting = true
        errorMessage = nil

        let ticket = PendingTicket(
            plate: plate.uppercased().trimmingCharacters(in: .whitespaces),
            lot: "",
            violationType: selectedViolation,
            confidence: 1.0,
            ticketCategory: "moving",
            locationLat: locationManager.latitude,
            locationLng: locationManager.longitude,
            locationText: locationText.isEmpty ? nil : locationText,
            vehicleDescription: vehicleDescription.isEmpty ? nil : vehicleDescription,
            officerNotes: officerNotes.isEmpty ? nil : officerNotes,
            driverName: driverName.isEmpty ? nil : driverName,
            driverLicense: driverLicense.isEmpty ? nil : driverLicense,
            officerName: officerAuth.officerName.isEmpty ? nil : officerAuth.officerName,
            officerEmail: officerAuth.officerEmail.isEmpty ? nil : officerAuth.officerEmail
        )

        Task {
            do {
                let result = try await HoundDogSyncService.shared.uploadTicket(ticket)
                submittedResult = result
            } catch {
                errorMessage = error.localizedDescription
            }
            isSubmitting = false
        }
    }

    private func violationLabel(for code: String) -> String {
        movingViolations.first(where: { $0.0 == code })?.1 ?? code
    }

    private func printTicket(_ result: HoundDogSyncService.TicketUploadResponse) {
        isPrinting = true
        printError = nil

        let ticketData = TicketReceiptBuilder.TicketData(
            ticketId: result.ticketId,
            plate: plate,
            violationType: selectedViolation,
            violationLabel: violationLabel(for: selectedViolation),
            lot: "",
            fineAmount: result.fineAmount,
            offenseNumber: result.offenseNumber,
            paymentUrl: result.paymentUrl,
            issuedAt: Date(),
            vehicleDescription: vehicleDescription.isEmpty ? nil : vehicleDescription,
            officerNotes: officerNotes.isEmpty ? nil : officerNotes,
            driverName: driverName.isEmpty ? nil : driverName,
            driverLicense: driverLicense.isEmpty ? nil : driverLicense,
            locationText: locationText.isEmpty ? nil : locationText,
            ticketCategory: "moving",
            officerName: officerAuth.officerName.isEmpty ? nil : officerAuth.officerName,
            officerEmail: officerAuth.officerEmail.isEmpty ? nil : officerAuth.officerEmail
        )

        Task {
            do {
                let commands = TicketReceiptBuilder.buildCommands(
                    ticket: ticketData,
                    schoolName: AppSettings.shared.schoolName
                )
                try await printerService.printCommands(commands)
            } catch {
                printError = error.localizedDescription
            }
            isPrinting = false
        }
    }

    private func generateQRCode(from string: String) -> UIImage? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"

        guard let outputImage = filter.outputImage else { return nil }
        let scale = 250.0 / outputImage.extent.width
        let scaledImage = outputImage.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard let cgImage = context.createCGImage(scaledImage, from: scaledImage.extent) else { return nil }
        return UIImage(cgImage: cgImage)
    }
}
