import Foundation

enum LogExporter {

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func exportCSV(from log: [ScannedPlate]) -> URL? {
        var csv = "timestamp,plate_text,confidence,frames_confirmed,detection_latency_s,camera,auth_status,match_method,matched_plate,permit_holder,permit_type,vehicle\n"
        for entry in log {
            let ts = isoFormatter.string(from: entry.timestamp)
            let status = entry.authStatus.label
            let holder: String
            let permitType: String
            let vehicle: String

            switch entry.authStatus {
            case .authorized(let permit), .wrongLot(let permit, _, _), .expired(let permit):
                holder = permit.ownerName.replacingOccurrences(of: ",", with: ";")
                permitType = permit.displayType
                vehicle = permit.vehicleDescription.replacingOccurrences(of: ",", with: ";")
            default:
                holder = ""
                permitType = ""
                vehicle = ""
            }

            let method = entry.matchMethod.rawValue
            let matched = entry.matchedPlate != entry.text ? entry.matchedPlate : ""
            let cam = entry.cameraName.replacingOccurrences(of: ",", with: ";")

            csv += "\(ts),\(entry.text),\(String(format: "%.3f", entry.confidence)),\(entry.framesConfirmed),"
            csv += "\(String(format: "%.3f", entry.detectionLatency)),\(cam),"
            csv += "\(status),\(method),\(matched),\(holder),\(permitType),\(vehicle)\n"
        }
        return writeToTemp(content: csv, extension: "csv", prefix: "birddog_scan")
    }

    static func exportDiagnosticCSV(from log: [DiagnosticEntry]) -> URL? {
        var csv = "timestamp,raw_text,normalized,confidence,aspect_ratio,accepted,rejection_reason\n"
        for entry in log {
            let ts = isoFormatter.string(from: entry.timestamp)
            let raw = entry.rawText.replacingOccurrences(of: ",", with: ";")
            csv += "\(ts),\(raw),\(entry.normalizedText),"
            csv += "\(String(format: "%.3f", entry.confidence)),"
            csv += "\(String(format: "%.2f", entry.aspectRatio)),"
            csv += "\(entry.accepted),\(entry.rejectionReason)\n"
        }
        return writeToTemp(content: csv, extension: "csv", prefix: "birddog_diagnostic")
    }

    static func exportJSON(from log: [ScannedPlate]) -> URL? {
        let entries: [[String: Any]] = log.map { entry in
            var dict: [String: Any] = [
                "timestamp": isoFormatter.string(from: entry.timestamp),
                "plate_text": entry.text,
                "confidence": Double(entry.confidence),
                "frames_confirmed": entry.framesConfirmed,
                "detection_latency_s": entry.detectionLatency,
                "camera": entry.cameraName,
                "auth_status": entry.authStatus.label,
                "match_method": entry.matchMethod.rawValue,
                "matched_plate": entry.matchedPlate,
            ]
            switch entry.authStatus {
            case .authorized(let permit), .wrongLot(let permit, _, _), .expired(let permit):
                dict["permit_holder"] = permit.ownerName
                dict["permit_type"] = permit.displayType
                dict["vehicle"] = permit.vehicleDescription
            default:
                break
            }
            return dict
        }
        guard let data = try? JSONSerialization.data(withJSONObject: entries, options: .prettyPrinted) else {
            return nil
        }
        return writeToTemp(data: data, extension: "json", prefix: "birddog_scan")
    }

