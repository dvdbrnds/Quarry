import SwiftUI

struct ScanLogView: View {

    let log: [ScannedPlate]
    let uniqueCount: Int
    let authorizedCount: Int
    let wrongLotCount: Int
    let expiredCount: Int
    let unknownCount: Int
    var onIssueTapped: ((ScannedPlate) -> Void)?

    @State private var filter: StatusFilter = .all

    enum StatusFilter: String, CaseIterable {
        case all = "All"
        case flagged = "Flagged"
        case wrongLotFilter = "Wrong Lot"
        case unknown = "Unknown"
    }

    private var filteredLog: [ScannedPlate] {
        switch filter {
        case .all:
            return log
        case .flagged:
            return log.filter {
                if case .authorized = $0.authStatus { return false }
                if case .unchecked = $0.authStatus { return false }
                return true
            }
        case .unknown:
            return log.filter {
                if case .unknown = $0.authStatus { return true }
                return false
            }
        case .wrongLotFilter:
            return log.filter {
                if case .wrongLot = $0.authStatus { return true }
                return false
            }
        }
    }

    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            headerBar
                .padding(.horizontal)
                .padding(.vertical, 8)

            if log.isEmpty {
                Spacer()
                HStack {
                    Spacer()
                    Text("Point camera at a license plate")
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(filteredLog, id: \ScannedPlate.id) { (entry: ScannedPlate) in
                            if isTicketable(entry), let action = onIssueTapped {
                                Button {
                                    action(entry)
                                } label: {
                                    plateRow(entry)
                                        .contentShape(Rectangle())
                                }
                                .buttonStyle(RowPressStyle())
                            } else {
                                plateRow(entry)
                            }
                            Divider()
                        }
                    }
                }
            }
        }
    }

    private var headerBar: some View {
        VStack(spacing: 6) {
            HStack {
                Text("Scan Log")
                    .font(.headline)
                Spacer()
                statusCounts
            }

            if !log.isEmpty && (unknownCount > 0 || wrongLotCount > 0 || expiredCount > 0) {
                Picker("Filter", selection: $filter) {
                    ForEach(StatusFilter.allCases, id: \.self) { f in
                        Text(f.rawValue).tag(f)
                    }
                }
                .pickerStyle(.segmented)
            }
        }
    }

    private var statusCounts: some View {
        HStack(spacing: 8) {
            if unknownCount > 0 {
                Label("\(unknownCount)", systemImage: "xmark.shield.fill")
                    .font(.caption.bold())
                    .foregroundStyle(.red)
            }
            if wrongLotCount > 0 {
                Label("\(wrongLotCount)", systemImage: "location.slash.fill")
                    .font(.caption.bold())
                    .foregroundStyle(.orange)
            }
            if expiredCount > 0 {
                Label("\(expiredCount)", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption.bold())
                    .foregroundStyle(.yellow)
            }
            Text("\(uniqueCount) scanned")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    private func plateRow(_ entry: ScannedPlate) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(entry.authStatus.color)
                .frame(width: 10, height: 10)

            Text(Self.timeFormatter.string(from: entry.timestamp))
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 1) {
                Text(entry.text)
                    .font(.system(.body, design: .monospaced, weight: .semibold))
                    .foregroundStyle(plateTextColor(for: entry.authStatus))

                if let detail = permitDetail(for: entry.authStatus) {
                    Text(detail)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer()

            if isTicketable(entry) && onIssueTapped != nil {
                HStack(spacing: 4) {
                    Text("ISSUE")
                        .font(.caption2.bold())
                        .foregroundStyle(.blue)
                    Image(systemName: "chevron.right")
                        .font(.caption2)
                        .foregroundStyle(.blue.opacity(0.6))
                }
            } else if entry.authStatus != .unchecked {
                Image(systemName: entry.authStatus.systemImage)
                    .font(.caption)
                    .foregroundStyle(entry.authStatus.color)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(rowBackground(for: entry.authStatus))
    }

    private func isTicketable(_ entry: ScannedPlate) -> Bool {
        switch entry.authStatus {
        case .unknown, .wrongLot, .expired: return true
        default: return false
        }
    }

    private func plateTextColor(for status: PlateStatus) -> Color {
        switch status {
        case .unknown: return .red
        case .wrongLot: return .orange
        case .ticketed: return .purple
        default: return .primary
        }
    }

    private func rowBackground(for status: PlateStatus) -> some View {
        Group {
            switch status {
            case .unknown:
                Color.red.opacity(0.08)
            case .wrongLot:
                Color.orange.opacity(0.08)
            case .expired:
                Color.yellow.opacity(0.06)
            case .ticketed:
                Color.purple.opacity(0.08)
            default:
                Color.clear
            }
        }
    }

    private struct RowPressStyle: ButtonStyle {
        func makeBody(configuration: Configuration) -> some View {
            configuration.label
                .opacity(configuration.isPressed ? 0.6 : 1)
                .scaleEffect(configuration.isPressed ? 0.98 : 1)
                .animation(.easeInOut(duration: 0.1), value: configuration.isPressed)
        }
    }

    private func permitDetail(for status: PlateStatus) -> String? {
        switch status {
        case .authorized(let permit):
            return [permit.displayType, permit.ownerName, permit.vehicleDescription]
                .filter { !$0.isEmpty }
                .joined(separator: " · ")
        case .wrongLot(let permit, let expected, let actual):
            return "WRONG LOT · Permit: \(expected) · Here: \(actual) · \(permit.ownerName)"
        case .expired(let permit):
            return "EXPIRED · \([permit.displayType, permit.ownerName].filter { !$0.isEmpty }.joined(separator: " · "))"
        case .unknown:
            return "NOT IN DATABASE"
        case .ticketed:
            return "TICKET ISSUED"
        case .unchecked:
            return nil
        }
    }
}
