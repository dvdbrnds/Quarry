# Bird Dog — Strategy & Marketing Discussion

*Working notes from Cowork conversation, May 26, 2026*

---

## 1. Project Summary

**Bird Dog** is a native iOS app built for Moravian University campus police to scan license plates in real time while driving through parking lots (typically from an iPad mounted on a golf cart). It checks plates against the school's permit database and instantly flags unauthorized, expired, or wrong-lot vehicles.

### Tech Stack
- **Swift 5.9 / SwiftUI / iOS 17+** with MVVM architecture
- **AVFoundation** for camera pipeline (built-in and external USB cameras)
- **Vision framework** (VNRecognizeTextRequest) for on-device OCR
- **SwiftData** for local permit/lot storage
- **Core Location** for lot geofencing
- **XcodeGen** (`project.yml`) for project generation

### Key Architecture

Data flow: **Camera frames** (throttled ~6fps) → **PlateRecognitionService** (Vision OCR + pattern filtering) → **PlateReaderViewModel** (multi-frame confirmation, fuzzy dedup, candidate voting) → **PlateAuthService** (3-tier lookup: exact → fuzzy → smart) → **UI update + haptic/audio feedback**.

### Notable Design Decisions

1. **External camera support** — Prioritizes USB cameras (global shutter like e-con See3CAM) over built-in iPad camera, with polling/retry logic. External cameras get relaxed confidence thresholds and a grayscale enhancement pass for colored plates (yellow NJ, etc.).
2. **Multi-frame confirmation** with `CandidateVoter` — Character-level majority voting across frames resolves OCR ambiguity (K/N, 1/7, O/0). Local format plates (PA, NJ, etc.) instant-confirmed in 1 frame; vanity plates require 3.
3. **3-tier database lookup** — `exact` → `fuzzy` (confusable character substitution) → `smart` (transpositions, substring extraction, truncation recovery, edit-distance scan).
4. **Extensive reject list** in `PlatePatternMatcher` — Hundreds of words (signs, car makes/models, dealer stickers, campus-specific noise like "CIOCCA", "MORAVIAN") to filter false positives.
5. **Admin/Officer mode** — Officers get scanner + log + export. Admins (passcode-gated) get database, lot, and settings management.
6. **Session history** — Named test sessions, persisted via `SessionHistoryManager`, compared later for benchmarking (latency, plates/min).

### Ownership & Authorship

Built by David Brandes (CIO) for Moravian University. Work-for-hire IP — Moravian owns it. Heather Hosfeld's IP framework (target July 15–30, 2026) will need to cover Bird Dog explicitly for any peer-licensing or commercialization path.

---

## 2. Market Reality

Campus parking enforcement is currently dominated by commercial LPR systems — Genetec AutoVu, Avigilon, 3M PIPS, Vigilant — running $50K–$200K+ per deployment with annual cloud subscriptions and integrator fees. Most small-to-mid colleges (1,500–10,000 students) cannot economically justify those systems, so they enforce manually, accept high violator leakage, or stitch together half-solutions.

Bird Dog occupies the functional gap at iPad + USB camera price point.

---

## 3. Audiences

### Three audiences, three angles

**Internal Moravian.** Sell the "win" up to Bryon, Cabinet, and the campus police chief. Frame as: in-house build, no vendor lock-in, no data leaves campus (on-device OCR — especially important after the Canvas/Instructure breach). Flagship demo of what the AI Development Center can produce. Surface on weekly PC Reportables under Cybersecurity and New Program Tech Enablement.

**Peer universities (the real market).** Lehigh Valley first — Lafayette, Lehigh, Muhlenberg, DeSales, Cedar Crest, Northampton CC. Then broader small/mid liberal arts and regional publics through EDUCAUSE and IACLEA (campus law enforcement). Headline: *"Enterprise LPR accuracy, built by a campus, for campuses — under the cost of one parking ticket per cart per year."* Lead with a benchmark from session-history data (latency, plates/min, false-positive rate) — that's the credibility wedge.

**Industry / conferences.** IACLEA Annual, EDUCAUSE, NACUBO Tech & Innovation. Submit a session: *"Building a Campus-Grade License Plate Reader for the Price of an iPad."*

### Adjacent verticals (phase 2)

Same operating profile, different vertical: hospital and healthcare campuses (permit-based lots, in-cart enforcement, HIPAA-adjacent privacy posture — on-device matters). After that: corporate campuses with employee permit parking, gated communities, K–12 districts.

---

## 4. Positioning Brief (v1)

### One-line definition
An iPad-based license plate reader built by a campus CIO for campus enforcement officers, that flags parking violators against your permit database in real time, on-device, with zero cloud dependency.

### What it displaces
Commercial LPR at $50K–$200K+ per deployment with annual cloud subs. Bird Dog runs on iPad + USB camera.

### Core message
*"Enterprise LPR accuracy, built by a campus for campuses. On an iPad. Without the cloud. Under the cost of one stolen permit per year."*

### Three signature differentiators

