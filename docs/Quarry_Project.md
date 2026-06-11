# Quarry: Campus Parking Platform

*Single source of truth. Last updated June 9, 2026.*

---

## Status at a glance

| Item | Status |
|---|---|
| **Bird Dog** (mobile LPR) | Built, in use by Moravian campus police |
| **SheepDog** (sensor platform) | POC specced, parts ordered, Pi gateway running |
| Quarry umbrella brand | Named, design decisions open |
| Heather Hosfeld IP framework | Pending (target July 15–30, 2026) |
| Iota 800 MHz partnership | Pending first meeting |
| Proof pack | Not started |
| IACLEA abstract | Not submitted |
| WiseSight outreach | Blocked by Iota + IP clarity |

### Blocked (waiting on others)

1. **IP framework (Heather Hosfeld, July 15–30).** Nothing gets marketed or licensed until this covers: Bird Dog app, SheepDog software, co-developed Iota sensor IP, brand/trademark, student contributions. Flag Bird Dog explicitly so it's in scope. Recommend Moravian-owned IP with nonexclusive licenses to peer non-profits, optional revenue share.
2. **Iota meeting.** Confirm: which capabilities are off-the-shelf vs. custom-build vs. out of scope, pricing, timeline, what "exclusivity" means inside the partnership.
3. **Campus police chief testimonial.** Needed for proof pack.

### Next moves (not blocked)

1. Build the SheepDog BLE POC (parts in hand, Pi running). See `sheepdog-ble/SheepDog_Build_Plan.md`.
2. Build the proof pack: benchmark chart (pull from `SessionHistoryManager`), 60-sec demo video from a golf cart, IT spec sheet.
3. Submit IACLEA conference abstract. Creates a forcing function for the proof pack and IP conversation.
4. Consolidate repos under Quarry umbrella.
5. Lehigh Valley peer-CIO intros: Lafayette, Lehigh, Muhlenberg, DeSales, Cedar Crest, Northampton CC. Five warm intros, five demos, two pilots = proof to cite everywhere else.
6. Finalize brand system decisions (Section 10 below), then build SheepDog and Quarry brand kits.

### Open design decisions

