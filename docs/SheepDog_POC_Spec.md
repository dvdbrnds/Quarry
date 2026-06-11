# SheepDog: End-to-End POC Spec

*Working spec, May 28, 2026. Companion to Bird_Dog_Strategy_Discussion.md*

## What SheepDog is

A sensor-based campus parking platform. The sensor approach is distinct enough from Bird Dog (the mobile LPR scanner) that it gets its own name, but not its own silo. Bird Dog points and flushes: active, officer-driven, finds the one violator. SheepDog herds and guards: continuous, autonomous, watches the whole flock. They're a working pair with the same handler.

## First principles

**Complementary by design.** These are two modes of one system, not two products. The hangtag preloads permits into Bird Dog before OCR. Zone sensors auto-switch Bird Dog's lot context so the officer never picks a lot. A sensor hot-list hit pushes to the cart. Every plate Bird Dog reads becomes a data point in SheepDog's continuous record. Active scan and passive mesh, feeding each other.

**One developer, one codebase.** Both tools are built and maintained by one person. That is a hard architecture constraint, not a footnote. One data model, one mental model. SheepDog reuses Bird Dog's `PlateAuthService`, the SwiftData permit and lot models, the admin UI, and the session-history benchmarking. No second parallel stack. Keep the maintenance surface as small as the demo allows: the iPad stays the hub where it can, occupancy surfaces inside Bird Dog's admin mode, and any gateway talks to the smallest backend possible, or none in the POC.

## The thesis behind this POC

Prove the concept now on cheap, commodity BLE hardware. The application layer (permit logic, occupancy logic, Bird Dog handoff, dashboard) is radio-agnostic. When we transition the radio to Iota 800 MHz sub-GHz, battery life skyrockets and range jumps to miles line-of-sight in areas with low cellular or WiFi coverage, and almost none of the software changes. The demo we build is roughly 90% of the production code. The migration is a hardware swap behind the same data contract.

That makes this POC two things at once: a working Moravian pilot, and a head start on the Iota partnership. Iota is coming in as an institutional partner who wants their devices on campus and wants to work with student software builders. SheepDog is the marquee example of exactly that: campus-and-student-built software running on Iota hardware. By the time the partnership formalizes, the concept is proven and the integration is written. The 800 MHz transition is the partnership delivering its upside, not a concession anyone extracts.

## The two demos

### Demo 1: Hangtag (ePermit on approach)

The permit hangtag is itself a sensor. A coin-cell BLE beacon advertises a permit ID. The iPad already running Bird Dog reads it directly, no extra reader hardware. Permit looks up before OCR even fires, so the plate scan becomes confirmation, not lookup. Scan-to-flag latency drops to near zero.

The anti-spoofing beat: a hardware permit can't be Photoshopped. If the beacon's permit ID and the OCR'd plate don't match, that's a flag (swapped or counterfeit permit). Good live demo moment.

### Demo 2: Occupancy sensor on a parking spot

A coin-cell BLE sensor with a magnetometer detects the steel mass of a vehicle and broadcasts occupied/vacant on state change. Magnetometer is the industry standard for parking pucks: immune to lighting, weather, and shadows. A small powered gateway on the spot's lot relays state over the existing lot WiFi to a live dashboard.

The demo moment: a car pulls into the spot, the dashboard flips to occupied in real time, no camera, no officer present.

## Architecture

Everything is coin-cell BLE. One radio standard top to bottom.

- **Sensors** (hangtag beacon, occupancy puck): coin-cell BLE, broadcast only, sleep otherwise.
- **Mobile read path** (hangtag): the roving iPad reads beacons as the cart passes. No gateway needed.
- **Fixed read path** (occupancy): a powered BLE-to-WiFi gateway per lot relays always-on sensor state. The gateway is the only thing on WiFi, and it's plugged into power so battery is a non-issue.
- **Platform**: keep it inside Bird Dog. Occupancy surfaces in the existing admin mode, reusing the SwiftData models and UI already there. For the POC the gateway can POST straight to the iPad on the lot WiFi, no broker, no separate web app. If always-on occupancy later needs to outlive the cart, add the smallest backend that does that one job, not a second platform. One developer, one stack.

Coin-cell sensors can't talk WiFi directly (WiFi drains a coin cell in hours). So the lot WiFi carries the gateway, not the sensors. The gateway sits one layer back.

