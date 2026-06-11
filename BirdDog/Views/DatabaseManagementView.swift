import SwiftUI
import SwiftData

struct DatabaseManagementView: View {

    @Query(sort: \PermitRecord.issuedDate, order: .reverse) private var allRecords: [PermitRecord]
    @State private var searchText = ""

    private var filteredRecords: [PermitRecord] {
        guard !searchText.isEmpty else { return allRecords }
        let term = searchText.uppercased()
        return allRecords.filter { record in
            record.plateNormalized.contains(term) ||
            record.ownerName.localizedCaseInsensitiveContains(searchText) ||
            record.permitNumber.localizedCaseInsensitiveContains(searchText) ||
            record.vehicleDescription.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var validCount: Int {
        allRecords.filter { $0.permitStatus == "Valid" }.count
    }

    private var expiredCount: Int {
        allRecords.filter { $0.permitStatus == "Expired" }.count
    }

    var body: some View {
        List {
            statsSection

            if !allRecords.isEmpty {
                recordsSection
            }
        }
        .searchable(text: $searchText, prompt: "Search plates, names, permits...")
        .navigationTitle("Permit Database")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var statsSection: some View {
        Section {
            HStack {
                StatCard(title: "Total", value: "\(allRecords.count)", color: .blue)
                StatCard(title: "Valid", value: "\(validCount)", color: .green)
                StatCard(title: "Expired", value: "\(expiredCount)", color: .yellow)
            }
            .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
            .listRowBackground(Color.clear)

            if allRecords.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "server.rack")
                        .font(.title)
                        .foregroundStyle(.secondary)
                    Text("No permit data loaded")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Rebuild the app with an updated permits.json to load data.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            }
        }
    }

    private var recordsSection: some View {
        Section("Permits (\(filteredRecords.count))") {
            ForEach(filteredRecords, id: \.plateNormalized) { record in
                PermitRowView(record: record)
            }
        }
    }
}

private struct StatCard: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.title2.bold().monospacedDigit())
                .foregroundStyle(color)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct PermitRowView: View {
    let record: PermitRecord

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        return f
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(record.plateRaw)
                    .font(.system(.body, design: .monospaced, weight: .semibold))

                Text(record.plateState)
                    .font(.caption)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.ultraThinMaterial, in: Capsule())

                Spacer()

                Text(record.permitStatus)
                    .font(.caption.bold())
                    .foregroundStyle(record.permitStatus == "Valid" ? .green : .yellow)
            }

            if !record.ownerName.isEmpty {
                Text(record.ownerName)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            HStack {
                if !record.permitType.isEmpty {
                    let displayType = record.permitType.components(separatedBy: ",").first?
                        .trimmingCharacters(in: .whitespaces).capitalized ?? record.permitType
                    Text(displayType)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if !record.lotZone.isEmpty {
                    Text("·")
                        .foregroundStyle(.secondary)
                    Text(record.lotZone)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if !record.vehicleDescription.isEmpty {
                    Text("·")
                        .foregroundStyle(.secondary)
                    Text(record.vehicleDescription)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Text("Issued: \(Self.dateFormatter.string(from: record.issuedDate))")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 2)
    }
}
