# Bird Dog — Technical Architecture

**Version:** 2.0
**Date:** April 16, 2026

---

## 1. Overview

Bird Dog is a native iOS app that scans license plates in real time, checks them against a local permit database, and provides instant visual/audio feedback to officers. The app supports admin/officer role separation and file-based data import for deployment to multiple schools without rebuilding.

```
┌─────────────────────────────────────────────────┐
│               Bird Dog v2.0                      │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │         Camera Feed (Live)                │   │
│  │                                           │   │
│  │    ┌─────────────┐   [LOT A] [DB: 1247]  │   │
│  │    │  ABC-1234   │                        │   │
│  │    │ ✓ AUTHORIZED│ ← status overlay       │   │
│  │    └─────────────┘                        │   │
│  │                                           │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Scan Log          3 ✓  1 ✗  0 ⚠  1 ?   │   │
│  │  10:31:02  ABC-1234  ✓ Authorized         │   │
│  │  10:31:05  XYZ-5678  ✗ Unknown            │   │
│  │  10:31:08  LMN-9012  ✓ Authorized         │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  🔊  [Clear] [Export]                    🔒     │
│       ↑ officer tools        admin lock ↑       │
└─────────────────────────────────────────────────┘
```

## 2. Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Swift 5.9+ | Native performance, first-class Vision/AVFoundation support |
| UI | SwiftUI | Modern, declarative, universal iPhone/iPad layout |
| Camera | AVFoundation (AVCaptureSession) | Full control over camera pipeline, frame-by-frame access |
| OCR | Vision framework (VNRecognizeTextRequest) | On-device text recognition — no network, no API keys |
| Persistence | SwiftData | Local permit/lot storage with query support |
| Location | Core Location | Lot geofencing and current-lot detection |
| Min Target | iOS 17.0 | SwiftData support, modern Vision improvements |
| Architecture | MVVM + Services | Clean separation, protocol-based for future extensibility |

## 3. App Architecture

```
┌─────────────────────────────────────────────────┐
│                    View Layer                     │
│  ContentView (SwiftUI)                           │
│  ├── CameraPreviewView (UIViewRepresentable)     │
│  ├── PlateOverlayView (status badges)            │
│  ├── ScanLogView (scrollable log + stats)        │
│  ├── AdminPasscodeView (numeric keypad sheet)    │
│  ├── DatabaseManagementView (admin only)         │
│  ├── LotManagementView (admin only)              │
│  └── AdminSettingsView (admin only)              │
└────────────────┬────────────────────────────────┘
                 │ observes
┌────────────────▼────────────────────────────────┐
│              ViewModel Layer                      │
│  PlateReaderViewModel (ObservableObject)          │
│  - manages scan state & plate log                │
│  - deduplication with fuzzy matching             │
│  - multi-frame confirmation                      │
│  - audio/haptic feedback dispatch                │
└────────────────┬────────────────────────────────┘
                 │ delegates to
┌────────────────▼────────────────────────────────┐
│              Service Layer                        │
│                                                  │
│  CameraService          - AVCaptureSession       │
│  PlateRecognitionService - Vision OCR pipeline   │
│  PlateAuthService       - permit status lookup   │
│  PlateDatabase          - SwiftData permit store │
│  GeofenceService        - lot boundaries + GPS   │
│  AppSettings            - admin passcode, school │
│                                                  │
│  DataProvider (protocol)                         │
│  └── LocalDataProvider  - file import/seeding    │
│  └── CloudDataProvider  - (future) cloud sync    │
└─────────────────────────────────────────────────┘
```

### 3.1 Key Components

**CameraService** — Manages the AVCaptureSession. Configures the back camera at high resolution. Delivers CMSampleBuffer frames via delegate. Throttles to ~6 fps effective rate.

**PlateRecognitionService** — Receives frames from CameraService. Runs VNRecognizeTextRequest, filters for plate-like patterns, applies confidence thresholding. Returns recognized plates with bounding boxes.