## Bill of materials (cheapest path)

Demo-grade quantities. Prices approximate, retail, small qty.

| Item | Purpose | Qty | Unit | Notes |
|---|---|---|---|---|
| BLE beacon card (nRF52, e.g. MINEW / Feasycom) | Hangtag transponder | 5 | $8–15 | Hangtag form factor, coin cell, 1–2 yr. UUID/major/minor encodes permit ID. |
| Seeed XIAO nRF52840 | Occupancy sensor MCU | 1–2 | $10 | BLE, coin-cell friendly, deep sleep. |
| QMC5883L magnetometer | Vehicle presence | 1–2 | $2 | I2C, detects steel mass. |
| CR2032 coin cells + holders | Power | few | $1 | |
| Raspberry Pi Zero 2 W (or ESP32) | BLE-to-WiFi gateway | 1 | $15 (or $5) | Powered, backhauls over lot WiFi via MQTT. |
| iPad | Bird Dog + hangtag reader | have it | — | Already owned. The reader is the device you already run. |

Total new spend: roughly $80–120 for both demos.

## Bird Dog integration

New service, `BeaconPermitService`:

- Scan for beacons via CoreLocation iBeacon ranging (or CoreBluetooth).
- Map beacon ID to permit, pull the record from SwiftData.
- Inject the result into `PlateAuthService` as a pre-resolved candidate before OCR runs.
- On OCR: plate matches the preloaded permit, instant confirm. Plate mismatch, flag as possible swapped/counterfeit permit.

This slots into the existing data flow (Camera → PlateRecognitionService → PlateReaderViewModel → PlateAuthService). The beacon just gives PlateAuthService a head start.

## The radio-agnostic data contract

Design every sensor message the same way now so the 800 MHz swap is clean:

```
{ sensorId, type, payload, rssi, timestamp }
```

Whether that arrives via BLE-on-iPad, BLE-gateway, or 800 MHz-gateway, the platform doesn't care. Build to this contract and the migration touches only the radio firmware and the gateway, never the app or the dashboard.

## BLE now vs 800 MHz later

| | BLE (POC) | Iota 800 MHz (production) |
|---|---|---|
| Range | 10–50 m | Hundreds of m through walls, miles line-of-sight |
| Coin-cell life | 1–2 yr | 5–10 yr |
| Gateway density | One per lot | One per many lots / campus |
| Network dependence | Lot WiFi for backhaul | None. Works in decks, dead zones, low-coverage areas |
| App / dashboard code | — | Unchanged |

## Partnership and the parking vertical

Iota doesn't offer parking management today. A real outcome of this work: SheepDog seeds a new vertical for them, built on a campus pilot and student builders. That makes Moravian the originator of a market for the hardware partner, not a customer in it.

The moat against WiseSight still holds, but the mechanism flips. You don't pry exclusivity out of Iota. Being their reference campus and the deepest first integration is the moat, and that comes from being the partner who built the showcase. Worth confirming what exclusivity even means inside an institutional partnership, because it may be looser and friendlier than the original strategy doc assumed.

The one thing to protect: if Moravian's concept, software, and field-proven design become the foundation of an Iota parking vertical, that contribution needs to be recognized and protected before it ships. The difference between "we helped Iota launch parking" and "we co-own the thing that launched it" is entirely in the terms, and terms get written early or not at all.

## What this POC unblocks

- A working Moravian pilot: the "show, don't tell" artifact the strategy doc kept asking for.
- A head start on the Iota partnership: concept proven and integration written before the partnership formalizes, so it begins from a built thing.
- The student-builder and AI Dev Center story: a student-built project on a partner's hardware, strong for Bryon and Cabinet and strong for Iota's own marketing.
- Input for Heather's IP framework: now there's a concrete sensor design, a Bird Dog integration, co-developed sensor work, and student contributions to scope. This is the most important reason to get the framework right.

## Open items

- Hangtag: issue new permits with the beacon built in, or retrofit beacons into existing Moravian hangtags. Decides production form factor. (Doesn't block the demo; we build a demo hangtag either way.)
- Which lot for the occupancy demo, and whether to confirm its WiFi reaches the chosen spot.
- Dashboard scope for the demo: bare occupied/vacant, or add zone and time-in-space.
