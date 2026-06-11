import XCTest
@testable import BirdDog

final class LogExporterTests: XCTestCase {

    private func makeSample() -> [ScannedPlate] {
        let permit = PermitInfo(
            ownerName: "John Smith",
            permitNumber: "P001",
            permitType: "Student",
            permitStatus: "Valid",
            lotZone: "Lot A",
            vehicleDescription: "Blue Honda",
            plateState: "PA",
            issuedDate: Date(timeIntervalSince1970: 1700000000)
        )

        return [
            ScannedPlate(
                text: "ABC1234",
                timestamp: Date(timeIntervalSince1970: 1700000100),
                confidence: 0.95,
                framesConfirmed: 3,
                authStatus: .authorized(permit: permit),
                matchMethod: .exact,
                matchedPlate: "ABC1234"
            ),
            ScannedPlate(
                text: "XYZ9999",
                timestamp: Date(timeIntervalSince1970: 1700000200),
                confidence: 0.88,
                framesConfirmed: 2,
                authStatus: .unknown,
                matchMethod: .none,
                matchedPlate: "XYZ9999"
            ),
        ]
    }

    func testCSVExportProducesFile() {
        let log = makeSample()
        let url = LogExporter.exportCSV(from: log)
        XCTAssertNotNil(url)

        guard let url else { return }
        let content = try? String(contentsOf: url)
        XCTAssertNotNil(content)

        XCTAssertTrue(content!.contains("ABC1234"))
        XCTAssertTrue(content!.contains("XYZ9999"))
        XCTAssertTrue(content!.contains("John Smith"))
        XCTAssertTrue(content!.hasPrefix("timestamp,plate_text,confidence,frames_confirmed,detection_latency_s,camera,"))

        try? FileManager.default.removeItem(at: url)
    }

    func testCSVExportEscapesCommasInNames() {
        let permit = PermitInfo(
            ownerName: "Smith, John",
            permitNumber: "P001",
            permitType: "Student",
            permitStatus: "Valid",
            lotZone: "Lot A",
            vehicleDescription: "Blue Honda",
            plateState: "PA",
            issuedDate: Date()
        )

        let log = [ScannedPlate(
            text: "ABC1234",
            timestamp: Date(),
            confidence: 0.95,
            framesConfirmed: 3,
            authStatus: .authorized(permit: permit),
            matchMethod: .exact,
            matchedPlate: "ABC1234"
        )]

        let url = LogExporter.exportCSV(from: log)
        XCTAssertNotNil(url)

        guard let url else { return }
        let content = try? String(contentsOf: url)
        XCTAssertTrue(content!.contains("Smith; John"), "Commas in names should be replaced with semicolons")

        try? FileManager.default.removeItem(at: url)
    }

    func testJSONExportProducesValidJSON() {
        let log = makeSample()
        let url = LogExporter.exportJSON(from: log)
        XCTAssertNotNil(url)

        guard let url else { return }
        let data = try? Data(contentsOf: url)
        XCTAssertNotNil(data)

        let parsed = try? JSONSerialization.jsonObject(with: data!) as? [[String: Any]]
        XCTAssertNotNil(parsed)
        XCTAssertEqual(parsed?.count, 2)
        XCTAssertEqual(parsed?.first?["plate_text"] as? String, "ABC1234")

        try? FileManager.default.removeItem(at: url)
    }

    func testEmptyLogExportsEmptyCSV() {
        let url = LogExporter.exportCSV(from: [])
        XCTAssertNotNil(url)

        guard let url else { return }
        let content = try? String(contentsOf: url)
        let lines = content?.components(separatedBy: "\n").filter { !$0.isEmpty }
        XCTAssertEqual(lines?.count, 1, "Should only have the header row")

        try? FileManager.default.removeItem(at: url)
    }
}
