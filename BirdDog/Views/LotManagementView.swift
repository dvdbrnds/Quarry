import SwiftUI
import MapKit

struct LotManagementView: View {

    @ObservedObject private var geofenceService = GeofenceService.shared
    @State private var showAddLot = false
    @State private var editingLot: ParkingLot?

    var body: some View {
        List {
            Section {
                if geofenceService.lots.isEmpty {
                    Text("No parking lots configured")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(geofenceService.lots) { lot in
                        lotRow(lot)
                    }
                    .onDelete(perform: deleteLots)
                }
            } header: {
                Text("Parking Lots (\(geofenceService.lots.count))")
            } footer: {
                Text("Define lot boundaries using corner coordinates from Google Earth. Lot names must match the zone names in your permit data.")
            }

            Section {
                locationStatusRow
            } header: {
                Text("Location Status")
            }
        }
        .navigationTitle("Lot Geofences")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showAddLot = true
                } label: {
                    Image(systemName: "plus")
                }
            }
        }
        .sheet(isPresented: $showAddLot) {
            NavigationStack {
                LotEditorView(lot: nil) { newLot in
                    geofenceService.addLot(newLot)
                }
            }
        }
        .sheet(item: $editingLot) { lot in
            NavigationStack {
                LotEditorView(lot: lot) { updatedLot in
                    geofenceService.updateLot(updatedLot)
                }
            }
        }
    }

    private func lotRow(_ lot: ParkingLot) -> some View {
        Button {
            editingLot = lot
        } label: {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(lot.name)
                        .font(.headline)
                        .foregroundStyle(.primary)
                    Spacer()
                    Text("\(lot.boundary.count) corners")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if lot.boundary.count >= 3 {
                    LotMapPreview(lot: lot)
                        .frame(height: 120)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
            .padding(.vertical, 4)
        }
    }

    private var locationStatusRow: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Circle()
                        .fill(locationStatusColor)
                        .frame(width: 8, height: 8)
                    Text(locationStatusText)
                        .font(.subheadline)
                }
                if let lot = geofenceService.currentLot {
                    Text("Current lot: \(lot.name)")
                        .font(.caption)
                        .foregroundStyle(.green)
                } else if geofenceService.currentLocation != nil {
                    Text("Not in any defined lot")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
    }

    private var locationStatusColor: Color {
        switch geofenceService.locationStatus {
        case .authorizedWhenInUse, .authorizedAlways: return .green
        case .notDetermined: return .yellow
        default: return .red
        }
    }

    private var locationStatusText: String {
        switch geofenceService.locationStatus {
        case .authorizedWhenInUse, .authorizedAlways: return "Location active"
        case .notDetermined: return "Location not requested"
        case .denied: return "Location denied"
        case .restricted: return "Location restricted"
        @unknown default: return "Unknown"
        }
    }

    private func deleteLots(at offsets: IndexSet) {
        for index in offsets {
            let lot = geofenceService.lots[index]
            geofenceService.deleteLot(id: lot.id)
        }
    }
}

// MARK: - Map Preview

struct LotMapPreview: View {
    let lot: ParkingLot

    private var region: MKCoordinateRegion {
        let lats = lot.boundary.map(\.latitude)
        let lngs = lot.boundary.map(\.longitude)
        let center = CLLocationCoordinate2D(
            latitude: (lats.min()! + lats.max()!) / 2,
            longitude: (lngs.min()! + lngs.max()!) / 2
        )
        let span = MKCoordinateSpan(
            latitudeDelta: (lats.max()! - lats.min()!) * 2.5 + 0.0005,
            longitudeDelta: (lngs.max()! - lngs.min()!) * 2.5 + 0.0005
        )
        return MKCoordinateRegion(center: center, span: span)
    }

    var body: some View {
        Map(initialPosition: .region(region)) {
            MapPolygon(coordinates: lot.boundary.map(\.clLocation))
                .foregroundStyle(.blue.opacity(0.2))
                .stroke(.blue, lineWidth: 2)
        }
        .disabled(true)
    }
}

// MARK: - Lot Editor

