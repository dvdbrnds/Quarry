import XCTest
@testable import BirdDog

final class CandidateVoterTests: XCTestCase {

    var voter: CandidateVoter!

    override func setUp() {
        super.setUp()
        voter = CandidateVoter()
    }

    func testSingleBallotConsensus() {
        voter.record(key: "KNH4017", ballot: .init(primary: "KNH4017", alternates: [], confidence: 0.95))
        XCTAssertEqual(voter.consensus(for: "KNH4017"), "KNH4017")
    }

    func testMajorityVotingResolvesAmbiguity() {
        // Two frames see "KNH4017", one sees "NNH4017" (K/N confusion)
        voter.record(key: "KNH4017", ballot: .init(primary: "KNH4017", alternates: [], confidence: 0.9))
        voter.record(key: "KNH4017", ballot: .init(primary: "KNH4017", alternates: [], confidence: 0.9))
        voter.record(key: "KNH4017", ballot: .init(primary: "NNH4017", alternates: [], confidence: 0.85))

        let result = voter.consensus(for: "KNH4017")
        XCTAssertEqual(result, "KNH4017", "Majority should win the vote")
    }

    func testAlternatesContribute() {
        // Primary says "NNH4017" but alternate says "KNH4017"
        voter.record(key: "KNH4017", ballot: .init(primary: "NNH4017", alternates: ["KNH4017"], confidence: 0.9))
        voter.record(key: "KNH4017", ballot: .init(primary: "KNH4017", alternates: [], confidence: 0.9))

        let result = voter.consensus(for: "KNH4017")
        XCTAssertEqual(result, "KNH4017", "Alternate candidate should tip the vote")
    }

    func testBallotCount() {
        XCTAssertEqual(voter.ballotCount(for: "ABC1234"), 0)
        voter.record(key: "ABC1234", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        XCTAssertEqual(voter.ballotCount(for: "ABC1234"), 1)
        voter.record(key: "ABC1234", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        XCTAssertEqual(voter.ballotCount(for: "ABC1234"), 2)
    }

    func testRemoveAll() {
        voter.record(key: "ABC1234", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        voter.record(key: "XYZ5678", ballot: .init(primary: "XYZ5678", alternates: [], confidence: 0.9))
        voter.removeAll()
        XCTAssertEqual(voter.ballotCount(for: "ABC1234"), 0)
        XCTAssertEqual(voter.ballotCount(for: "XYZ5678"), 0)
    }

    func testRemoveSingleKey() {
        voter.record(key: "ABC1234", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        voter.record(key: "XYZ5678", ballot: .init(primary: "XYZ5678", alternates: [], confidence: 0.9))
        voter.remove(key: "ABC1234")
        XCTAssertEqual(voter.ballotCount(for: "ABC1234"), 0)
        XCTAssertEqual(voter.ballotCount(for: "XYZ5678"), 1)
    }

    func testConsensusForUnknownKeyReturnsNil() {
        XCTAssertNil(voter.consensus(for: "NOPE"))
    }

    func testDifferentLengthsUseMostCommon() {
        // Three ballots of length 7, one of length 6 — should use length 7
        voter.record(key: "KEY", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        voter.record(key: "KEY", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        voter.record(key: "KEY", ballot: .init(primary: "ABC1234", alternates: [], confidence: 0.9))
        voter.record(key: "KEY", ballot: .init(primary: "BC1234", alternates: [], confidence: 0.8))

        let result = voter.consensus(for: "KEY")
        XCTAssertEqual(result?.count, 7)
    }
}