1. **On-device, no cloud.** No plate data leaves campus. FERPA-adjacent privacy story is sharper every month given how breach-heavy higher ed has been.
2. **Officer-built workflow.** Works one-handed from a moving golf cart. External-camera-first (USB global-shutter), grayscale enhancement for colored plates, multi-frame confirmation. Tuned in actual campus lots.
3. **Built by a peer, supported by a peer.** Licensing from another CIO who maintains it because his own officers depend on it — not from a vendor whose sales engineer has never seen a campus golf cart.

### Proof points to build before any outreach
- Benchmark: plates/minute, end-to-end latency, false-positive rate (vs. commercial baseline or pre-Bird-Dog manual workflow). `SessionHistoryManager` already produces this — pull one representative session into a single-slide chart.
- Testimonial from Moravian's campus police chief.
- 60–90 second demo video shot from a golf cart in a Moravian lot.
- One-page IT spec sheet (hardware list, network/data posture, integration notes).

### Channels
- **IACLEA** — annual conference + magazine. Highest-leverage room. Submit a session.
- **EDUCAUSE** — Annual + regional events. CIO-to-CIO trust channel.
- **NACUBO** — Tech & Innovation track, business officers care about the cost story.
- **Lehigh Valley peer-CIO outreach first.** Five warm intros → five demos → two pilots = proof to cite everywhere else.
- **Higher Ed CIO lists / newsletters** — CIO Review, CHE tech coverage, EdTech Magazine Higher Ed.

### Strategic fork — paths considered

1. **Internal only** — flagship internal win, AI Dev Center showcase, no external surface
2. **Open source** — Moravian brand play, low maintenance if a community is seeded, fits AI-Across-the-Curriculum narrative
3. **Higher-ed-only license** ← *selected path* — peer-share model, modest revenue, mediated by Heather Hosfeld's IP framework
4. **Commercial spin-out** — biggest upside but real cost: IP cleanup, support model, business owner, liability

**Selected: Higher Ed only, with adjacent parking scenarios (hospitals, corporate campuses, HOAs, K–12) where the operating profile is the same — quickly identify violators against a known permit list.**

### Quietly important precondition
Built on Moravian time/resources → Moravian owns it. Market as "Moravian's Bird Dog, built and maintained by the Office of the CIO." Legally clean *and* a stronger marketing position (institutional weight, not solo developer risk).

### First three concrete moves (next 30 days)

1. **IP green light from Heather.** Bird Dog can't be marketed beyond Moravian until the IP/licensing framework (target July 15–30) covers it. Flag Bird Dog explicitly so it's in scope, not an afterthought. Recommend Moravian-owned IP with nonexclusive licenses to peer non-profits, optional revenue share.
2. **Build the proof pack.** Benchmark chart, 60-sec demo video, IT spec sheet, chief's testimonial. ~4 hours of work. Without this, no outreach lands.
3. **Submit one conference abstract.** IACLEA is the right first room. Submitting costs nothing and creates a forcing function for the proof pack and the IP conversation.

---

## 5. WiseSight Partnership / Complement Analysis

### What WiseSight is
AI parking enforcement (Columbus, OH; anchor customer Pittsburgh Parking Authority). Strong on fixed-infrastructure plays: Multi-Space LPR, Hawk Tracking, Hawk Occupancy, Eagle Eye video. They serve municipal, university, and parking-operator markets. They have a University Solutions tier and a Mobile LPR Assist product — but the lineup is sized for big municipal-scale customers. Cost structure almost certainly doesn't pencil out for a 2K-student liberal arts college.

### Where Bird Dog fits

- **Pricing tier they can't profitably serve.** WiseSight's University Solutions is built for the Pittsburgh-Parking-Authority-meets-Big-State-U end. Bird Dog is the small-and-mid college SKU under their floor — and that's most of higher ed by institution count.
- **Different operating mode.** WiseSight is fixed-camera-first (mounted, networked, cloud-analyzed). Bird Dog is mobile-cart-first (iPad, officer-driven, on-device). Same enforcement outcome, totally different deployment profile.
- **On-device, no cloud.** Moat against WiseSight in privacy-conscious verticals (small colleges, hospitals, K–12). Their architecture pushes to their cloud; Bird Dog doesn't.

### Three deal structures worth thinking through

1. **Partnership / co-sell.** They route small-college leads to us; we route big-municipality leads to them. Lowest commitment, fastest start, lowest leverage.
2. **OEM / white-label.** Bird Dog becomes "WiseSight Campus Mobile" under their brand. Bigger reach, less control, smaller margin per deal, faster scale.
3. **API integration / data bridge.** Bird Dog feeds violations and Iota sensor data into WiseSight's analytics dashboard. Customers can buy either independently; they snap together. Most flexible, biggest technical lift, best long-term option.

### Critical caution
Don't walk into WiseSight from a position of weakness. Their team can spin up iPad LPR in a few sprints if they decide small-college is worth chasing. The asset that protects Bird Dog isn't the code — it's (a) Iota sensor exclusivity, (b) institutional credibility ("built by a CIO for his own campus"), and (c) the AI Dev Center as a sustained development engine. Lock those down *before* the meeting.

### Sequenced first moves (next ~60 days)

