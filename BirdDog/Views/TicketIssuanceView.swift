import SwiftUI
import CoreImage.CIFilterBuiltins
import CoreLocation

struct TicketIssuanceView: View {
    @Environment(\.dismiss) private var dismiss

    @State private var plate = ""
    @State private var selectedLot = ""
    @State private var selectedViolation = ""
    @State private var vehicleDescription = ""
    @State private var officerNotes = ""
    @State private var isSubmitting = false
    @State private var submittedResult: HoundDogSyncService.TicketUploadResponse?
    @State private var errorMessage: String?
    @State private var capturedPhotoPath: String?
    @State private var capturedPhotoImage: UIImage?
    @State private var captureTimestamp = Date()
    @State private var isWarning = false
    @State private var selectedWarningReason = ""
    @State private var warningDetail = ""
    @State private var plateMisread = false
    @State private var correctedPlate = ""

    private static let commonWarningReasons = [
        "No permit displayed",
        "Parked in wrong lot",
        "Expired permit",
        "First offense — verbal/written warning",
        "Improper parking (over the line, etc.)",
        "Blocking access / fire lane",
        "Loading zone overstay",
        "Temporary grace — new student",
        "Permit pending / in process",
    ]

    @State private var lots: [ParkingLot] = []
    @State private var officerName = ""
    @State private var officerEmail = ""
    @State private var ticketLat: Double?
    @State private var ticketLng: Double?
    @State private var violationTypes: [(String, String)] = []

    var cameraService: CameraService?
    var prefilledPlate: String?
    var prefilledEntry: ScannedPlate?
    var onTicketIssued: ((String) -> Void)?

    private func ensureValidViolationSelection(preferred: [String] = []) {
        let codes = Set(violationTypes.map(\.0))
        if !selectedViolation.isEmpty, codes.contains(selectedViolation) { return }
        selectedViolation = ViolationTypeStore.shared.resolveCode(
            preferred: preferred.isEmpty ? ["no_permit_displayed", "no_permit", "unauthorized_permit"] : preferred,
            category: "parking"
        )
    }

    var body: some View {
        NavigationStack {
            if let result = submittedResult {
                TicketConfirmationView(
                    result: result,
                    plate: plate,
                    selectedViolation: selectedViolation,
                    selectedLot: selectedLot,
                    vehicleDescription: vehicleDescription,
                    officerNotes: officerNotes,
                    officerName: officerName,
                    officerEmail: officerEmail,
                    violationLabel: violationLabel(for: selectedViolation),
                    isWarning: isWarning
                )
            } else {
                ticketForm
            }
        }
    }