**PlateAuthService** — Implements `PlateCheckable` protocol. Looks up plates in the database (exact match, then fuzzy OCR-character substitution). Returns status: authorized, wrong lot, expired, or unknown. Handles wildcard zones ("PARKING LOTS", "NORTH CAMPUS", etc.).

**PlateDatabase** — SwiftData-backed permit storage. Seeds from bundled or imported JSON. Provides exact and fuzzy lookup. Manages import lifecycle.

**GeofenceService** — Core Location-based lot detection. Stores lot boundary polygons in SwiftData. Uses ray-casting point-in-polygon test to determine current lot. Updates in real time as the device moves.

**AppSettings** — UserDefaults-backed settings: admin passcode, school name. Manages admin unlock state (session-only, not persisted). Gate for admin-only features.

**DataProvider protocol** — Abstracts data import operations. `LocalDataProvider` handles file-based import to Documents directory. Designed so `CloudDataProvider` can be added later without changing existing code.

**PlateRecognizerService** — Optional cloud OCR path using the PlateRecognizer API. Disabled by default; toggled in Admin Settings. When active, replaces the on-device Vision pipeline for frame processing.

**CandidateVoter** — Accumulates multi-frame OCR observations and uses character-level majority voting to resolve ambiguous characters (K/N, 1/7, O/0, etc.). Produces a consensus plate string from noisy frame-by-frame reads.

**PlateReaderViewModel** — Central coordinator. Receives recognized plates, applies multi-frame confirmation and fuzzy dedup, checks authorization, updates the scan log, dispatches haptic/audio feedback. Persists the scan log to disk so it survives app restarts.

### 3.2 Data Flow

```
Camera Frame (30fps, processed at ~6fps)
    │
    ▼
CameraService (AVCaptureVideoDataOutputSampleBufferDelegate)
    │ CMSampleBuffer
    ▼
PlateRecognitionService
    │ 1. VNImageRequestHandler from pixel buffer
    │ 2. VNRecognizeTextRequest (language correction OFF)
    │ 3. Filter for plate-like patterns (PlatePatternMatcher)
    │ 4. Confidence threshold (≥ 0.8)
    │
    ▼
PlateReaderViewModel
    │ 1. Multi-frame confirmation (1-3 frames depending on plate type)
    │ 2. Fuzzy deduplication (edit distance ≤ 2)
    │ 3. PlateAuthService.check(plate:currentLot:)
    │ 4. Insert into scan log
    │ 5. Trigger haptic + audio feedback
    │
    ▼
ContentView (SwiftUI reactively updates)
```

### 3.3 Admin / Officer Mode

```
App Launch
    │
    ▼
Officer Mode (default)
    │ Camera + scan log + export + clear + audio toggle
    │
    │ Tap 🔒 icon
    ▼
AdminPasscodeView (numeric keypad)
    │ Correct code?
    ▼
Admin Mode
    │ All officer features PLUS:
    │ ├── Database Management
    │ ├── Lot Management
    │ └── Admin Settings (passcode change, school name, data import)
    │
    │ Tap 🔓 icon
    ▼
Officer Mode (locked again)
```

### 3.4 Data Import Flow

```
Admin taps "Import Permits" in Settings
    │
    ▼
.fileImporter (system file picker)
    │ Select JSON file (from AirDrop, Files, etc.)
    ▼
LocalDataProvider.importPermits(from:)
    │ 1. Decode & validate JSON
    │ 2. Save to Documents/imported_permits.json
    │ 3. Clear existing SwiftData records
    │ 4. Seed from new payload
    ▼
Confirmation alert: "Imported 1,247 permit records"
```

On next app launch, `PlateDatabase.seedIfNeeded()` checks Documents directory first, falling back to the bundled file only if no import exists.

## 4. Project Structure

