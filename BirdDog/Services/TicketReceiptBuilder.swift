import Foundation

#if canImport(StarIO10)
import StarIO10

struct TicketReceiptBuilder {

    private static let paperWidthMm = 48.0
    private static let charsPerLine = 32

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
        let title = ticket.ticketCategory == "moving" ? " CITATION " : " PARKING TICKET "
        let school = schoolName.isEmpty ? "Campus Police" : schoolName

        let printerBuilder = makeBasePrinterBuilder()

        _ = printerBuilder
            .styleAlignment(.center)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleInvert(true)
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText("\(title)\n")
            )
            .actionFeed(1)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 1, height: 2))
                    .actionPrintText("\(school)\n")
            )
            .actionPrintText("Campus Police Department\n")

        appendRuledLine(to: printerBuilder)

        _ = printerBuilder
            .styleAlignment(.left)
            .actionPrintText("Ticket #: \(String(ticket.ticketId.prefix(8)).uppercased())\n")
            .actionPrintText("Date:     \(dateStr)\n")

        appendRuledLine(to: printerBuilder)

        _ = printerBuilder
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .actionPrintText("VEHICLE\n")
            )
            .actionPrintText("Plate:\n")
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleAlignment(.center)
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText("\(ticket.plate.uppercased())\n")
            )
            .styleAlignment(.left)

        if let desc = ticket.vehicleDescription, !desc.isEmpty {
            appendWrapped(to: printerBuilder, label: "Vehicle:  ", text: desc)
        }

        if ticket.ticketCategory == "moving" {
            if let name = ticket.driverName, !name.isEmpty {
                appendWrapped(to: printerBuilder, label: "Driver:   ", text: name)
            }
            if let lic = ticket.driverLicense, !lic.isEmpty {
                _ = printerBuilder.actionPrintText("License:  \(lic)\n")
            }
        }

        appendRuledLine(to: printerBuilder)

        _ = printerBuilder
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .actionPrintText("VIOLATION\n")
            )
        appendWrapped(to: printerBuilder, label: "Type:     ", text: ticket.violationLabel)

        if !ticket.lot.isEmpty {
            appendWrapped(to: printerBuilder, label: "Location: ", text: ticket.lot)
        }
        if let locText = ticket.locationText, !locText.isEmpty {
            appendWrapped(to: printerBuilder, label: "Area:     ", text: locText)
        }
        if ticket.offenseNumber > 1 {
            _ = printerBuilder.actionPrintText("Offense:  #\(ticket.offenseNumber)\n")
        }

        appendRuledLine(to: printerBuilder)

        _ = printerBuilder
            .styleAlignment(.center)
            .actionFeed(1)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleInvert(true)
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText(" FINE: $\(ticket.fineAmount) \n")
            )
            .actionFeed(2)

        if !ticket.paymentUrl.isEmpty {
            _ = printerBuilder
                .styleAlignment(.center)
                .add(
                    StarXpandCommand.PrinterBuilder()
                        .styleBold(true)
                        .actionPrintText("Scan to pay online\n")
                )
                .actionFeed(1)
                .actionPrintQRCode(
                    StarXpandCommand.Printer.QRCodeParameter(content: ticket.paymentUrl)
                        .setModel(.model2)
                        .setLevel(.q)
                        .setCellSize(7)
                )
                .actionFeed(1)
                .actionPrintText("Pay online or at Campus Police\n")
        }

        if let name = ticket.officerName, !name.isEmpty {
            appendRuledLine(to: printerBuilder)
            _ = printerBuilder
                .styleAlignment(.left)
                .add(
                    StarXpandCommand.PrinterBuilder()
                        .styleBold(true)
                        .actionPrintText("ISSUING OFFICER\n")
                )
            appendWrapped(to: printerBuilder, label: "Name:     ", text: name)
            if let email = ticket.officerEmail, !email.isEmpty {
                appendWrapped(to: printerBuilder, label: "ID:       ", text: email)
            }
        }

        _ = printerBuilder
            .styleAlignment(.center)
            .actionFeed(2)

        if ticket.ticketCategory == "moving" {
            for line in wrapLines(
                "All violations must be paid or appealed within 10 days of the date issued. Fines not paid or appealed within 10 days will result in a Traffic Citation via the Local Magistrate."
            ) {
                _ = printerBuilder.actionPrintText("\(line)\n")
            }
        } else {
            for line in wrapLines(
                "Issued under campus parking regulations. Appeals must be filed within 10 business days."
            ) {
                _ = printerBuilder.actionPrintText("\(line)\n")
            }
        }

        _ = printerBuilder
            .actionFeed(3)
            .actionCut(.partial)

        _ = builder.addDocument(
            StarXpandCommand.DocumentBuilder()
                .settingPrintableArea(paperWidthMm)
                .settingTopMargin(2.0)
                .addPrinter(printerBuilder)
        )

        return builder.getCommands()
    }

    static func buildTestCommands(schoolName: String) -> String {
        let builder = StarXpandCommand.StarXpandCommandBuilder()
        let school = schoolName.isEmpty ? "Bird Dog" : schoolName
        let printerBuilder = makeBasePrinterBuilder()
            .styleAlignment(.center)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleInvert(true)
                    .styleBold(true)
                    .styleMagnification(StarXpandCommand.MagnificationParameter(width: 2, height: 2))
                    .actionPrintText(" PRINTER TEST \n")
            )
            .actionFeed(1)
            .add(
                StarXpandCommand.PrinterBuilder()
                    .styleBold(true)
                    .actionPrintText("\(school)\n")
            )
            .actionPrintText("Campus Parking Enforcement\n")

        appendRuledLine(to: printerBuilder)

        _ = printerBuilder
            .actionPrintText("High-quality print check\n")
            .actionPrintText("\(Date().formatted())\n")
            .actionFeed(1)
            .actionPrintQRCode(
                StarXpandCommand.Printer.QRCodeParameter(content: "https://parking.moravian.edu")
                    .setModel(.model2)
                    .setLevel(.q)
                    .setCellSize(7)
            )
            .actionFeed(2)
            .actionPrintText("If this looks sharp, ticket\n")
            .actionPrintText("prints will match.\n")
            .actionFeed(3)
            .actionCut(.partial)

        _ = builder.addDocument(
            StarXpandCommand.DocumentBuilder()
                .settingPrintableArea(paperWidthMm)
                .settingTopMargin(2.0)
                .addPrinter(printerBuilder)
        )

        return builder.getCommands()
    }

    private static func makeBasePrinterBuilder() -> StarXpandCommand.PrinterBuilder {
        StarXpandCommand.PrinterBuilder()
            .styleInternationalCharacter(.usa)
            .styleFont(.a)
            .styleCharacterSpace(0)
            .styleLineSpace(1.0)
            .styleBaseMagnification(
                StarXpandCommand.Printer.BaseMagnificationParameter()
                    .setText(.standard)
            )
    }

    private static func appendRuledLine(to printerBuilder: StarXpandCommand.PrinterBuilder) {
        _ = printerBuilder
            .actionFeed(1)
            .actionPrintRuledLine(
                StarXpandCommand.Printer.RuledLineParameter(width: paperWidthMm)
                    .setThickness(0.3)
            )
            .actionFeed(1)
    }

    private static func appendWrapped(
        to printerBuilder: StarXpandCommand.PrinterBuilder,
        label: String,
        text: String
    ) {
        let lines = wrapLines(text, firstLinePrefix: label, continuationPrefix: String(repeating: " ", count: label.count))
        for line in lines {
            _ = printerBuilder.actionPrintText("\(line)\n")
        }
    }

    private static func wrapLines(
        _ text: String,
        firstLinePrefix: String = "",
        continuationPrefix: String = "",
        width: Int = charsPerLine
    ) -> [String] {
        let words = text.split(whereSeparator: \.isWhitespace).map(String.init)
        guard !words.isEmpty else {
            let trimmed = firstLinePrefix.trimmingCharacters(in: .whitespaces)
            return trimmed.isEmpty ? [] : [trimmed]
        }

        var lines: [String] = []
        var current = firstLinePrefix

        for word in words {
            let joiner = (current == firstLinePrefix || current == continuationPrefix || current.isEmpty) ? "" : " "
            let candidate = current + joiner + word

            if candidate.count <= width {
                current = candidate
                continue
            }

            if !current.trimmingCharacters(in: .whitespaces).isEmpty {
                lines.append(current)
            }

            var remainder = word
            let usable = max(1, width - continuationPrefix.count)
            while remainder.count > usable {
                let idx = remainder.index(remainder.startIndex, offsetBy: usable)
                lines.append(continuationPrefix + String(remainder[..<idx]))
                remainder = String(remainder[idx...])
            }
            current = continuationPrefix + remainder
        }

        if !current.trimmingCharacters(in: .whitespaces).isEmpty {
            lines.append(current)
        }
        return lines
    }
}
#endif
