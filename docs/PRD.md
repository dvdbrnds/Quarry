# Bird Dog — Product Requirements Document

**Version:** 2.0
**Date:** April 16, 2026
**Author:** David Brands, Moravian University
**Status:** Active

---

## 1. Problem Statement

University campus police departments have the authority and access to license plate databases (both internal parking permit databases and state-level plate data) but lack a practical tool to scan license plates in campus parking lots. Officers currently rely on manual plate checks, which is time-consuming and limits enforcement coverage.

## 2. Product Vision

Bird Dog is an iOS app (universal — iPhone and iPad) that uses the device camera to continuously recognize license plates in real time. The primary deployment is a golf-cart-mounted iPad that scans every plate as an officer drives through campus parking lots, cross-referencing against permit databases to flag vehicles that need attention.

Bird Dog is designed to be sold as a product to multiple universities, with each school managing their own permit data, lot boundaries, and configuration.

## 3. MVP Scope (Phase 1 — Complete)

The MVP validated that an iOS device can reliably read license plates at close range in a parking lot environment.

### 3.1 MVP Features (Delivered)

- Live camera feed displayed full-screen in the app
- Continuous, real-time license plate detection and text extraction using Apple's Vision framework
- On-screen overlay displaying detected plate numbers as they are read
- Running log of all scanned plates with timestamps
- Ability to export the scan log (CSV or JSON) for accuracy analysis
- Universal app — runs on both iPhone and iPad
- Audible beep and haptic feedback when a plate is successfully read
- Duplicate detection with fuzzy matching
- Count of total unique plates scanned in current session
- Multi-frame confirmation to reduce false positives

### 3.2 MVP Success Criteria (Met)

1. The app reads license plates at a distance of 2–6 feet from the camera
2. Recognition accuracy is >= 95% for stationary plates in daylight conditions
3. Continuous processing without crashing or significant lag
4. Exported logs can be manually verified against physical counts

## 4. Phase 2 — Permit Validation & Station Deployment (Current)

### 4.1 Features (Delivered)

**Permit Database Integration**
- Local SwiftData storage of permit records with plate, owner, permit type, status, and lot zone
- Real-time plate authorization checking against the permit database
- Fuzzy matching for OCR-similar characters (O/0, I/1, B/8, etc.)
- Color-coded status overlay: Authorized (green), Wrong Lot (orange), Expired (yellow), Unknown (red)
- Distinct audio and haptic feedback per status type

**Geofencing**
- Parking lot boundaries defined as coordinate polygons
- Automatic current-lot detection using Core Location
- Wrong-lot detection: flags vehicles parked in lots they aren't permitted for
- Lot management UI with map preview

**Admin / Officer Mode**
- Officer mode (default): Camera scanner, scan log, and export only — simple, distraction-free
- Admin mode (passcode-protected): Access to database management, lot management, settings
- Configurable admin passcode (default: 1234)

**Data Management**
- JSON file import for permits and lots without rebuilding the app
- Import via AirDrop, Files app, or any file source
- Documents-directory override: imported data takes precedence over bundled data
- School name configuration for multi-school deployment

**Export**
- CSV export with plate text, confidence, auth status, permit holder, and vehicle info
- Optional diagnostic CSV with raw OCR data for accuracy analysis
- Share sheet integration for AirDrop, email, etc.

### 4.2 Success Criteria

1. Officers can use the app without accidentally modifying permit data or lot boundaries
2. Permit data can be updated on the station iPad without developer involvement
3. The app correctly identifies authorized, unauthorized, wrong-lot, and expired permits
4. Export data is sufficient for enforcement records

## 5. Users

**Primary user:** University campus police officers performing parking lot patrols.

**Admin user:** IT staff or department supervisor who manages permit data, lot boundaries, and app settings.

**Target customer:** University campus police departments (starting with Moravian University, expanding to other schools).

## 6. Technical Constraints

- Must use Apple-native frameworks (Vision, AVFoundation) — no third-party OCR dependencies
- Must work offline — all data is local, no network requirements
- iOS deployment target: iOS 17.0
- Swift 5.9+, SwiftUI, SwiftData

## 7. Distribution Strategy

| Stage | Method | Details |
|-------|--------|---------|
| Development | Xcode direct install | Developer deploys to test devices |
| Internal testing | TestFlight | Invite station Apple ID, OTA updates |
| Production sales | Apple Business Manager + Custom Apps | Private App Store listing, schools use ABM to deploy to managed devices |

Custom Apps via ABM is the recommended B2B distribution model — the app goes through App Store review but is only visible to authorized organizations. No enterprise certificates or sideloading required.

## 8. Future Phases

### Phase 3 — Cloud Sync & Multi-Tenancy
- Cloud backend with per-school tenant data
- School onboarding flow: license key -> pull permits/lots from cloud
- Scan log sync for reporting dashboards
- DataProvider protocol already in place to support this swap

### Phase 4 — State Database Integration
- Connect to PA state license plate systems (JNET/CLEAN)
- Broader vehicle checks beyond university permits

### Phase 5 — Citation Workflow
- Allow officers to initiate enforcement actions from the app
- Citation generation and tracking

### Phase 6 — Reporting & Analytics
- Scan history and enforcement metrics
- Lot coverage maps
- Usage analytics per school

## 9. Open Questions

| # | Question | Status |
|---|----------|--------|
| 1 | What iPad models do target schools have available? | Open |
| 2 | What is the state license plate lookup system (JNET? CLEAN?)? API or manual? | Open |
| 3 | Are there privacy/policy requirements around storing scanned plate data? | Open |
| 4 | What pricing model for multi-school sales? | Open |
| 5 | Do schools need custom branding (logo, colors)? | Open |
