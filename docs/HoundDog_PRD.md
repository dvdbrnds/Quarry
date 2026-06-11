# Hound Dog: Product Requirements Document

*Quarry Management Dashboard + Ticketing + Payment Gateway*
*Draft, June 11, 2026*

---

## What Hound Dog is

The third working dog in the Quarry system. Bird Dog finds violators by camera. SheepDog watches the lot by sensor. Hound Dog tracks the trail: permit database, ticket lifecycle, payment collection, and enforcement reporting.

Hound Dog is a responsive web application that serves as the central management layer for the Quarry platform. It is the source of truth for permits, tickets, and payments, and it syncs permit data over the air to Bird Dog iPads in the field.

## Users

Two primary user groups with different needs:

**Parking officers and supervisor.** Field enforcement and day-to-day operations. Issue tickets (via Bird Dog, surfaced in Hound Dog), monitor ticket status, look up vehicles and permits, check occupancy (from SheepDog sensors), view enforcement activity in real time. Officers need mobile access from their phones while on foot or in the cart.

**Finance / business office.** Payment reconciliation and reporting. Monitor incoming payments, reconcile against the bursar system, run revenue reports, handle appeals and adjustments, export data for Oracle/Jenzabar. Desktop-first workflow.

## Core capabilities

### 1. Permit database (source of truth)

Hound Dog owns the permit database. Bird Dog consumes it.

- Create, edit, deactivate, and bulk-import permits.
- Permit record: student/employee ID, name, plate number(s), lot assignment, permit type (faculty, student, visitor, reserved, temporary), start/end dates, beacon ID (when SheepDog hangtag is assigned).
- Hound Dog IS the permit database. No import from another system. Permits are created and managed here.
- Over-the-air sync to Bird Dog iPads. When permits change in Hound Dog, the update pushes to connected Bird Dog devices so officers always have current data without manual database loads.

### 2. Ticket lifecycle

A ticket is created in the field (by Bird Dog or manually by an officer) and tracked through resolution.

- **Issued.** Officer flags a violation. Bird Dog captures: plate, photo, lot, timestamp, violation type, officer ID. Ticket syncs to Hound Dog immediately (or on next connectivity).
- **Pending payment.** Student notified (email, student portal link). Payment window opens.
- **Paid.** Payment received via online portal or bursar. Ticket closed.
- **Appealed.** Student submits appeal. Supervisor reviews in Hound Dog, approves or denies.
- **Escalated.** Unpaid past deadline. Forwarded to bursar for student account hold or collection action.
- **Voided.** Officer or supervisor cancels (wrong vehicle, duplicate, etc.).

Dashboard shows ticket pipeline: how many at each stage, aging, total outstanding.

### 3. Payment gateway

Two payment channels feeding one ledger:

**Online payment portal (new).** A student-facing page where violators pay tickets directly. Student looks up their ticket by plate number or ticket ID, sees the violation details and amount, pays by credit/debit card. Payment processor: Stripe or institution-approved gateway (check with finance which processors Moravian already has contracts with). Receipt emailed automatically.

**Bursar integration.** For students who pay through the bursar's office or have the fine applied to their student account. Hound Dog receives payment confirmation from the bursar system (batch file, API, or manual entry depending on what Jenzabar supports). This is the existing path that most fines currently travel.

Both channels update the same ticket record. The dashboard shows payment source so finance can reconcile.

### 4. Enforcement dashboard

Real-time and historical views for supervisors and officers.

**Live view:**
- Active Bird Dog sessions (which officers are scanning, where).
- Recent tickets issued (last hour, today).
- SheepDog occupancy status by lot (occupied/vacant counts, utilization percentage).
- Beacon-detected vehicles currently in lot (hangtag permits).

**Historical / reporting:**
- Tickets by day/week/month, by lot, by violation type, by officer.
- Revenue: collected, outstanding, written off.
- Lot utilization over time (from SheepDog data). Heat maps by hour/day.
- Enforcement efficiency: plates scanned per hour, violation rate, false positive rate (from Bird Dog session history).
- Export to CSV/Excel for Oracle/Jenzabar or Cabinet reporting.

### 5. Over-the-air sync to Bird Dog

This is what makes Hound Dog operationally critical. Today Bird Dog loads permits from a local JSON file. Hound Dog replaces that with a live sync:

- Bird Dog polls or subscribes to a Hound Dog API endpoint.
- On permit change (add, edit, deactivate), the update is available to Bird Dog within seconds.
- Bird Dog caches permits locally (SwiftData) so it works offline. Syncs delta on reconnect.
- Sync payload: full permit list on first connect, incremental changes (created/updated/deleted since last sync timestamp) thereafter.
- Same endpoint serves ticket upload: Bird Dog pushes new tickets to Hound Dog as they're created in the field.

## Device experience

**Desktop (finance, supervisor).** Full dashboard layout. Tables, charts, pipeline views, bulk operations, reporting. Primary workflow for finance reconciliation and supervisor oversight.

**Mobile (officers in the field).** Responsive layout optimized for phone screens. Officers need quick access to: ticket status lookup, recent tickets, lot occupancy status, permit lookup. Not the full reporting suite. Think of it as the field reference card, not the command center.

