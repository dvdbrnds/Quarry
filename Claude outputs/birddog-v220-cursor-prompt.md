# Cursor Prompt — BirdDog v2.2.0 App Store Submission Prep

## Context

BirdDog is an iOS parking enforcement app (bundle ID: `edu.moravian.birddog`). We received MFi approval from Star Micronics for our thermal printer integration. The StarXpand SDK is already fully integrated -- this is purely a version bump and submission prep. No new code is needed.

## Steps

### Step 1: Bump version in project.yml

In `project.yml`, under `targets > BirdDog > settings > base`:

- Change `MARKETING_VERSION` from `"2.1.0"` to `"2.2.0"`
- Change `CURRENT_PROJECT_VERSION` from `"3"` to `"1"`

### Step 2: Update APP_STORE_REVIEW_NOTES.md

In `BirdDog/APP_STORE_REVIEW_NOTES.md`:

- Change the header from `v2.1.0` to `v2.2.0`
- Update the checklist version from `2.1.0` to `2.2.0`
- Update the build number note to say "currently 1"

### Step 3: Regenerate the Xcode project

Run in terminal:

```bash
xcodegen generate
```

This reads `project.yml` and regenerates `BirdDog.xcodeproj`. Resolve any SPM packages if prompted.

### Step 4: Verify StarXpand SDK integration (no changes needed, just confirm)

Confirm all of these are already in place:

- `project.yml` has `StarXpand-SDK-iOS` package from `"2.6.0"` with `StarIO10` product dependency and `ExternalAccessory.framework`
- `Info.plist` has `jp.star-m.starpro` in `UISupportedExternalAccessoryProtocols`
- `Info.plist` has `external-accessory` in `UIBackgroundModes`
- `Info.plist` has both `NSBluetoothAlwaysUsageDescription` and `NSBluetoothPeripheralUsageDescription`
- `PrinterService.swift` imports StarIO10 via `#if canImport(StarIO10)`

If any of these are missing, flag it. They should all be present already.

### Step 5: Build and test

1. Build the project in Xcode (Cmd+B) -- should compile with zero errors
2. Run on a physical device if available to confirm printer discovery still works
3. Archive for distribution (Product > Archive) to confirm the release build succeeds

## Constraints

- Do NOT modify `PrinterService.swift` or any other Swift source files
- Do NOT change the StarXpand SDK version (keep `from: "2.6.0"`)
- Do NOT change the bundle ID, team ID, or code signing settings
- Do NOT touch `Info.plist` -- it's already correct
- The only files that change are `project.yml` and `APP_STORE_REVIEW_NOTES.md`

---

## App Store Connect Review Notes (paste this into the Review Notes field)

```
This app uses MFi-certified Star Micronics thermal printers for printing parking citations via Bluetooth. The app has been approved by Apple for use with the following printers.

PPIDs and Printer Models:

121976-443675 — SM-S230i
121976-000847 — SM-T300i
121976-639631 — SM-T400i

MFi Protocol: jp.star-m.starpro

The Bluetooth connection is used exclusively for communicating with these thermal receipt printers to print parking citations in the field. No other external accessories are used.
```

## Submission Checklist

- [ ] Version: 2.2.0
- [ ] Bundle ID: edu.moravian.birddog
- [ ] Build number: 1
- [ ] Review notes: paste the text above
- [ ] Screenshots: update if UI changed since last submission
- [ ] Privacy policy URL: confirm it's current
- [ ] Export compliance: ITSAppUsesNonExemptEncryption = NO (already set in Info.plist)
