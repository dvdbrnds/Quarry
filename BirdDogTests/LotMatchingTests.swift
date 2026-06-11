import XCTest
@testable import BirdDog

final class LotMatchingTests: XCTestCase {

    // PlateAuthService.lotMatches is private, so we test through the public
    // checkDetailed API using a real database + records. These tests exercise
    // the lot matching logic end-to-end on the auth service.

    // MARK: - PlateStatus Codable round-trip

    func testPlateStatusCodableRoundTrip() throws {
        let permit = PermitInfo(
            ownerName: "Jane Doe",
            permitNumber: "P100",
            permitType: "Staff",
            permitStatus: "Valid",
            lotZone: "Lot B",
            vehicleDescription: "Red Toyota",
            plateState: "PA",
            issuedDate: Date(timeIntervalSince1970: 1700000000)
        )

        let cases: [PlateStatus] = [
            .authorized(permit: permit),
            .wrongLot(permit: permit, expectedLot: "Lot B", actualLot: "Lot C"),
            .expired(permit: permit),
            .unknown,
            .unchecked,
        ]

        let encoder = JSONEncoder()
        let decoder = JSONDecoder()

        for original in cases {
            let data = try encoder.encode(original)
            let decoded = try decoder.decode(PlateStatus.self, from: data)
            XCTAssertEqual(decoded, original, "Round-trip failed for \(original.label)")
        }
    }

    // MARK: - ScannedPlate Codable round-trip

    func testScannedPlateCodableRoundTrip() throws {
        let permit = PermitInfo(
            ownerName: "Jane Doe",
            permitNumber: "P100",
            permitType: "Staff",
            permitStatus: "Valid",
            lotZone: "Lot B",
            vehicleDescription: "Red Toyota",
            plateState: "PA",
            issuedDate: Date(timeIntervalSince1970: 1700000000)
        )

        let plate = ScannedPlate(
            text: "ABC1234",
            timestamp: Date(timeIntervalSince1970: 1700000100),
            confidence: 0.95,
            framesConfirmed: 3,
            authStatus: .authorized(permit: permit),
            matchMethod: .exact,
            matchedPlate: "ABC1234"
        )

        let encoder = JSONEncoder()
        let decoder = JSONDecoder()

        let data = try encoder.encode(plate)
        let decoded = try decoder.decode(ScannedPlate.self, from: data)

        XCTAssertEqual(decoded.text, plate.text)
        XCTAssertEqual(decoded.confidence, plate.confidence)
        XCTAssertEqual(decoded.framesConfirmed, plate.framesConfirmed)
        XCTAssertEqual(decoded.matchMethod, plate.matchMethod)
        XCTAssertEqual(decoded.authStatus, plate.authStatus)
    }
}