```
Bird Dog/
├── BirdDog/
│   ├── App/
│   │   ├── BirdDogApp.swift
│   │   └── Info.plist
│   ├── Models/
│   │   ├── ParkingLot.swift
│   │   ├── PermitRecord.swift
│   │   ├── PlateStatus.swift
│   │   └── ScannedPlate.swift
│   ├── Services/
│   │   ├── AppSettings.swift
│   │   ├── CameraService.swift
│   │   ├── DataProvider.swift
│   │   ├── GeofenceService.swift
│   │   ├── PlateAuthService.swift
│   │   ├── PlateDatabase.swift
│   │   ├── PlateRecognitionService.swift
│   │   └── PlateRecognizerService.swift  # Optional cloud OCR (PlateRecognizer API)
│   ├── Utilities/
│   │   ├── CandidateVoter.swift           # Multi-frame character-level voting
│   │   ├── LogExporter.swift
│   │   └── PlatePatternMatcher.swift
│   ├── ViewModels/
│   │   └── PlateReaderViewModel.swift
│   ├── Views/
│   │   ├── AdminPasscodeView.swift
│   │   ├── AdminSettingsView.swift
│   │   ├── CameraPreviewView.swift
│   │   ├── ContentView.swift
│   │   ├── DatabaseManagementView.swift
│   │   ├── LotManagementView.swift
│   │   ├── PlateOverlayView.swift
│   │   └── ScanLogView.swift
│   └── Resources/
│       ├── Assets.xcassets/
│       ├── lots.json
│       └── permits.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CURSOR_PROMPTS.md
│   ├── PRD.md
│   └── TESTING_PLAN.md
├── BirdDogTests/                          # Unit tests (XCTest)
│   ├── PlatePatternMatcherTests.swift
│   ├── CandidateVoterTests.swift
│   ├── LotMatchingTests.swift
│   └── LogExporterTests.swift
├── scripts/
│   ├── convert_permits.py
│   └── test_platerecognizer.py
├── project.yml
└── README.md
```

## 5. Multi-School Architecture

Each school deployment is a single instance of the same app binary. School-specific data is managed locally:

| Data | Storage | Update Method |
|------|---------|---------------|
| Permit records | SwiftData (seeded from JSON) | File import via Admin Settings |
| Lot boundaries | SwiftData (seeded from JSON) | File import or manual entry via Lot Management |
| School name | UserDefaults | Admin Settings |
| Admin passcode | UserDefaults | Admin Settings |

The `DataProvider` protocol is the extensibility seam. When cloud sync is needed:
1. Implement `CloudDataProvider` conforming to `DataProvider`
2. Add school onboarding: license key → fetch school's data from API
3. Periodic background sync replaces manual file import
4. No changes to PlateDatabase, GeofenceService, or any view code

## 6. Distribution

| Stage | Method |
|-------|--------|
| Development | Xcode direct install |
| Testing | TestFlight (invite station Apple ID) |
| Production | Apple Business Manager + Custom Apps |

Custom Apps via ABM: the app passes App Store review but is only visible to authorized schools. Each school's IT uses ABM (free from Apple) to push the app to their managed iPads.

## 7. Key Implementation Details

### 7.1 Camera Permissions

Info.plist includes `NSCameraUsageDescription`. The app handles permission flow gracefully — prompt on first launch, instructions if denied.

### 7.2 Location Permissions

Info.plist includes `NSLocationWhenInUseUsageDescription`. Required for lot geofencing. Pre-grant during iPad setup.

### 7.3 Frame Processing Strategy

- Process every 5th frame (~6 fps effective rate)
- Vision requests run on a dedicated background serial queue
- Non-blocking: if a request is in-flight, the next frame is skipped

### 7.4 Plate Pattern Matching

- PA format: 3 letters + 4 digits (prioritized with lower confirmation threshold)
- General: 2-8 alphanumeric characters, must contain both letters and numbers
- Vanity plates: higher confirmation threshold (3 frames) to reduce false positives
- Fuzzy OCR substitutions: O↔0, I↔1, B↔8, S↔5, Z↔2, G↔6, D→0, Q→0

### 7.5 Export Format

CSV with columns: `timestamp, plate_text, confidence, frames_confirmed, auth_status, permit_holder, permit_type, vehicle`