1. **Nail down what Iota can actually deliver.** Cost, timeline, willingness to spec custom 800 MHz sensors for this use case, exclusivity terms. This meeting determines whether the WiseSight conversation is "partner" or "competitor."
2. **Heather Hosfeld's IP framework needs to cover three things:** the Bird Dog app, any Iota co-developed sensor IP, and the brand/trademark for the productized offering.
3. **Run one Iota-integrated pilot at Moravian.** Even one lot with occupancy beacons + ePermit transmitters integrated with Bird Dog. That's the "show, don't tell" artifact.
4. **Then approach WiseSight** with a tight one-pager: here's a tier you can't currently serve, here's the joint TAM, here's three deal structures.

---

## 6. Iota 800 MHz Capability Analysis

Sub-GHz 800 MHz gives four things Wi-Fi/BLE can't: real range (hundreds of meters through walls, miles line-of-sight), genuinely long battery life on tiny sensors (5–10 years on a coin cell), penetration through parking decks and dense buildings, and zero dependency on campus Wi-Fi or IT provisioning.

### Vehicle and permit ID (headline capability)

**ePermit transponders.** A windshield decal with a passive or low-power 800 MHz chip broadcasts permit info to the cart's iPad on approach. The lookup pre-loads *before* OCR even fires — the plate scan becomes confirmation rather than lookup. Scan-to-flag latency drops from 1–2 seconds to effectively zero. Officer trust goes up because the decision is multi-factor.

**Anti-spoofing.** A hardware permit can't be Photoshopped the way an OCR-only system can be fooled by a printed paper plate.

**Guest / visitor flow.** Temporary 24-hour transponders for visitors and contractors with auto-expiry.

### Location and lot intelligence

GPS is unreliable in lots — canopies, between buildings, parking decks. Lot-perimeter beacons on sub-GHz tell the cart with certainty which lot and which zone (faculty, visitor, reserved, EV) it's in. Officer never has to manually pick a lot. Bird Dog auto-switches context as the cart moves.

### Space-level occupancy

Per-space magnetometer + 800 MHz sensors detect vehicle presence in real time, enabling:
- Live lot utilization dashboard
- Reserved-space monitoring (handicap, dean, EV chargers, loading)
- Time-in-space tracking — auto-flags vehicles past permit limit, alert pushed to nearest cart
- Heat maps over weeks/months — Cabinet-grade data for parking planning

Essentially WiseSight's Hawk Occupancy at small-campus economics, without fixed cameras.

### Network independence

Sensors backhaul to one or two gateway hubs per lot — no campus Wi-Fi SSIDs, no IT firewall tickets, no Cisco controllers, no port openings. Three real benefits:
- Works in parking decks where Wi-Fi is dead
- Works during campus network outages
- Doesn't expand IT attack surface (matters given the Canvas/Instructure breach context)

### New enforcement and safety workflows

- **Hot-list instant alerts.** Flagged plate enters a lot — all active carts notified with direction-of-travel hint.
- **Geofenced violation alerts.** Sensor sees a car overstay → push to nearest cart.
- **Officer safety beacon.** Cart broadcasts officer location to dispatch — lone-officer overnight rounds safer.
- **Stolen-vehicle BOLO.** Plate hits a sensor → instant alert across the mesh.

### Data and integration layer

Continuous utilization data lets you correlate revenue, violations, and lot usage. Pipe to TeamDynamix, Oracle, or whatever's in use.

### Strategic implications — three reasons this changes the product

1. **It changes Bird Dog from "mobile scanner" to "campus parking platform."** Mobile is the entry product; sensors are the expansion. Different ARR profile, much stickier customer.
2. **It gives a real moat against WiseSight.** They can copy the iPad LPR app in a sprint. They can't replicate an Iota-exclusive 800 MHz mesh without rebuilding their own hardware stack or partnering with someone they don't have.
3. **The same sensor mesh sells into other campus problems.** Lone-worker safety, HVAC occupancy, asset tracking, classroom utilization, EV charger monitoring — Iota gateway is sunk cost once installed.

### Reality check
We don't yet know what Iota will commit to building, on what timeline, at what cost, with what exclusivity. Pre-meeting questions: which capabilities does Iota's existing 800 MHz hardware already deliver, which would they custom-build, which are off the table?

---

## 7. Open Questions / Next Decisions

- **Iota follow-up agenda** — which capabilities are off-the-shelf, which are custom-build, which are out of scope; pricing, timeline, exclusivity terms
- **Heather Hosfeld scope expansion** — Bird Dog (app + Iota co-developed sensor IP + brand/trademark) in her July 15–30 IP framework
- **Proof pack production** — benchmark chart, demo video, IT spec sheet, chief testimonial
- **IACLEA abstract** — draft and submit
- **WiseSight outreach one-pager** — draft after Iota and IP clarity
- **Peer Lehigh Valley CIO intro list** — Lafayette, Lehigh, Muhlenberg, DeSales, Cedar Crest, Northampton CC

---

*Document captured from Cowork conversation. Add to Cowork Artifact Library for ongoing reference.*
