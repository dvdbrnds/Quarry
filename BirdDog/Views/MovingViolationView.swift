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
    @State private var selectedViolation = ""
    @State private var officerNotes = ""
    @State private var isSubmitting = false
    @State private var submittedResult: HoundDogSyncService.TicketUploadResponse?
    @State private var errorMessage: String?
    @State private var isPrinting = false
    @State private var printError: String?
    @State private var capturedPhotoPath: String?
    @State private var capturedPhotoImage: UIImage?
    @State private var captureTimestamp = Date()
    @ObservedObject private var printerService = PrinterService.shared

    var cameraService: CameraService?

    @State private var officerName = ""
    @State private var officerEmail = ""

    private var movingViolations: [(String, String)] {
        ViolationTypeStore.shared.types
            .filter { $0.category == "moving" }
            .map { ($0.code, $0.label) }
    }

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
                    Text("— Select —").tag("")
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

            Section {
                if let image = capturedPhotoImage {
                    VStack(spacing: 8) {
                        ZStack(alignment: .bottomLeading) {
                            Image(uiImage: image)
                                .resizable()
                                .scaledToFit()
                                .clipShape(RoundedRectangle(cornerRadius: 8))

                            Text(evidenceTimestampString)
                                .font(.caption2.monospaced())
                                .padding(4)
                                .background(.black.opacity(0.6))
                                .foregroundStyle(.white)
                                .clipShape(RoundedRectangle(cornerRadius: 4))
                                .padding(6)
                        }

                        Button {
                            capturePhoto()
                        } label: {
                            Label("Retake Photo", systemImage: "camera.rotate")
                                .font(.caption)
                        }
                    }
                } else {
                    HStack {
                        Image(systemName: "camera")
                            .foregroundStyle(.secondary)
                        Text("No photo captured")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        if cameraService != nil {
                            Button("Capture") { capturePhoto() }
                                .font(.caption)
                        }
                    }
                }
            } header: {
                Text("Evidence Photo")
            } footer: {
                Text("Photo is captured automatically when the citation form opens.")
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
                    .disabled(plate.isEmpty || driverName.isEmpty || selectedViolation.isEmpty || isSubmitting)
                    .bold()
            }
        }
        .onAppear {
            officerName = OfficerAuthService.shared.officerName
            officerEmail = OfficerAuthService.shared.officerEmail
            ensureValidViolationSelection()
            capturePhoto()
        }
    }

    private func ensureValidViolationSelection() {
        let codes = Set(movingViolations.map(\.0))
        if codes.contains(selectedViolation) { return }
        selectedViolation = ViolationTypeStore.shared.resolveCode(
            preferred: ["stop_sign", "speeding"],
            category: "moving"
        )
    }

    private static let timestampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f
    }()

    private var evidenceTimestampString: String {
        Self.timestampFormatter.string(from: captureTimestamp)
    }

    @State private var isCapturingPhoto = false

    private func capturePhoto() {
        guard let camera = cameraService, !isCapturingPhoto else { return }
        isCapturingPhoto = true
        let timestamp = Date()
        Task.detached(priority: .userInitiated) {
            let path = await camera.captureOneShotPhoto()
            let image: UIImage? = if let path { UIImage(contentsOfFile: path) } else { nil }
            await MainActor.run {
                captureTimestamp = timestamp
                capturedPhotoPath = path
                capturedPhotoImage = image
                isCapturingPhoto = false
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

            if !officerName.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "person.badge.shield.checkmark.fill")
                        .foregroundStyle(.blue)
                    Text("Issued by \(officerName)")
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

            Button {
                printTicket(result)
            } label: {
                HStack {
                    Image(systemName: "printer.fill")
                    Text(isPrinting ? "Printing…" : "Print Citation")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(isPrinting || printerService.connectionState == .connecting)

            if printerService.connectionState == .connecting {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Connecting to printer…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else if !printerService.isConnected {
                Text(printerService.hasSavedPrinter
                     ? "Printer not connected — tap Print to reconnect."
                     : "No printer paired. Pair one in Settings → Printer.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            if let printError {
                Text(printError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            Button("Done") { dismiss() }
                .buttonStyle(.bordered)
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
            if printerService.autoPrintEnabled {
                printTicket(result)
            } else if !printerService.isConnected && printerService.hasSavedPrinter {
                printerService.reconnectSaved()
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
            photoPath: capturedPhotoPath,
            ticketCategory: "moving",
            locationLat: locationManager.latitude,
            locationLng: locationManager.longitude,
            locationText: locationText.isEmpty ? nil : locationText,
            vehicleDescription: vehicleDescription.isEmpty ? nil : vehicleDescription,
            officerNotes: officerNotes.isEmpty ? nil : officerNotes,
            driverName: driverName.isEmpty ? nil : driverName,
            driverLicense: driverLicense.isEmpty ? nil : driverLicense,
            officerName: officerName.isEmpty ? nil : officerName,
            officerEmail: officerEmail.isEmpty ? nil : officerEmail
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
            officerName: officerName.isEmpty ? nil : officerName,
            officerEmail: officerEmail.isEmpty ? nil : officerEmail
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
