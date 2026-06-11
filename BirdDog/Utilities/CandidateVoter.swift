import Foundation

/// Accumulates multi-candidate OCR observations across frames and uses
/// character-level voting to resolve ambiguous characters (K/N, 1/7, etc.).
final class CandidateVoter {

    struct Ballot {
        let primary: String
        let alternates: [String]
        let confidence: Float
    }

    private var activeBallots: [String: [Ballot]] = [:]
    private var ballotTimestamps: [String: Date] = [:]

    private let expiryInterval: TimeInterval = 3.0

    /// Record a new observation. The `key` groups ballots by fuzzy plate identity.
    func record(key: String, ballot: Ballot) {
        activeBallots[key, default: []].append(ballot)
        ballotTimestamps[key] = Date()
    }

    /// Returns the consensus plate text using character-level majority voting
    /// across the primary + alternate candidates from all frames.
    /// Candidates matching known NA plate formats receive a weight bonus.
    func consensus(for key: String) -> String? {
        guard let ballots = activeBallots[key], !ballots.isEmpty else { return nil }

        let allCandidates = ballots.flatMap { ballot -> [(String, Float)] in
            let baseWeight = ballot.confidence
            var results: [(String, Float)] = [(ballot.primary, Self.formatWeight(ballot.primary, base: baseWeight))]
            for alt in ballot.alternates {
                results.append((alt, Self.formatWeight(alt, base: baseWeight * 0.6)))
            }
            return results
        }

        guard let targetLength = mostCommonLength(allCandidates.map(\.0)) else {
            return ballots.last?.primary
        }

        let sameLengthCandidates = allCandidates.filter { $0.0.count == targetLength }
        guard !sameLengthCandidates.isEmpty else { return ballots.last?.primary }

        var result: [Character] = []
        for position in 0..<targetLength {
            var votes: [Character: Float] = [:]
            for (text, weight) in sameLengthCandidates {
                let idx = text.index(text.startIndex, offsetBy: position)
                let char = text[idx]
                votes[char, default: 0] += weight
            }
            if let winner = votes.max(by: { $0.value < $1.value }) {
                result.append(winner.key)
            }
        }

        return String(result)
    }

    private static func formatWeight(_ text: String, base: Float) -> Float {
        if PlatePatternMatcher.isLocalFormat(text) {
            return base * 2.0
        }
        if PlatePatternMatcher.matchesAnyNAFormat(text) {
            return base * 1.5
        }
        return base
    }

    /// Remove stale entries that haven't received new observations.
    func pruneExpired() {
        let cutoff = Date().addingTimeInterval(-expiryInterval)
        let expired = ballotTimestamps.filter { $0.value < cutoff }.map(\.key)
        for key in expired {
            activeBallots.removeValue(forKey: key)
            ballotTimestamps.removeValue(forKey: key)
        }
    }

    func remove(key: String) {
        activeBallots.removeValue(forKey: key)
        ballotTimestamps.removeValue(forKey: key)
    }

    func ballotCount(for key: String) -> Int {
        activeBallots[key]?.count ?? 0
    }

    func removeAll() {
        activeBallots.removeAll()
        ballotTimestamps.removeAll()
    }

    private func mostCommonLength(_ strings: [String]) -> Int? {
        var counts: [Int: Int] = [:]
        for s in strings { counts[s.count, default: 0] += 1 }
        return counts.max(by: { $0.value < $1.value })?.key
    }
}
