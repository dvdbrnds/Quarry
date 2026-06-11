# Quarry: Strategy & Build Discussion

*Working notes from Cowork conversation, May 28, 2026. Companion to Bird_Dog_Strategy_Discussion.md and SheepDog_POC_Spec.md.*

---

## 0. Where this started

Bird Dog is built and working: a native iOS LPR scanner for campus parking enforcement. SheepDog is the next-level idea, a sensor-based tool distinct enough from the LPR that it needs its own path. Over this conversation SheepDog got defined, the build approach got specced, the two tools got recognized as a complementary pair, and the pair got an umbrella name: Quarry.

The dog logic: a bird dog points and flushes (active, handler-driven, finds the one bird). A sheepdog herds and guards (continuous, autonomous, watches the whole flock). Two different working dogs, one handler.

---

## 1. What SheepDog is

A sensor-based campus parking platform. Bird Dog finds the exception by sight; SheepDog watches the whole flock continuously with always-on sensors. The sensor approach is different enough from the LPR to earn its own name, but it is not a separate product. The two are two modes of one system.

---

## 2. Strategy: two parallel tracks, not one gated by the other

Early framing treated SheepDog as gated by Iota (the 800 MHz sensor partner). That was wrong. The correction:

- **Bird Dog is a pure software play.** Proof pack, IACLEA abstract, Lehigh Valley peer demos. None of it waits on anyone.
- **SheepDog is not gated either, it is parallel.** What is band-agnostic is the concept and the software: a sensor that says "vehicle present," a transponder that says "permit #4471 entered," a beacon that says "you're in the faculty zone." None of that cares whether the radio is 800 MHz, LoRa, BLE, or WiFi. You can prove the whole workflow on commodity hardware now.
- **What is actually Iota-specific is narrow:** range, battery life, deck penetration, network independence. Those are production deployment economics, not concept. They decide whether SheepDog scales cheaply, not whether it works.

So Iota does not gate the proof. It improves the production version.

---

## 3. The POC (full spec lives in SheepDog_POC_Spec.md)

Demonstrate end to end on cheap BLE, then transition the radio to Iota 800 MHz where battery life and range jump and almost no software changes.

**Two demos:**

1. **Hangtag (ePermit on approach).** The permit hangtag is itself a sensor: a coin-cell BLE beacon broadcasting a permit ID. The iPad already running Bird Dog reads it directly, no extra reader. Permit preloads before OCR fires, so the scan becomes confirmation, not lookup. Anti-spoofing: a hardware permit can't be Photoshopped, and a beacon/plate mismatch is a flag.
2. **Occupancy sensor on a parking spot.** A coin-cell BLE sensor with a magnetometer detects the steel mass of a vehicle and broadcasts occupied/vacant. A small powered BLE-to-WiFi gateway relays state over the existing lot WiFi.

**Radio decision:** everything is coin-cell BLE, one standard top to bottom. Coin cells rule out WiFi on the sensors (WiFi drains a coin cell in hours). The lot WiFi carries a powered gateway, not the sensors. For the first proof, no gateway is even needed: hangtag beacon to iPad to Bird Dog.

**Cheapest-path BOM:** roughly $80 to $120 total. BLE beacon cards for hangtags (~$8 to $15 each), a Seeed XIAO nRF52840 plus a QMC5883L magnetometer for the occupancy node (~$12), a Raspberry Pi Zero 2 W or ESP32 as the gateway (~$5 to $15), and the iPad you already own as the reader.

**Radio-agnostic data contract:** every sensor message shaped the same way now (`sensorId`, `type`, `payload`, `rssi`, `timestamp`) so the 800 MHz swap touches only firmware and the gateway, never the app or dashboard.

**BLE now vs 800 MHz later:** BLE gives 10 to 50 m range and 1 to 2 year coin-cell life and needs a gateway per lot. Iota 800 MHz gives hundreds of meters through walls, miles line-of-sight, 5 to 10 year coin-cell life, one gateway per many lots, and no WiFi dependency (works in decks and dead zones). The app and dashboard code are unchanged across the swap.

---

## 4. First principles that shape everything

**Complementary by design.** Two modes of one system, not two products. The hangtag preloads permits into Bird Dog. Zone sensors auto-switch Bird Dog's lot context. A sensor hot-list hit pushes to the cart. Every plate Bird Dog reads becomes a data point in SheepDog's continuous record. Active scan and passive mesh, feeding each other.

**One developer, one codebase.** Both tools are built and maintained by one person. That is a hard architecture constraint. One data model, one mental model. SheepDog reuses Bird Dog's `PlateAuthService`, the SwiftData permit and lot models, the admin UI, and the session-history benchmarking. No second parallel stack. (This walked back an earlier suggestion to stand up a separate MQTT broker plus web dashboard. For one dev that is a second thing to keep alive. Occupancy surfaces inside Bird Dog's existing admin mode instead, and the POC gateway just POSTs to the iPad.)

---

## 5. Repo decision

Build SheepDog inside the existing Bird Dog repo. Do not spin up a new repo or a monorepo with tooling.

Reasoning: most of SheepDog is Bird Dog code (the beacon service injects into `PlateAuthService`, occupancy surfaces in the existing admin mode, both share the SwiftData models). A second repo means either duplicated models or a cross-repo dependency seam, which is pure tax for a solo dev.

The one wrinkle is non-Swift code: the sensor firmware (nRF52) and the gateway (ESP32 or Pi). That argues for a `firmware/` folder beside the app in the same repo, not a separate repo. Zero monorepo tooling needed:

```
/  (the existing repo)
  BirdDog.xcodeproj   (app: Bird Dog scan + SheepDog sensor features)
  firmware/
    hangtag-beacon/
    occupancy-sensor/
    gateway/
```

When to split later: if SheepDog grows a real server backend on its own deploy cadence, or if student builders need an isolated repo without write access to the core app. Neither is true today; splitting early is the expensive direction.

The repo is named `birddog` but is about to house the pair. Renaming a git repo is cheap with no external dependents, so now is the painless time to move it under the umbrella name.

---

## 6. Iota: a partnership, not a negotiation

Important reframe. Earlier notes talked about "leverage" over Iota. That was both the wrong word and, once the facts came in, the wrong frame.

Iota is entering an institutional partnership with Moravian: they want their devices supported on campus and they want to partner with student software builders. SheepDog falls neatly into that. It is the marquee example of exactly what they want: campus-and-student-built software running on Iota hardware.

What follows:

- The BLE POC is not a bargaining chip, it is a head start. By the time the partnership formalizes, the concept is proven and the integration is written. The 800 MHz transition is the partnership delivering its upside.
- The moat against competitors (WiseSight) still holds but the mechanism flips. You do not pry exclusivity out of Iota. Being their reference campus and the deepest first integration is the moat, and that comes from being the partner who built the showcase. Worth confirming what "exclusivity" even means inside the partnership.
- The student-builder piece connects straight to the AI Dev Center and the AI-across-the-curriculum narrative. Strong for Bryon and Cabinet, strong for Iota's own marketing.

**The big upside:** a real possible outcome is Iota creating a parking-management vertical they don't currently offer, seeded by this campus pilot and student builders. That makes Moravian the originator of a market for the hardware partner, not a customer in it.

**The one thing to protect:** if Moravian's concept, software, and field-proven design become the foundation of an Iota parking vertical, that contribution needs to be recognized and protected before it ships. The difference between "we helped Iota launch parking" and "we co-own the thing that launched it" is entirely in the terms, and terms get written early or not at all. This is the most important reason to get Heather Hosfeld's IP framework right. It now needs to cover the SheepDog software, any co-developed sensor IP, and student contributions.

---

## 7. Naming the umbrella: Quarry

The pair needed an umbrella name. The path: rejected pure dog-collective names (Brace, Pack, Whistle, Kennel) and hunting-vs-herding pair names (Stock & Field, Field & Fold, Hunt & Herd) in favor of a single term that encompasses both.

**Selected: Quarry.** It names the one thing both dogs share, the target. A bird dog and a sheepdog have opposite instincts, but pointed at the same campus they are both working the same quarry: the unauthorized vehicle, the expired permit, the overstay. Bird Dog finds it by sight, SheepDog finds it by sensor, both are after the same quarry. The name organizes around the job, not the dogs. It is also a strong single word with a useful second meaning (a place you work to extract something of value).

**Logo direction:** keep the word Quarry unchanged and put the parking connection in the wordmark/logo rather than respelling. Considered and set aside: "Carry" (bakes "car" into the letters but loses the meaning and is weak for search/trademark) and "Quarrk" (Quarry + Park, but collides with Q-Park, a real parking company, and with Quark). Quarry-plus-logo keeps the meaning and the distinctiveness and still reads as parking on sight, with parking living in the mark (the Q as a tire, wheel, or hiding the universal parking "P").

---

## 8. Brand system plan (in progress)

Existing Bird Dog brand, for reference: institutional navy (`#0a1428` family) plus brass/mustard accent, Space Grotesk / Inter / JetBrains Mono, greyhound silhouette as the Moravian nod, serious law-enforcement tone. Delivered as a design-canvas HTML brand book with a `brand.css` token file and rendered logo PNGs.

Plan: one shared design system with three skins. Bird Dog and SheepDog as siblings, Quarry as the parent they sit under.

Open design decisions (to confirm before building the parallels):

- **Scope per brand:** core first (token CSS, primary wordmark plus logo directions, one-pager) versus the full kit (logos, app icons, splash, login art, spec sheet, one-pager).
- **SheepDog look:** it is a herding dog and the sensor platform. Bird Dog owns navy plus brass plus greyhound, so SheepDog needs differentiation. Candidates: a Border Collie / herding-dog silhouette with a signal-green or signal-teal accent on the kept navy base, or an abstract sensor mark with no literal dog.
- **Quarry mark:** parent brand with a neutral palette (navy plus steel/graphite) so the two dog brands are the colorful children. Candidates: a parking-P fused with a crosshair/reticle (parking plus target), a quarry-cut Q monogram, or a type-led wordmark with a subtle parking glyph.

---

## 9. Open questions / next decisions

- Confirm the brand-system decisions in section 8, then build the SheepDog and Quarry kits as parallels to Bird Dog.
- Hangtag: issue new permits with the beacon built in, or retrofit beacons into existing Moravian hangtags.
- Which lot for the occupancy demo, and whether its WiFi reaches the chosen spot.
- Dashboard scope for the demo: bare occupied/vacant, or add zone and time-in-space.
- Rename the repo under the Quarry umbrella (cheap now, keep history, fix the remote).
- Heather Hosfeld IP framework expanded to cover SheepDog software, co-developed Iota sensor IP, and student contributions.
- Iota meeting: confirm what "exclusivity" means inside the partnership, and scope the parking-vertical possibility and Moravian's stake in it.