struct LotEditorView: View {
    let lot: ParkingLot?
    let onSave: (ParkingLot) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String = ""
    @State private var cornerRows: [CornerRow] = []
    @State private var newLat: String = ""
    @State private var newLng: String = ""

    struct CornerRow: Identifiable {
        let id = UUID()
        var lat: String
        var lng: String

        var coordinate: Coordinate? {
            guard let la = Double(lat), let lo = Double(lng),
                  (-90...90).contains(la), (-180...180).contains(lo) else { return nil }
            return Coordinate(latitude: la, longitude: lo)
        }

        init(coordinate: Coordinate) {
            self.lat = String(format: "%.5f", coordinate.latitude)
            self.lng = String(format: "%.5f", coordinate.longitude)
        }

        init(lat: String = "", lng: String = "") {
            self.lat = lat
            self.lng = lng
        }
    }

    init(lot: ParkingLot?, onSave: @escaping (ParkingLot) -> Void) {
        self.lot = lot
        self.onSave = onSave
        _name = State(initialValue: lot?.name ?? "")
        _cornerRows = State(initialValue: lot?.boundary.map { CornerRow(coordinate: $0) } ?? [])
    }

    private var validCoordinates: [Coordinate] {
        cornerRows.compactMap(\.coordinate)
    }

    var body: some View {
        Form {
            Section("Lot Name") {
                TextField("e.g. LOT A", text: $name)
                    .textInputAutocapitalization(.characters)
            }

            Section {
                ForEach($cornerRows) { $row in
                    let index = cornerRows.firstIndex(where: { $0.id == row.id }) ?? 0
                    HStack(spacing: 8) {
                        Text("\(index + 1)")
                            .font(.caption.bold())
                            .foregroundStyle(.secondary)
                            .frame(width: 24)
                        TextField("Latitude", text: $row.lat)
                            .keyboardType(.numbersAndPunctuation)
                            .font(.system(.body, design: .monospaced))
                        TextField("Longitude", text: $row.lng)
                            .keyboardType(.numbersAndPunctuation)
                            .font(.system(.body, design: .monospaced))
                    }
                }
                .onDelete(perform: deleteCorners)
                .onMove(perform: moveCorners)

                Button {
                    cornerRows.append(CornerRow())
                } label: {
                    Label("Add Corner", systemImage: "plus.circle.fill")
                }
            } header: {
                HStack {
                    Text("Boundary Corners (\(cornerRows.count))")
                    Spacer()
                    EditButton()
                        .font(.caption)
                }
            } footer: {
                Text("Tap any coordinate to edit it. Add corners in order walking the perimeter. Get lat/lng from Google Earth.")
            }

            if validCoordinates.count >= 3 {
                Section("Preview") {
                    let previewLot = ParkingLot(id: "preview", name: name, boundary: validCoordinates)
                    LotMapPreview(lot: previewLot)
                        .frame(height: 200)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
                }
            }

            if !invalidCornerWarning.isEmpty {
                Section {
                    Label(invalidCornerWarning, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
        .navigationTitle(lot == nil ? "Add Lot" : "Edit Lot")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") { save() }
                    .disabled(!canSave)
            }
        }
    }

    private var invalidCornerWarning: String {
        let invalidCount = cornerRows.count - validCoordinates.count
        if invalidCount > 0 {
            return "\(invalidCount) corner(s) have invalid coordinates and will be ignored"
        }
        return ""
    }

    private var canSave: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && validCoordinates.count >= 3
    }

    private func deleteCorners(at offsets: IndexSet) {
        cornerRows.remove(atOffsets: offsets)
    }

    private func moveCorners(from source: IndexSet, to destination: Int) {
        cornerRows.move(fromOffsets: source, toOffset: destination)
    }

    private func save() {
        let trimmedName = name.trimmingCharacters(in: .whitespaces)
        let id = lot?.id ?? trimmedName.uppercased().replacingOccurrences(of: " ", with: "_")
        let newLot = ParkingLot(id: id, name: trimmedName.uppercased(), boundary: validCoordinates)
        onSave(newLot)
        dismiss()
    }
}
