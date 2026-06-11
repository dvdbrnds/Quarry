# BirdDog — iOS Asset Package

Brand assets for the **BirdDog** campus parking-enforcement app (Moravian University beta).
Drop-in ready for an Xcode / Swift project.

---

## What's inside

```
BirdDog-Assets/
├─ Assets.xcassets/            ← drag this straight into your Xcode project
│  ├─ AppIcon.appiconset/      Single-size 1024² app icon (Xcode 14+ auto-generates the rest)
│  ├─ GreyhoundBrass.imageset/ Brass greyhound mark  @1x/2x/3x
│  ├─ GreyhoundNavy.imageset/  Navy greyhound mark   @1x/2x/3x
│  ├─ GreyhoundBone.imageset/  Off-white greyhound   @1x/2x/3x
│  ├─ LaunchLogo.imageset/     Larger brass mark for the launch screen
│  └─ BD*.colorset/            Named brand colors (see palette below)
└─ raw/                        Master PNGs + alternate app-icon styles
```

> **Note on scale suffixes:** the @2x / @3x files are named `-2x` / `-3x` on disk
> (the `@` character isn't filesystem-safe here). Xcode reads filenames from each
> `Contents.json`, so the catalog resolves correctly — no action needed. If you
> prefer the canonical `@` names, rename the files and update the three `filename`
> fields in the corresponding `Contents.json`.

---

## Install

1. In Xcode, delete the default `Assets.xcassets` **or** drag these named assets into your existing catalog.
2. To add the whole catalog: drag `Assets.xcassets` into the Project Navigator → check *Copy items if needed*.
3. Set **Target → General → App Icons and Launch Screen → App Icon Source** to `AppIcon`.

---

## Using the assets

### SwiftUI
```swift
Image("GreyhoundBrass")            // imageset name
    .resizable()
    .scaledToFit()
    .frame(height: 32)

Color("BDNavy")                    // colorset name
Text("BirdDog").foregroundStyle(Color("BDBrass"))
```

### UIKit
```swift
let mark = UIImage(named: "GreyhoundBrass")
view.backgroundColor = UIColor(named: "BDNavy")
```

### Launch screen
Use a **Launch Screen storyboard**: set the view background to `BDNavyDeep`
and center an `UIImageView` using `LaunchLogo`. (Apple no longer allows
full-bitmap launch images; compose with the color + logo.)

---

## Color palette

| Color set        | Hex       | Use |
|------------------|-----------|-----|
| `BDNavy`         | `#0A1428` | Primary brand / backgrounds |
| `BDNavyDeep`     | `#050B1A` | Splash / deepest surface |
| `BDNavy700`      | `#14274D` | Cards, raised surfaces on navy |
| `BDBrass`        | `#FBBF24` | Primary accent (CTAs, highlights) |
| `BDBrassDeep`    | `#CA8A04` | Accent on light backgrounds |
| `BDBone`         | `#F3F1EA` | Light surface |
| `BDBoneLight`    | `#FAFAF6` | Lightest surface / text on navy |
| `BDInk`          | `#14171C` | Primary text on light |
| `BDInkMute`      | `#5A6373` | Secondary text / captions |
| `BDSignalRed`    | `#B91C1C` | Violations, expired, tow |
| `BDSignalGreen`  | `#15803D` | Valid permit / success |

---

## Typography (add separately)

The brand uses three Google Fonts — add the `.ttf` files to your target and
register them in `Info.plist` under *Fonts provided by application*.

| Role     | Family            | Weights |
|----------|-------------------|---------|
| Display / wordmark | **Space Grotesk** | 400 / 600 / 700 |
| Body / UI          | **Inter**         | 400 / 500 / 600 / 700 |
| Plates / IDs / mono| **JetBrains Mono**| 400 / 500 / 600 |

Download: fonts.google.com/specimen/Space+Grotesk · /Inter · /JetBrains+Mono

---

## App icon notes

- `AppIcon-1024.png` is the production icon: solid `#0A1428` field, brass greyhound, no transparency, no pre-rounded corners (iOS applies the mask).
- Alternates in `raw/` (`AppIcon-BrassField`, `AppIcon-Bone`) can be wired up as
  **alternate app icons** via `setAlternateIconName(_:)` if you want selectable themes.

---

*BirdDog Patrol Suite · © 2026. Greyhound mark is an homage to Moravian University.*
