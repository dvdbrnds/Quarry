import SwiftUI
import CoreImage.CIFilterBuiltins
import CoreLocation

struct TicketIssuanceView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var geofence = GeofenceService.shared
    @StateObject private var locationManager = TicketLocationManager()

    @State private var plate = ""
    @State private var selectedLot = ""
    @State private var selectedViolation = "no_permit"
    @State private var vehicleDescription = ""
    @State private var officerNotes = ""
    @State private var isSubmitting = false
    @State private var submittedResult: HoundDogSyncService.TicketUploadResponse?
    @State private var errorMessage: String?
    @State private var isPrinting = false
    @State private var printError: String?
    @ObservedObject private var printerService = PrinterService.shared
    @ObservedObject private var officerAuth = OfficerAuthService.shared

    var prefilledPlate: String?

    private let violationTypes = [
        ("no_permit", "No Valid Permit"),
        ("expired_permit", "Expired Permit"),
        ("wrong_lot", "Wrong Lot"),
        ("fire_lane", "Fire Lane"),
        ("disability_area", "Disability Area (No Placard)"),
        ("overtime", "Overtime Parking"),
        ("snow_emergency", "Snow Emergency Violation"),
        ("loading_zone", "Loading Zone"),
        ("reserved", "Reserved Space"),
        ("double_parked", "Double Parked"),
        ("other", "Other"),
    ]

    var body: some View {
        NavigationStack {
            if let result = submittedResult {
                ticketConfirmation(result)
            } else {
                ticketForm
            }
        }
    }

    private var ticketForm: some View {
        Form {
            Section("Vehicle") {
                TextField("License Plate", text: $plate)
                    .textInputAutocapitalization(.characters)
                    .font(.system(.title3, design: .monospaced))
                TextField("Vehicle Description", text: $vehicleDescription)
                    .textInputAutocapitalization(.sentences)
            }

            Section("Violation") {
                Picker("Type", selection: $selectedViolation) {
                    ForEach(violationTypes, id: \.0) { code, label in
                        Text(label).tag(code)
                    }
                }
                Picker("Lot", selection: $selectedLot) {
                    Text("— Select —").tag("")
                    ForEach(geofence.lots, id: \.id) { lot in
                        Text(lot.name).tag(lot.name)
                    }
                }
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
        .navigationTitle("Issue Ticket")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Issue") { submitTicket() }
                    .disabled(plate.isEmpty || selectedLot.isEmpty || isSubmitting)
                    .bold()
            }
        }
        .onAppear {
            if let pre = prefilledPlate { plate = pre }
            if selectedLot.isEmpty, let current = geofence.currentLotName {
                selectedLot = current
            }
        }
    }

    private func ticketConfirmation(_ result: HoundDogSyncService.TicketUploadResponse) -> some View {
        VStack(spacing: 24) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)

            Text("Ticket Issued")
                .font(.title2.bold())

            VStack(spacing: 8) {
                Text(plate)
                    .font(.system(.title, design: .monospaced).bold())
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
                        Text(isPrinting ? "Printing…" : "Print Ticket")
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
        .navigationTitle("Ticket Issued")
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

    private func submitTicket() {
        isSubmitting = true
        errorMessage = nil

        let ticket = PendingTicket(
            plate: plate.uppercased().trimmingCharacters(in: .whitespaces),
            lot: selectedLot,
            violationType: selectedViolation,
            confidence: 1.0,
            ticketCategory: "parking",
            locationLat: locationManager.latitude,
            locationLng: locationManager.longitude,
            vehicleDescription: vehicleDescription.isEmpty ? nil : vehicleDescription,
            officerNotes: officerNotes.isEmpty ? nil : officerNotes,
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
        violationTypes.first(where: { $0.0 == code })?.1 ?? code
    }

    private func printTicket(_ result: HoundDogSyncService.TicketUploadResponse) {
        isPrinting = true
        printError = nil

        let ticketData = TicketReceiptBuilder.TicketData(
            ticketId: result.ticketId,
            plate: plate,
            violationType: selectedViolation,
            violationLabel: violationLabel(for: selectedViolation),
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

@MainActor
final class TicketLocationManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var latitude: Double?
    @Published var longitude: Double?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        Task { @MainActor in
            self.latitude = loc.coordinate.latitude
            self.longitude = loc.coordinate.longitude
        }
    }
}
