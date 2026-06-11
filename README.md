# Bird Dog

Real-time license plate scanner for university campus police. Officers drive through parking lots with a mounted iPad, and Bird Dog scans every plate, checking it against the school's permit database and flagging unauthorized, expired, or wrong-lot vehicles.

## Quick Start

### Prerequisites

- Xcode 15+ with iOS 17 SDK
- An Apple Developer account (for device deployment)
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) (optional — `project.pbxproj` is committed)

### Build & Run

```bash
# If regenerating the Xcode project from project.yml:
brew install xcodegen
xcodegen generate

# Open in Xcode
open BirdDog.xcodeproj
```

Select your target device and hit Run. The app requires a physical device (camera not available in Simulator).

### First Launch

1. Grant camera and location permissions when prompted
2. The app starts in **Officer mode** — camera scanner, scan log, and export
3. Tap the lock icon in the bottom bar to enter **Admin mode** (default passcode: `1234`)
4. In Admin mode, configure the school name, import permit data, and manage lots

## Updating Permit Data

Permit data is a JSON file matching the format in `BirdDog/Resources/permits.json`.

### From a spreadsheet

```bash
# Convert an Excel export to the JSON format Bird Dog expects
# Output is written to BirdDog/Resources/permits.json
python3 scripts/convert_permits.py input.xlsx
```

### Loading onto the iPad

**Option A — Rebuild** (development): Replace `BirdDog/Resources/permits.json` and build from Xcode.

**Option B — File import** (production): AirDrop the JSON file to the iPad, then open it from Bird Dog's Admin Settings > Import Permits. The imported file becomes the source of truth and persists across app restarts.

## Admin vs. Officer Mode

| Feature | Officer | Admin |
|---------|---------|-------|
| Camera scanner | Yes | Yes |
| Scan log & stats | Yes | Yes |
| Export | Yes | Yes |
| Clear log | Yes | Yes |
| Audio toggle | Yes | Yes |
| Database management | No | Yes |
| Lot management | No | Yes |
| Settings (passcode, school, import) | No | Yes |

Tap the lock icon to toggle. The default admin passcode is `1234` — change it in Admin Settings before handing the iPad to officers.

## Distribution

| Stage | How |
|-------|-----|
| **Development** | Xcode direct install to device |
| **Testing** | TestFlight — invite the station's Apple ID |
| **Production** | Apple Business Manager + Custom Apps |

For selling to other schools, use **Custom Apps via Apple Business Manager**. The app goes through normal App Store review but is only visible to organizations you authorize. Each school's IT team uses ABM (free from Apple) to deploy to their managed devices.

## Multi-School Setup

Each school runs the same app binary. School-specific configuration:

1. **School name** — Set in Admin Settings, shown in UI and exports
2. **Permit data** — Import via JSON file (AirDrop or Files app)
3. **Lot boundaries** — Import via JSON or manually define in Lot Management
4. **Admin passcode** — Set per-device in Admin Settings

A `DataProvider` protocol is in place to support future cloud sync, where schools would pull their data from a centralized backend instead of manual file import.

## Project Structure

```
Bird Dog/
├── BirdDog/
│   ├── App/              # App entry point
│   ├── Models/           # Data models (SwiftData + value types)
│   ├── Services/         # Camera, OCR, auth, database, geofencing, settings
│   ├── ViewModels/       # PlateReaderViewModel (central coordinator)
│   ├── Views/            # SwiftUI views
│   ├── Utilities/        # Plate pattern matching, candidate voting, log export
│   └── Resources/        # Asset catalog, bundled JSON data
├── BirdDogTests/         # Unit tests (XCTest)
├── docs/                 # PRD, architecture, testing plan
├── scripts/              # Data conversion tools
└── project.yml           # XcodeGen project spec
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed technical documentation.
