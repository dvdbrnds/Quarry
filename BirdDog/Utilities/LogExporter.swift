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

    // MARK: - Session-aware exports (with device/benchmark metadata)

    static func exportBenchmarkSummary(from sessions: [ScanSession]) -> URL? {
        guard !sessions.isEmpty else { return nil }

        var lines: [String] = ["BIRD DOG - DEVICE BENCHMARK REPORT", ""]
        lines.append("Generated: \(isoFormatter.string(from: Date()))")
        lines.append("Sessions compared: \(sessions.count)")
        lines.append("")

        for session in sessions {
            let device = session.deviceModel ?? "Unknown Device"
            let chip = session.deviceChip ?? "—"
            let conn = session.connectionType ?? "—"
            lines.append("═══ \(device) (\(chip)) ═══")
            lines.append("  Session: \(session.label)")
            lines.append("  Date: \(isoFormatter.string(from: session.startTime))")
            lines.append(String(format: "  Duration: %.1f minutes", session.duration / 60.0))
            lines.append("  Connection: \(conn)")
            lines.append("  Camera: \(session.primaryCamera)")

            if let res = session.cameraResolution {
                lines.append("  Resolution: \(res)")
            }
            if let fps = session.cameraFPS, fps > 0 {
                lines.append("  Configured FPS: \(fps)")
            }
            if let fps = session.avgActualFPS, fps > 0 {
                lines.append(String(format: "  Actual FPS: %.1f", fps))
            }
            if let tp = session.pixelThroughput, tp > 0 {
                lines.append(String(format: "  Pixel Throughput: %.1f Mpx/s", tp / 1_000_000))
            }

            lines.append("")
            lines.append("  -- Processing --")
            if let ocr = session.avgOCRTimeMs, ocr > 0 {
                lines.append(String(format: "  Avg OCR Time: %.1f ms", ocr))
            }
            if let peak = session.peakOCRTimeMs, peak > 0 {
                lines.append(String(format: "  Peak OCR Time: %.1f ms", peak))
            }
            if let proc = session.framesProcessed {
                lines.append("  Frames Processed: \(proc)")
            }
            if let skip = session.framesSkipped {
                lines.append("  Frames Skipped: \(skip)")
            }
            if session.frameSkipRatio > 0 {
                lines.append(String(format: "  Frame Skip Ratio: %.0f%%", session.frameSkipRatio * 100))
            }

            lines.append("")
            lines.append("  -- Plate Detection --")
            lines.append("  Plates detected: \(session.plates.count)")
            lines.append(String(format: "  Plates/minute: %.1f", session.platesPerMinute))
            lines.append(String(format: "  Avg Latency: %.3fs", session.avgLatency))
            lines.append(String(format: "  Median Latency: %.3fs", session.medianLatency))
            lines.append(String(format: "  Avg Confidence: %.1f%%", session.avgConfidence * 100))
            lines.append("")
        }

        if sessions.count >= 2 {
            lines.append("═══ DEVICE COMPARISON ═══")
            let header = String(format: "  %-25s %8s %8s %10s %8s %8s %10s",
                                "Device", "Plates", "P/min", "Avg Lat", "OCR ms", "FPS", "Skip %")
            lines.append(header)
            lines.append("  " + String(repeating: "─", count: 79))

            for s in sessions {
                let device = (s.deviceModel ?? "Unknown").prefix(25)
                let row = String(format: "  %-25s %8d %8.1f %10.3fs %8.1f %8.1f %9.0f%%",
                                 String(device),
                                 s.plates.count,
                                 s.platesPerMinute,
                                 s.avgLatency,
                                 s.avgOCRTimeMs ?? 0,
                                 s.avgActualFPS ?? 0,
                                 s.frameSkipRatio * 100)
                lines.append(row)
            }
            lines.append("")
        }

        let content = lines.joined(separator: "\n")
        return writeToTemp(content: content, extension: "txt", prefix: "birddog_benchmark")
    }

    static func exportBenchmarkCSV(from sessions: [ScanSession]) -> URL? {
        guard !sessions.isEmpty else { return nil }

        var csv = "session_label,start_time,device_model,device_chip,connection_type,"
        csv += "camera,resolution,configured_fps,actual_fps,pixel_throughput_mpxs,"
        csv += "avg_ocr_ms,peak_ocr_ms,frames_processed,frames_skipped,skip_ratio,"
        csv += "plates_detected,plates_per_min,avg_latency_s,median_latency_s,avg_confidence\n"

        for s in sessions {
            let ts = isoFormatter.string(from: s.startTime)
            let label = s.label.replacingOccurrences(of: ",", with: ";")
            let device = (s.deviceModel ?? "").replacingOccurrences(of: ",", with: ";")
            let chip = (s.deviceChip ?? "").replacingOccurrences(of: ",", with: ";")
            let conn = (s.connectionType ?? "").replacingOccurrences(of: ",", with: ";")
            let cam = s.primaryCamera.replacingOccurrences(of: ",", with: ";")
            let res = s.cameraResolution ?? ""

            csv += "\(label),\(ts),\(device),\(chip),\(conn),"
            csv += "\(cam),\(res),\(s.cameraFPS ?? 0),"
            csv += String(format: "%.1f,", s.avgActualFPS ?? 0)
            csv += String(format: "%.1f,", (s.pixelThroughput ?? 0) / 1_000_000)
            csv += String(format: "%.1f,%.1f,", s.avgOCRTimeMs ?? 0, s.peakOCRTimeMs ?? 0)
            csv += "\(s.framesProcessed ?? 0),\(s.framesSkipped ?? 0),"
            csv += String(format: "%.3f,", s.frameSkipRatio)
            csv += "\(s.plates.count),"
            csv += String(format: "%.1f,%.3f,%.3f,%.3f\n",
                          s.platesPerMinute, s.avgLatency, s.medianLatency, s.avgConfidence)
        }

        return writeToTemp(content: csv, extension: "csv", prefix: "birddog_benchmark")
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
