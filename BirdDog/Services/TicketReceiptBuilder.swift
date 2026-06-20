import Foundation
import StarIO10

struct TicketReceiptBuilder {

    struct TicketData {
        let ticketId: String
        let plate: String
        let violationType: String
        let violationLabel: String
        let lot: String
        let fineAmount: String
        let offenseNumber: Int
        let paymentUrl: String
        let issuedAt: Date
        let vehicleDescription: String?
        let officerNotes: String?
        let driverName: String?
        let driverLicense: String?
        let locationText: String?
        let ticketCategory: String
        let officerName: String?
        let officerEmail: String?
    }

    static func buildCommands(
        ticket: TicketData,
        schoolName: String
    ) -> String {
        let builder = StarXpandCommand.StarXpandCommandBuilder()

        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "MM/dd/yyyy  h:mm a"
        let dateStr = dateFormatter.string(from: ticket.issuedAt)

        let separator = "--------------------------------\n"

        let printerBuilder = StarXpandCommand.PrinterBuilder()
            .styleInternationalCharacter(.usa)
            .styleCharacterSpace(0)

        // Header
        _ = printerBuilder
            .styleAlignment(.center)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText(ticket.ticketCategory == "moving" ? "CITATION\n" : "PARKING TICKET\n")
            )
            .actionPrintText("\n")
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .actionPrintText("\(schoolName.isEmpty ? "Campus Police" : schoolName)\n")
            )
            .actionPrintText("Campus Police Department\n")
            .actionPrintText(separator)

        // Ticket info
        _ = printerBuilder
            .styleAlignment(.left)
            .actionPrintText("Ticket #: \(String(ticket.ticketId.prefix(8)).uppercased())\n")
            .actionPrintText("Date:     \(dateStr)\n")
            .actionPrintText(separator)

        // Vehicle
        _ = printerBuilder
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .actionPrintText("VEHICLE\n")
            )
        _ = printerBuilder.actionPrintText("Plate:    ")
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 1))
                    .styleBold(true)
                    .actionPrintText("\(ticket.plate)\n")
            )

        if let desc = ticket.vehicleDescription, !desc.isEmpty {
            _ = printerBuilder.actionPrintText("Vehicle:  \(desc)\n")
        }

        // Driver info (moving violations)
        if ticket.ticketCategory == "moving" {
            if let name = ticket.driverName, !name.isEmpty {
                _ = printerBuilder.actionPrintText("Driver:   \(name)\n")
            }
            if let lic = ticket.driverLicense, !lic.isEmpty {
                _ = printerBuilder.actionPrintText("License:  \(lic)\n")
            }
        }

        _ = printerBuilder.actionPrintText(separator)

        // Violation
        _ = printerBuilder
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .actionPrintText("VIOLATION\n")
            )
            .actionPrintText("Type:     \(ticket.violationLabel)\n")

        if !ticket.lot.isEmpty {
            _ = printerBuilder.actionPrintText("Location: \(ticket.lot)\n")
        }

        if let locText = ticket.locationText, !locText.isEmpty {
            _ = printerBuilder.actionPrintText("Area:     \(locText)\n")
        }

        if ticket.offenseNumber > 1 {
            _ = printerBuilder.actionPrintText("Offense:  #\(ticket.offenseNumber)\n")
        }

        _ = printerBuilder.actionPrintText(separator)

        // Fine
        _ = printerBuilder
            .styleAlignment(.center)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText("FINE: $\(ticket.fineAmount)\n")
            )
            .actionPrintText("\n")

        // Payment QR
        if !ticket.paymentUrl.isEmpty {
            _ = printerBuilder
                .actionPrintText("Scan to pay online:\n")
                .actionPrintQRCode(
                    StarXpandCommand.Printer.QRCodeParameter(content: ticket.paymentUrl)
                        .setLevel(.m)
                        .setCellSize(6)
                )
                .actionPrintText("\n")
                .add(
                    StarXpandCommand.PrinterBuilder()
                        .styleUnderLine(true)
                        .actionPrintText("\(ticket.paymentUrl)\n")
                )
                .actionPrintText("\n")
        }

        // Officer signature
        if let name = ticket.officerName, !name.isEmpty {
            _ = printerBuilder
                .styleAlignment(.left)
                .actionPrintText(separator)
                .add(
                    StarXpandCommand.PrinterBuilder()
                        .styleBold(true)
                        .actionPrintText("ISSUING OFFICER\n")
                )
                .actionPrintText("Name:     \(name)\n")
            if let email = ticket.officerEmail, !email.isEmpty {
                _ = printerBuilder.actionPrintText("ID:       \(email)\n")
            }
        }

        // Footer
        _ = printerBuilder
            .styleAlignment(.center)
            .actionPrintText("\n")
            .actionPrintText("This ticket is issued under the\n")
            .actionPrintText("campus parking regulations.\n")
            .actionPrintText("Appeals must be filed within\n")
            .actionPrintText("10 business days.\n")
            .actionPrintText("\n")
            .actionPrintText(separator)
            .actionCut(.partial)

        _ = builder.addDocument(
            StarXpandCommand.DocumentBuilder()
                .addPrinter(printerBuilder)
        )

        return builder.getCommands()
    }

    // MARK: - Test Print

    static func buildTestCommands(schoolName: String) -> String {
        let builder = StarXpandCommand.StarXpandCommandBuilder()

        let printerBuilder = StarXpandCommand.PrinterBuilder()
            .styleInternationalCharacter(.usa)
            .styleCharacterSpace(0)
            .styleAlignment(.center)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText("PRINTER TEST\n")
            )
            .actionPrintText("\n")
            .actionPrintText("\(schoolName.isEmpty ? "Bird Dog" : schoolName)\n")
            .actionPrintText("Campus Parking Enforcement\n")
            .actionPrintText("--------------------------------\n")
            .actionPrintText("Printer is working correctly.\n")
            .actionPrintText("\(Date().formatted())\n")
            .actionPrintText("--------------------------------\n")
            .actionPrintQRCode(
                StarXpandCommand.Printer.QRCodeParameter(content: "https://quarry.moravian.edu")
                    .setLevel(.m)
                    .setCellSize(6)
            )
            .actionPrintText("\n")
            .actionCut(.partial)

        _ = builder.addDocument(
            StarXpandCommand.DocumentBuilder()
                .addPrinter(printerBuilder)
        )

        return builder.getCommands()
    }
}