    static func exportSessionSummary(from log: [ScannedPlate]) -> URL? {
        guard !log.isEmpty else { return nil }

        let grouped = Dictionary(grouping: log, by: { $0.cameraName.isEmpty ? "Unknown" : $0.cameraName })
        var lines: [String] = ["BIRD DOG - SESSION PERFORMANCE SUMMARY", ""]

        let sorted = log.sorted { $0.timestamp < $1.timestamp }
        if let first = sorted.first, let last = sorted.last {
            let duration = last.timestamp.timeIntervalSince(first.timestamp)
            let mins = duration / 60.0
            lines.append("Session: \(isoFormatter.string(from: first.timestamp)) → \(isoFormatter.string(from: last.timestamp))")
            lines.append(String(format: "Duration: %.1f minutes", mins))
            lines.append("Total plates scanned: \(log.count)")
            lines.append("")
        }

        for (camera, entries) in grouped.sorted(by: { $0.key < $1.key }) {
            let latencies = entries.map { $0.detectionLatency }
            let confidences = entries.map { Double($0.confidence) }
            let framesCounts = entries.map { $0.framesConfirmed }
            let avgLatency = latencies.reduce(0, +) / Double(latencies.count)
            let minLatency = latencies.min() ?? 0
            let maxLatency = latencies.max() ?? 0
            let medianLatency = median(latencies)
            let avgConf = confidences.reduce(0, +) / Double(confidences.count)
            let avgFrames = Double(framesCounts.reduce(0, +)) / Double(framesCounts.count)

            let authorized = entries.filter {
                if case .authorized = $0.authStatus { return true }; return false
            }.count
            let unknown = entries.filter {
                if case .unknown = $0.authStatus { return true }; return false
            }.count
            let expired = entries.filter {
                if case .expired = $0.authStatus { return true }; return false
            }.count

            let sortedEntries = entries.sorted { $0.timestamp < $1.timestamp }
            var sessionMins = 0.0
            if let f = sortedEntries.first, let l = sortedEntries.last {
                sessionMins = l.timestamp.timeIntervalSince(f.timestamp) / 60.0
            }
            let platesPerMin = sessionMins > 0 ? Double(entries.count) / sessionMins : Double(entries.count)

            lines.append("═══ \(camera) ═══")
            lines.append("  Plates detected: \(entries.count)")
            lines.append(String(format: "  Plates/minute:   %.1f", platesPerMin))
            lines.append(String(format: "  Avg confidence:  %.1f%%", avgConf * 100))
            lines.append(String(format: "  Avg frames:      %.1f", avgFrames))
            lines.append(String(format: "  Detection latency (s): avg=%.3f  min=%.3f  max=%.3f  median=%.3f", avgLatency, minLatency, maxLatency, medianLatency))
            lines.append("  Auth breakdown: \(authorized) authorized, \(unknown) unknown, \(expired) expired")
            lines.append("")
        }

        if grouped.count > 1 {
            lines.append("═══ COMPARISON ═══")
            for (camera, entries) in grouped.sorted(by: { $0.key < $1.key }) {
                let avgLat = entries.map { $0.detectionLatency }.reduce(0, +) / Double(entries.count)
                let avgConf = entries.map { Double($0.confidence) }.reduce(0, +) / Double(entries.count)
                let padded = camera.padding(toLength: 30, withPad: " ", startingAt: 0)
                lines.append(String(format: "  %@  plates=%3d  avg_latency=%.3fs  avg_conf=%.1f%%", padded, entries.count, avgLat, avgConf * 100))
            }
            lines.append("")
        }

        let content = lines.joined(separator: "\n")
        return writeToTemp(content: content, extension: "txt", prefix: "birddog_summary")
    }

    private static func median(_ values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        let sorted = values.sorted()
        let mid = sorted.count / 2
        if sorted.count.isMultiple(of: 2) {
            return (sorted[mid - 1] + sorted[mid]) / 2.0
        }
        return sorted[mid]
    }

    private static func writeToTemp(content: String, extension ext: String, prefix: String) -> URL? {
        guard let data = content.data(using: .utf8) else { return nil }
        return writeToTemp(data: data, extension: ext, prefix: prefix)
    }

    private static func writeToTemp(data: Data, extension ext: String, prefix: String) -> URL? {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd_HHmmss"
        let dateStr = formatter.string(from: Date())
        let filename = "\(prefix)_\(dateStr).\(ext)"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        do {
            try data.write(to: url)
            return url
        } catch {
            return nil
        }
    }
}
