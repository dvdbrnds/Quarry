import XCTest
@testable import BirdDog

final class PlatePatternMatcherTests: XCTestCase {

    // MARK: - Normalization

    func testNormalizeStripsSpacesAndSpecialChars() {
        XCTAssertEqual(PlatePatternMatcher.normalize("ABC 1234"), "ABC1234")
        XCTAssertEqual(PlatePatternMatcher.normalize("abc-1234"), "ABC1234")
        XCTAssertEqual(PlatePatternMatcher.normalize("A.B.C.1234"), "ABC1234")
    }

    func testNormalizeUppercases() {
        XCTAssertEqual(PlatePatternMatcher.normalize("abc1234"), "ABC1234")
    }

    func testNormalizeTransliteratesCyrillic() {
        // Cyrillic А, В, С look like Latin A, B, C
        XCTAssertEqual(PlatePatternMatcher.normalize("АВС1234"), "ABC1234")
    }

    // MARK: - Plate Validation

    func testValidPAPlate() {
        XCTAssertNil(PlatePatternMatcher.evaluatePlate("KNH4017"))
        XCTAssertTrue(PlatePatternMatcher.looksLikePlate("KNH4017"))
    }

    func testValidNJPlate() {
        XCTAssertNil(PlatePatternMatcher.evaluatePlate("A12BCD"))
        XCTAssertTrue(PlatePatternMatcher.looksLikePlate("A12BCD"))
    }

    func testTooShortRejected() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("AB12"), .tooShort)
    }

    func testTooLongRejected() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("ABCD12345"), .tooLong)
    }

    func testRejectListCatchesCarModels() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("CAMRY"), .rejectList)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("HONDA"), .rejectList)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("SUBARU"), .rejectList)
    }

    func testRejectListCatchesSigns() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("POLICE"), .rejectList)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("PARKING"), .rejectList)
    }

    func testVanityPlateDisabled() {
        XCTAssertFalse(PlatePatternMatcher.isVanityPlate("HELLO"))
        XCTAssertFalse(PlatePatternMatcher.isVanityPlate("ABCDEF"))
        XCTAssertFalse(PlatePatternMatcher.isVanityPlate("ABC1234"))
    }

    func testAllLetterPlateRejected() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("HELLO"), .noDigits)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("ABCDEF"), .noDigits)
    }

    func testNonStandardFormatRejected() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("TOYOTA1"), .noFormatMatch)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("BRONCO3"), .noFormatMatch)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("HELLO12"), .noFormatMatch)
    }

    func testLocalFormatRecognition() {
        XCTAssertTrue(PlatePatternMatcher.isLocalFormat("KNH4017"))   // PA
        XCTAssertTrue(PlatePatternMatcher.isLocalFormat("A12BCD"))    // NJ
        XCTAssertTrue(PlatePatternMatcher.isLocalFormat("123456"))    // DE
    }

    func testNonLocalFormat() {
        XCTAssertFalse(PlatePatternMatcher.isLocalFormat("1ABC234"))  // CA
    }

    func testPennsylvaniaPlateDetection() {
        XCTAssertTrue(PlatePatternMatcher.isPennsylvaniaPlate("ABC1234"))
        XCTAssertFalse(PlatePatternMatcher.isPennsylvaniaPlate("A12BCD"))
    }

    // MARK: - Aspect Ratio

    func testValidAspectRatio() {
        XCTAssertTrue(PlatePatternMatcher.hasPlateAspectRatio(CGRect(x: 0, y: 0, width: 3, height: 1)))
        XCTAssertTrue(PlatePatternMatcher.hasPlateAspectRatio(CGRect(x: 0, y: 0, width: 5, height: 1)))
    }

    func testTooTallRejected() {
        XCTAssertFalse(PlatePatternMatcher.hasPlateAspectRatio(CGRect(x: 0, y: 0, width: 1, height: 1)))
    }

    func testZeroHeightRejected() {
        XCTAssertFalse(PlatePatternMatcher.hasPlateAspectRatio(CGRect(x: 0, y: 0, width: 3, height: 0)))
    }

    // MARK: - Confusable Distance

    func testIdenticalPlatesZeroDistance() {
        XCTAssertEqual(PlatePatternMatcher.confusableDistance("ABC1234", "ABC1234"), 0.0)
    }

    func testConfusableCharsLowCost() {
        let dist = PlatePatternMatcher.confusableDistance("KNH4017", "NNH4017")
        XCTAssertLessThan(dist, 1.0, "K->N should be a confusable swap with low cost")
    }

    func testNonConfusableCharsFullCost() {
        let dist = PlatePatternMatcher.confusableDistance("ABC1234", "AXC1234")
        XCTAssertEqual(dist, 1.0, "B->X is not confusable, should cost 1.0")
    }

    func testMultipleConfusableSwaps() {
        let dist = PlatePatternMatcher.confusableDistance("KNH4O17", "NNH4017")
        XCTAssertLessThan(dist, 1.0, "K->N and O->0 are both confusable")
    }

    // MARK: - Time-based Plate Rejection

    func testTimePatternRejected() {
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("1100PM"), .noFormatMatch)
        XCTAssertEqual(PlatePatternMatcher.evaluatePlate("770AM"), .noFormatMatch)
    }
}