**Bird Dog iPad.** Not a Hound Dog client directly. Bird Dog talks to the Hound Dog API for permit sync and ticket upload, but officers use Bird Dog's native UI for scanning. Hound Dog is what they check between shifts or when they need the bigger picture.

## Integration points

| System | Direction | What flows |
|---|---|---|
| Bird Dog (iPad) | Hound Dog → Bird Dog | Permit database sync |
| Bird Dog (iPad) | Bird Dog → Hound Dog | New tickets, scan session data |
| SheepDog (gateway) | SheepDog → Hound Dog | Occupancy state changes |
| Bursar | Bidirectional | Payment confirmations, account hold requests |
| Payment gateway (TBD) | External → Hound Dog | Online payment confirmations |
| Email/notification service | Hound Dog → Student | Ticket notification, payment receipt |

## Permit data model

| Field | Type | Notes |
|---|---|---|
| permitId | UUID | Primary key |
| studentId | String | Jenzabar student/employee ID |
| name | String | Display name |
| plates | [String] | One or more plate numbers (some students have multiple vehicles) |
| lotAssignment | String | Which lot(s) the permit covers |
| permitType | Enum | faculty, student, visitor, reserved, temporary, service |
| beaconId | String? | SheepDog hangtag beacon UUID/Major/Minor (null if no beacon assigned) |
| startDate | Date | Permit valid from |
| endDate | Date | Permit expires |
| status | Enum | active, expired, suspended, revoked |
| createdAt | Date | |
| updatedAt | Date | Used for incremental sync |

## Ticket data model

| Field | Type | Notes |
|---|---|---|
| ticketId | UUID | Primary key |
| plate | String | License plate (from Bird Dog OCR or manual entry) |
| permitId | UUID? | Linked permit if one exists |
| lot | String | Where the violation occurred |
| zone | String? | Specific zone if applicable |
| violationType | Enum | no_permit, expired_permit, wrong_lot, overtime, fire_lane, handicap, other |
| fineAmount | Decimal | |
| photo | URL? | Violation photo from Bird Dog camera |
| officerId | String | Who issued it |
| issuedAt | Date | |
| status | Enum | issued, pending_payment, paid, appealed, escalated, voided |
| paymentMethod | Enum? | online_card, bursar, cash, waived |
| paidAt | Date? | |
| appealNote | String? | Student's appeal text |
| appealDecision | Enum? | pending, approved, denied |
| appealDecidedBy | String? | Supervisor who ruled |

## Non-functional requirements

**Performance.** Permit sync to Bird Dog must complete within 5 seconds on lot WiFi. Dashboard loads within 2 seconds on desktop.

**Offline resilience.** Bird Dog must function fully when Hound Dog is unreachable (cached permits, queued tickets). Tickets created offline sync when connectivity returns. No data loss.

**Security.** Authentication required for all users (role-based: officer, supervisor, finance, admin). HTTPS only. No student PII exposed without authentication. Payment data never touches Hound Dog servers directly (Stripe handles PCI compliance). Session timeout for idle users.

**Privacy.** Plate photos and student records stay on institutional infrastructure. No third-party cloud storage for enforcement data. Consistent with Bird Dog's on-device privacy posture, extended to the server layer.

**Deployment.** On-prem Coolify VM at Moravian. For licensing to other institutions, each runs their own instance (Docker, deployed via Coolify or similar). Not a SaaS product. Consistent with the higher-ed licensing model and the privacy story.

## What Hound Dog replaces

**OmniGo.** Moravian currently uses OmniGo for parking enforcement records. Hound Dog replaces it: permits, tickets, payments, and reporting all move into Quarry's own system. This eliminates a vendor dependency and integrates enforcement data directly with Bird Dog and SheepDog.

## What Hound Dog is NOT

- Not a replacement for student information systems (Jenzabar/Oracle). It doesn't manage student records.
- Not a public-facing app. The student payment portal is the only student-facing surface, and it's minimal: look up ticket, pay, done.
- Not a standalone product. Hound Dog without Bird Dog is just a ticket tracker. The value is the integration: field enforcement (Bird Dog) + sensor monitoring (SheepDog) + management (Hound Dog) as one system.

## Phased delivery

**Phase 1: Permit management + Bird Dog sync.** Get the source-of-truth database live, build the API, implement OTA sync to Bird Dog. This unblocks everything else and immediately improves field operations (no more manual JSON loads).

**Phase 2: Ticketing + dashboard.** Ticket lifecycle, enforcement dashboard, supervisor views. Officers can see the pipeline.

**Phase 3: Payment gateway.** Online payment portal (Stripe), bursar integration, payment reconciliation for finance. Revenue starts flowing through the system.

**Phase 4: SheepDog integration.** Occupancy data from the gateway feeds into the dashboard. Lot utilization views, heat maps, the full picture.

## Open questions

- Payment processor: TBD. Resolve before Phase 3.
- Do we need to support appeals through the portal (student submits online), or are appeals handled in-person at the parking office?
- Fine schedule: flat rate per violation type, or variable? Who sets the amounts?
- Notification: email only, or also SMS?
- OmniGo migration: Moravian currently uses OmniGo for parking enforcement records. What data needs to migrate to Hound Dog, and does OmniGo have an export path?