- Hangtag: issue new permits with built-in beacon, or retrofit beacons into existing hangtags. (Doesn't block the demo.)
- Which lot for the occupancy demo, and whether its WiFi reaches the chosen spot.
- Dashboard scope for demo: bare occupied/vacant, or add zone and time-in-space.
- SheepDog brand look and Quarry parent mark (see Section 10).

---

## 1. What Quarry is

A campus parking platform with two modes, named for the one thing both share: the target.

**Bird Dog** points and flushes: active, officer-driven, finds the one violator by sight (LPR).
**SheepDog** herds and guards: continuous, autonomous, watches the whole flock by sensor.

Two different working dogs, one handler. They aren't separate products. They feed each other: hangtag beacons preload permits into Bird Dog before OCR fires, zone sensors auto-switch Bird Dog's lot context, sensor hot-list hits push to the cart, every plate Bird Dog reads becomes a data point in SheepDog's continuous record. Active scan and passive mesh, one system.

"Quarry" also carries a useful second meaning: a place you work to extract something of value.

**The evolution this enables:** today Bird Dog is LPR-first (camera finds the plate, then looks up the permit). With active radio hangtags (BLE now, Iota 800 MHz in production), the permit identifies itself on approach. LPR becomes the backup/confirmation layer. The officer knows the permit status before the camera even fires. SheepDog doesn't just add to Bird Dog, it changes what Bird Dog is.

---

## 2. Architecture: one developer, one codebase

Both tools are built and maintained by one person. That is a hard constraint, not a footnote. One data model, one mental model. SheepDog reuses Bird Dog's `PlateAuthService`, the SwiftData permit and lot models, the admin UI, and the session-history benchmarking. No second parallel stack. Occupancy surfaces inside Bird Dog's existing admin mode. The POC gateway POSTs to the iPad on the lot WiFi, no broker, no separate web app.

### Data flow

```
                    ┌─────────────────────────────────┐
                    │           Bird Dog iPad          │
                    │                                  │
  Beacon hangtag ──►│ BeaconPermitService              │
  (BLE / 800 MHz)   │   ↓ pre-resolved permit         │
                    │ PlateAuthService ◄── PlateRecognitionService ◄── Camera
                    │   ↓                              │
                    │ UI (officer view + admin view)    │
                    │   ↑                              │
  Occupancy puck ──►│ Gateway HTTP POST ──► SwiftData  │
  (via Pi gateway)  │                                  │
                    └─────────────────────────────────┘
```

### Radio-agnostic data contract

Every sensor message shaped the same way so the 800 MHz swap is clean:

```json
{ "sensorId": "occ-001", "type": "occupancy", "payload": "occupied", "rssi": -42, "timestamp": "2026-06-09T14:30:00Z" }
```

Whether arriving via BLE-on-iPad, BLE-gateway, or 800 MHz-gateway, the platform doesn't care. Migration touches only radio firmware and gateway, never app or dashboard.

### Repo structure (target)

```
quarry/                      (repo root)
  BirdDog.xcodeproj          app: Bird Dog scan + SheepDog sensor features
  BirdDog/                   Swift source
    Services/
      PlateAuthService.swift
      BeaconPermitService.swift   ← new for SheepDog
      PlateRecognitionService.swift
      ...
    Models/
    Views/
    ViewModels/
  firmware/
    hangtag-beacon/           beacon card config notes
    occupancy-sensor/         XIAO nRF52840 + QMC5883L sketch
    gateway/                  Pi Python BLE-to-HTTP bridge
```

---

## 3. Bird Dog (mobile LPR)

### What it is

A native iOS app for campus police to scan license plates in real time from a golf cart. iPad + USB camera, checks plates against the permit database, flags unauthorized/expired/wrong-lot vehicles instantly.

### Tech stack

Swift 5.9 / SwiftUI / iOS 17+, MVVM. AVFoundation camera pipeline (built-in + external USB). Vision framework for on-device OCR. SwiftData for local permit/lot storage. Core Location for lot geofencing. XcodeGen for project generation.

### Key design decisions

- **External camera first.** USB global-shutter cameras (e-con See3CAM) over built-in iPad camera, with polling/retry, relaxed confidence thresholds, and grayscale enhancement for colored plates.
- **Multi-frame confirmation with CandidateVoter.** Character-level majority voting across frames resolves OCR ambiguity (K/N, 1/7, O/0). Local format plates instant-confirmed in 1 frame; vanity plates require 3.
- **3-tier database lookup.** Exact → fuzzy (confusable character substitution) → smart (transpositions, substring extraction, truncation recovery, edit-distance scan).
- **Extensive reject list** in PlatePatternMatcher. Hundreds of words (signs, car makes/models, dealer stickers, campus-specific noise).
- **Admin/Officer mode.** Officers: scanner + log + export. Admins (passcode-gated): database, lot, settings management.
- **Session history.** Named test sessions via SessionHistoryManager, compared for benchmarking (latency, plates/min).

### Existing brand

Institutional navy (#0a1428 family) plus brass/mustard accent. Space Grotesk / Inter / JetBrains Mono. Greyhound silhouette as the Moravian nod. Serious law-enforcement tone. Delivered as a design-canvas HTML brand book with brand.css token file and rendered logo PNGs.

### Ownership

Built by David Brandes (CIO) for Moravian University. Work-for-hire IP, Moravian owns it. Market as "Moravian's Bird Dog, built and maintained by the Office of the CIO."

---

## 4. SheepDog (sensor platform)

### What it is

Always-on sensors that watch the parking lot continuously. Two capabilities: active radio hangtags that identify permitted vehicles on approach, and occupancy pucks that detect whether a space is occupied. Bird Dog finds the exception by sight; SheepDog watches the whole flock.

### The POC thesis

Prove the concept on cheap commodity BLE hardware. The application layer is radio-agnostic. When the radio transitions to Iota 800 MHz, battery life skyrockets and range jumps, and almost none of the software changes. The demo is roughly 90% of the production code.

This makes the POC two things at once: a working Moravian pilot, and a head start on the Iota partnership. By the time the partnership formalizes, the concept is proven and the integration is written.

### Two demos

**Demo 1: Hangtag (ePermit on approach).** The permit hangtag is a coin-cell BLE beacon advertising a permit ID. The iPad reads it directly via CoreLocation iBeacon ranging, no extra hardware. Permit pre-loads before OCR fires, so the plate scan becomes confirmation. Anti-spoofing: a hardware permit can't be Photoshopped. Beacon/plate mismatch = flag.

**Demo 2: Occupancy sensor.** A coin-cell BLE sensor with a magnetometer detects the steel mass of a vehicle, broadcasts occupied/vacant on state change. A powered gateway on the lot relays state over WiFi. Demo moment: car pulls in, dashboard flips to occupied in real time, no camera, no officer.

### BLE POC hardware

Full shopping list with Amazon links in `sheepdog-ble/SheepDog_BLE_Shopping_List.md`. Total spend ~$185–220.

| Item | Purpose | Status |
|---|---|---|
| 5x Feasycom FSC-BP105D beacon cards | Hangtag permits | Ordered |
| 2x Seeed XIAO nRF52840 | Occupancy sensor MCU | Ordered |
| 1x ACEIRMC QMC5883L GY-273 10-pack | Magnetometer | Ordered |
| 1x Raspberry Pi 3 Model B+ | BLE-to-WiFi gateway | Running |
| MicroSD, power supply, jumpers, breadboards, USB-C cable, CR2032 batteries | Support | Ordered |

### Build sequence

Eight scenes, detailed in `sheepdog-ble/SheepDog_Build_Plan.md`. Scenes 1–3 are software only (gateway setup, beacon config, BeaconPermitService). Scenes 4–7 are the hardware build (wire sensor, flash firmware, gateway script, Bird Dog integration). Scene 8 is the full dress rehearsal in a parking lot.

### Bird Dog integration

New service, `BeaconPermitService`:

1. Scan for beacons via CoreLocation iBeacon ranging.
2. Map beacon ID to permit, pull record from SwiftData.
3. Inject result into `PlateAuthService` as a pre-resolved candidate before OCR runs.
4. On OCR: plate matches → instant confirm. Mismatch → flag.

Slots into existing data flow. The beacon gives PlateAuthService a head start.

---

## 5. Evolution path

| Stage | Identification method | LPR role | Radio |
|---|---|---|---|
| **Today** | Passive hangtag (sticker) | Primary | None |
| **BLE POC** | Active beacon hangtag | Confirmation/backup | BLE |
| **Production** | Active radio hangtag | Fallback for non-equipped vehicles | Iota 800 MHz |

### BLE now vs 800 MHz later

| | BLE (POC) | Iota 800 MHz (production) |
|---|---|---|
| Range | 10–50 m | Hundreds of m through walls, miles line-of-sight |
| Coin-cell life | 1–2 yr | 5–10 yr |
| Gateway density | One per lot | One per many lots / campus |
| Network dependence | Lot WiFi for backhaul | None (works in decks, dead zones) |
| App / dashboard code | — | Unchanged |

---

## 6. Iota 800 MHz: what it enables

Sub-GHz 800 MHz gives four things WiFi/BLE can't: real range, long battery life, penetration through parking decks, and zero dependency on campus WiFi.

**ePermit transponders.** Windshield decal broadcasts permit info on approach. Scan-to-flag latency effectively zero. Guest/visitor: temporary transponders with auto-expiry.

**Lot intelligence.** Lot-perimeter beacons tell the cart which lot and zone it's in. GPS is unreliable in lots. Bird Dog auto-switches context.

**Space-level occupancy.** Live utilization dashboard, reserved-space monitoring, time-in-space tracking, heat maps. WiseSight's Hawk Occupancy at small-campus economics.

**Network independence.** No campus WiFi, no IT firewall tickets. Works in decks, during outages, doesn't expand attack surface.

**New workflows.** Hot-list alerts, geofenced violation alerts, officer safety beacon, stolen-vehicle BOLO across the mesh.

---

## 7. Iota partnership framing

This is a partnership, not a negotiation. Iota is entering an institutional partnership with Moravian: they want their devices on campus and want to work with student software builders. SheepDog is the marquee example.

- The BLE POC is a head start. Concept proven and integration written before the partnership formalizes.
- The moat is being their reference campus and deepest first integration.
- The student-builder piece connects to the AI Dev Center and AI-across-the-curriculum narrative.

**Big upside:** Iota doesn't offer parking management today. SheepDog seeds a new vertical for them. Moravian becomes the originator of a market, not a customer in it.

**Protect:** if Moravian's concept, software, and field-proven design become the foundation of an Iota parking vertical, that contribution needs to be recognized and protected before it ships. Terms get written early or not at all.

---

## 8. Market and positioning

### Market reality

Campus parking enforcement is dominated by commercial LPR: Genetec AutoVu, Avigilon, 3M PIPS, Vigilant. $50K–$200K+ per deployment. Most small-to-mid colleges can't justify those systems. Quarry occupies the gap.

### Quarry positioning

**One line.** A campus parking platform that combines mobile LPR with always-on sensors, built by a campus CIO, running on-device with zero cloud dependency.

**What it displaces.** Commercial LPR at $50K–$200K+ and fixed-camera occupancy systems.

**Core message.** "Enterprise parking intelligence, built by a campus for campuses. On an iPad and a mesh of coin-cell sensors. Without the cloud."

**Three differentiators:**

1. **On-device, no cloud.** No plate data leaves campus. FERPA-adjacent privacy story.
2. **Two modes, one platform.** Active scan (Bird Dog) + passive mesh (SheepDog) feed each other. No other small-campus system does both.
3. **Built by a peer.** Licensing from another CIO who maintains it because his own officers depend on it.

### Audiences

**Internal Moravian.** Bryon, Cabinet, campus police chief. In-house build, no vendor lock-in, on-device. Flagship AI Dev Center demo.

**Peer universities.** Lehigh Valley first, then broader small/mid liberal arts and regional publics through EDUCAUSE and IACLEA.

**Industry / conferences.** IACLEA Annual, EDUCAUSE, NACUBO Tech & Innovation.

**Adjacent verticals (phase 2).** Hospitals, corporate campuses, gated communities, K–12.

### WiseSight

AI parking enforcement (Columbus, OH). Strong on fixed infrastructure, sized for big municipal customers. Bird Dog serves the tier they can't profitably reach. Three possible structures: co-sell, OEM/white-label, or API integration. Don't approach until Iota and IP are locked down.

---

## 9. Strategic path

**Higher-ed-only license**, with adjacent scenarios (hospitals, corporate campuses, HOAs, K–12) where the operating profile matches.

### Two parallel tracks

- **Bird Dog** is a pure software play. Proof pack, IACLEA abstract, peer demos. Nothing waits on anyone.
- **SheepDog** is parallel, not gated by Iota. The concept and software are band-agnostic. Iota improves production economics, not whether it works.

### Channels

IACLEA (highest-leverage room), EDUCAUSE (CIO-to-CIO), NACUBO (cost story), Lehigh Valley peer-CIO outreach first, higher-ed CIO lists and newsletters.

### Proof points to build

- Benchmark chart from SessionHistoryManager (plates/min, latency, false-positive rate).
- Campus police chief testimonial.
- 60–90 second demo video from a golf cart.
- One-page IT spec sheet.

---

## 10. Brand system (in progress)

One shared design system, three skins. Bird Dog and SheepDog as siblings, Quarry as the parent.

**Bird Dog (established):** navy (#0a1428) + brass/mustard. Space Grotesk / Inter / JetBrains Mono. Greyhound silhouette. Law-enforcement tone.

**SheepDog (open):** candidates: Border Collie / herding-dog silhouette with signal-green or signal-teal accent on navy base, or abstract sensor mark.

**Quarry (open):** neutral palette (navy + steel/graphite). Candidates: parking-P fused with crosshair/reticle, quarry-cut Q monogram, or type-led wordmark. The Q as a tire, wheel, or hiding the universal parking "P."

**Logo direction:** keep the word Quarry unchanged, put the parking connection in the mark. Rejected: "Carry" and "Quarrk."

---

## 11. IP and legal

**Ownership.** Built on Moravian time/resources, Moravian owns it.

**Heather Hosfeld's IP framework (July 15–30, 2026) must cover:**
1. Bird Dog app
2. SheepDog software
3. Co-developed Iota sensor IP
4. Brand/trademark for the productized offering
5. Student contributions

**Recommendation:** Moravian-owned IP with nonexclusive licenses to peer non-profits, optional revenue share.

**The precondition that gates everything external:** nothing gets marketed, licensed, or shown to WiseSight until the IP framework is in place.

---

## File index

```
Quarry/
  docs/
    Quarry_Project.md                    ← this file
    Bird_Dog_Strategy_Discussion.md      ← original strategy notes (May 26)
    Quarry_Strategy_Discussion.md        ← original strategy notes (May 28)
  Bird Dog/                              ← Xcode project (app code)
  sheepdog-ble/                          ← BLE POC
    SheepDog_Build_Plan.md               ← 8-scene build sequence
    SheepDog_BLE_Shopping_List.md        ← vetted parts list with Amazon links
    SheepDog_POC_Spec.md                 ← original POC spec (May 28)
  brand/                                 ← Bird Dog brand assets (SheepDog + Quarry TBD)
```