    private var ticketForm: some View {
        Form {
            if let permit = prefilledEntry?.authStatus.permit {
                Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(prefilledEntry?.text ?? "")
                                .font(.system(.title2, design: .monospaced, weight: .bold))
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
                                Label("\(permit.displayType) · \(permit.permitStatus)", systemImage: "doc.text.fill")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            if !permit.lotZone.isEmpty {
                                Label("Permit for \(permit.lotZone)", systemImage: "mappin.circle.fill")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        Image(systemName: prefilledEntry?.authStatus.systemImage ?? "exclamationmark.triangle.fill")
                            .font(.title)
                            .foregroundStyle(prefilledEntry?.authStatus.color ?? .red)
                    }
                } header: {
                    Text("Vehicle on File")
                }
            }

            Section("Vehicle") {
                TextField("License Plate", text: $plate)
                    .textInputAutocapitalization(.characters)
                    .font(.system(.title3, design: .monospaced))
                TextField("Vehicle Description", text: $vehicleDescription)
                    .textInputAutocapitalization(.sentences)
            }

            if prefilledEntry != nil {
                Section {
                    Toggle(isOn: $plateMisread.animation()) {
                        Label("Plate Misread", systemImage: "eye.trianglebadge.exclamationmark")
                    }
                    .tint(.red)

                    if plateMisread {
                        TextField("Correct plate number", text: $correctedPlate)
                            .textInputAutocapitalization(.characters)
                            .font(.system(.title3, design: .monospaced))
                            .onChange(of: correctedPlate) { _, newValue in
                                correctedPlate = newValue.uppercased()
                            }
                    }
                } footer: {
                    Text(plateMisread
                         ? "Enter the actual plate you see on the vehicle. The ticket will use this corrected plate and the misread will be reported."
                         : "Toggle on if the camera read the plate incorrectly.")
                }
            }

            Section {
                Toggle(isOn: $isWarning.animation()) {
                    Label(isWarning ? "Warning" : "Citation",
                          systemImage: isWarning ? "exclamationmark.bubble.fill" : "doc.text.fill")
                }
                .tint(.orange)
            } footer: {
                Text(isWarning
                     ? "No fine will be assessed. A warning record will be created."
                     : "A citation with the applicable fine will be issued.")
            }

            if isWarning {
                Section("Warning Reason") {
                    Picker("Reason", selection: $selectedWarningReason) {
                        Text("— Select —").tag("")
                        ForEach(Self.commonWarningReasons, id: \.self) { reason in
                            Text(reason).tag(reason)
                        }
                        Text("Other").tag("Other")
                    }
                    TextField("Additional detail (optional)", text: $warningDetail, axis: .vertical)
                        .lineLimit(2...4)
                }
            }

            Section("Violation") {
                Picker("Type", selection: $selectedViolation) {
                    Text("— Select —").tag("")
                    ForEach(violationTypes, id: \.0) { code, label in
                        Text(label).tag(code)
                    }
                }
                if !lots.isEmpty {
                    Picker("Lot", selection: $selectedLot) {
                        Text("— Select —").tag("")
                        ForEach(lots, id: \.id) { lot in
                            Text(lot.name).tag(lot.name)
                        }
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

                if let lat = ticketLat, let lng = ticketLng {
                    HStack {
                        Image(systemName: "location.fill")
                            .font(.caption)
                            .foregroundStyle(.green)
                        Text(String(format: "%.5f, %.5f", lat, lng))
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }

                HStack {
                    Image(systemName: "clock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(evidenceTimestampString)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Evidence")
            } footer: {
                Text("Photo is captured automatically when the ticket form opens.")
            }

            Section("Notes") {
                TextEditor(text: $officerNotes)
                    .frame(minHeight: 80)
            }

            if let err = errorMessage {
                Section {
                    Text(err)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
        }
        .navigationTitle(isWarning ? "Issue Warning" : "Issue Ticket")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button(isWarning ? "Issue Warning" : "Issue") { submitTicket() }
                    .disabled(plate.isEmpty || (!lots.isEmpty && selectedLot.isEmpty) || selectedViolation.isEmpty || (isWarning && selectedWarningReason.isEmpty) || isSubmitting)
                    .bold()
            }
        }
        .onAppear {
            let geo = GeofenceService.shared
            lots = geo.lots
            officerName = OfficerAuthService.shared.officerName
            officerEmail = OfficerAuthService.shared.officerEmail
            violationTypes = ViolationTypeStore.shared.types(in: "parking").map { ($0.code, $0.label) }
            if let loc = geo.currentLocation {
                ticketLat = loc.coordinate.latitude
                ticketLng = loc.coordinate.longitude
            }

            if let entry = prefilledEntry {
                plate = entry.text
                if let permit = entry.authStatus.permit {
                    vehicleDescription = permit.vehicleDescription
                    if !permit.lotZone.isEmpty {
                        selectedLot = permit.lotZone
                    }
                }
                switch entry.authStatus {
                case .unknown:
                    ensureValidViolationSelection(preferred: [
                        "no_permit", "no_permit_displayed", "unauthorized_permit", "first_year_unauthorized"
                    ])
                case .wrongLot:
                    ensureValidViolationSelection(preferred: [
                        "wrong_lot", "unauthorized_premium", "unauthorized_permit", "prohibited_parking"
                    ])
                case .expired:
                    ensureValidViolationSelection(preferred: [
                        "expired_permit", "unauthorized_permit", "no_permit_displayed"
                    ])
                default:
                    ensureValidViolationSelection()
                }
            } else if let pre = prefilledPlate {
                plate = pre
                ensureValidViolationSelection()
            } else {
                ensureValidViolationSelection()
            }
            if selectedLot.isEmpty {
                if let current = geo.currentLotName {
                    selectedLot = current
                } else if lots.count == 1 {
                    selectedLot = lots[0].name
                }
            }
            capturePhoto()
        }
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

    // Confirmation screen is extracted to TicketConfirmationView to isolate
    // PrinterService observation from the form and avoid re-render lag.

    private func submitTicket() {
        isSubmitting = true
        errorMessage = nil

        let ocrPlate = plate.uppercased().trimmingCharacters(in: .whitespaces)
        let normalizedPlate: String
        let ocrOriginal: String?
        if plateMisread && !correctedPlate.trimmingCharacters(in: .whitespaces).isEmpty {
            normalizedPlate = correctedPlate.uppercased().trimmingCharacters(in: .whitespaces)
            ocrOriginal = ocrPlate
        } else {
            normalizedPlate = ocrPlate
            ocrOriginal = nil
        }
        let permit = prefilledEntry?.authStatus.permit
        let db = PlateDatabase.shared

        var composedNotes = officerNotes
        if isWarning {
            var warningText = "[WARNING] \(selectedWarningReason)"
            if !warningDetail.trimmingCharacters(in: .whitespaces).isEmpty {
                warningText += " — \(warningDetail.trimmingCharacters(in: .whitespaces))"
            }
            composedNotes = composedNotes.isEmpty ? warningText : "\(warningText)\n\(composedNotes)"
        }

        let ticket = PendingTicket(
            plate: normalizedPlate,
            lot: selectedLot,
            violationType: selectedViolation,
            confidence: 1.0,
            photoPath: capturedPhotoPath,
            ticketCategory: "parking",
            locationLat: ticketLat,
            locationLng: ticketLng,
            vehicleDescription: vehicleDescription.isEmpty ? nil : vehicleDescription,
            officerNotes: composedNotes.isEmpty ? nil : composedNotes,
            officerName: officerName.isEmpty ? nil : officerName,
            officerEmail: officerEmail.isEmpty ? nil : officerEmail,
            isWarning: isWarning,
            warningReason: isWarning ? selectedWarningReason : nil,
            ocrOriginalPlate: ocrOriginal,
            ownerName: permit?.ownerName,
            permitNumber: permit?.permitNumber
        )

        // Persist locally FIRST so the retry queue works even if the server is unreachable
        try? db.savePendingTicket(ticket)

        let paymentBaseURL = AppSettings.shared.paymentBaseURL

        Task {
            do {
                let serverResult = try await HoundDogSyncService.shared.uploadTicket(ticket)

                if serverResult.isDuplicate {
                    // Server says this plate already has an open ticket in this lot.
                    // Remove from local pending queue (already handled server-side).
                    db.markTicketUploaded(ticket)
                    try? db.saveContext()

                    await MainActor.run {
                        submittedResult = serverResult
                        onTicketIssued?(normalizedPlate)
                        isSubmitting = false
                    }
                    return
                }

                db.markTicketUploaded(ticket)
                ticket.paymentUrl = serverResult.paymentUrl
                ticket.fineAmount = serverResult.fineAmount
                ticket.offenseNumber = serverResult.offenseNumber
                try? db.saveContext()

                await MainActor.run {
                    submittedResult = serverResult
                    onTicketIssued?(normalizedPlate)
                    isSubmitting = false
                }
            } catch {
                // Ticket is already saved locally — it will retry on next sync
                let offlinePaymentUrl = paymentBaseURL.isEmpty ? "" : "\(paymentBaseURL)/pay?ticket=\(ticket.ticketId)"

                await MainActor.run {
                    onTicketIssued?(normalizedPlate)
                    isSubmitting = false
                    submittedResult = HoundDogSyncService.TicketUploadResponse(
                        status: "accepted",
                        ticketId: ticket.ticketId,
                        paymentUrl: offlinePaymentUrl,
                        fineAmount: ViolationTypeStore.shared.fineAmount(forCode: ticket.violationType),
                        offenseNumber: db.offenseCount(forPlate: normalizedPlate),
                        notificationSent: false,
                        notificationEmail: nil
                    )
                }
            }
        }
    }

    private func violationLabel(for code: String) -> String {
        violationTypes.first(where: { $0.0 == code })?.1 ?? code
    }

}

// MARK: - Ticket Confirmation (isolated from form to prevent printer observation re-renders)

struct TicketConfirmationView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var printerService = PrinterService.shared

    let result: HoundDogSyncService.TicketUploadResponse
    let plate: String
    let selectedViolation: String
    let selectedLot: String
    let vehicleDescription: String
    let officerNotes: String
    let officerName: String
    let officerEmail: String
    let violationLabel: String
    var isWarning: Bool = false

    @State private var isPrinting = false
    @State private var printError: String?

    var body: some View {
        VStack(spacing: 24) {
            if result.isDuplicate {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.orange)

                Text("Already Ticketed")
                    .font(.title2.bold())

                Text("This vehicle already has an open ticket in this lot.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            } else if isWarning {
                Image(systemName: "exclamationmark.bubble.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.orange)

                Text("Warning Issued")
                    .font(.title2.bold())
            } else {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.green)

                Text("Ticket Issued")
                    .font(.title2.bold())
            }

            VStack(spacing: 8) {
                Text(plate)
                    .font(.system(.title, design: .monospaced).bold())
                if isWarning {
                    Text("Warning — No Fine")
                        .font(.headline)
                        .foregroundStyle(.orange)
                } else {
                    Text("Fine: $\(result.fineAmount)")
                        .font(.headline)
                }
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

            if result.notificationSent, let email = result.notificationEmail {
                VStack(spacing: 6) {
                    HStack(spacing: 8) {
                        Image(systemName: "envelope.badge.fill")
                            .font(.title3)
                            .foregroundStyle(.blue)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Email Notification Sent")
                                .font(.subheadline.bold())
                            Text(email)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(Color.blue.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            } else {
                VStack(spacing: 6) {
                    HStack(spacing: 8) {
                        Image(systemName: "envelope.badge.shield.half.filled.fill")
                            .font(.title3)
                            .foregroundStyle(.orange)
                        Text("No email on file — print required")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(Color.orange.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 10))
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

            printButton

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
                .tint(result.notificationSent ? .accentColor : nil)
                .padding(.top)
        }
        .padding()
        .navigationTitle(isWarning ? "Warning Issued" : "Ticket Issued")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Done") { dismiss() }
            }
        }
        .onAppear {
            if !result.notificationSent && printerService.autoPrintEnabled {
                printTicket()
            } else if !printerService.isConnected && printerService.hasSavedPrinter {
                printerService.reconnectSaved()
            }
        }
    }

    @ViewBuilder
    private var printButton: some View {
        let label = HStack {
            Image(systemName: result.notificationSent ? "printer" : "printer.fill")
            Text(isPrinting
                 ? "Printing…"
                 : (result.notificationSent ? "Print Copy" : "Print Ticket"))
        }
        .frame(maxWidth: .infinity)

        if result.notificationSent {
            Button { printTicket() } label: { label }
                .buttonStyle(.bordered)
                .disabled(isPrinting || printerService.connectionState == .connecting)
        } else {
            Button { printTicket() } label: { label }
                .buttonStyle(.borderedProminent)
                .disabled(isPrinting || printerService.connectionState == .connecting)
        }
    }

    private func printTicket() {
        isPrinting = true
        printError = nil

        let ticketData = TicketReceiptBuilder.TicketData(
            ticketId: result.ticketId,
            plate: plate,
            violationType: selectedViolation,
            violationLabel: violationLabel,
            lot: selectedLot,
            fineAmount: result.fineAmount,
            offenseNumber: result.offenseNumber,
            paymentUrl: result.paymentUrl,
            issuedAt: Date(),
            vehicleDescription: vehicleDescription.isEmpty ? nil : vehicleDescription,
            officerNotes: officerNotes.isEmpty ? nil : officerNotes,
            driverName: nil,
            driverLicense: nil,
            locationText: nil,
            ticketCategory: "parking",
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
