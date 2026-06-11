# Hound Dog: Architecture Document

*Technical architecture for the Quarry management dashboard, ticketing system, and payment gateway.*
*Draft, June 11, 2026*

---

## System overview

Hound Dog is a server-side web application with a responsive frontend. It serves three roles: permit source of truth (with OTA sync to Bird Dog), ticket/payment lifecycle manager, and enforcement dashboard. It also ingests occupancy data from SheepDog gateways.

```
                         ┌──────────────────────────────┐
                         │         Hound Dog             │
                         │                               │
  Bird Dog iPad ◄──────► │  API Server                   │ ◄──── SheepDog Gateway
  (permit sync,          │    ├─ /api/permits            │       (occupancy POSTs)
   ticket upload)        │    ├─ /api/tickets            │
                         │    ├─ /api/occupancy          │
                         │    ├─ /api/sync               │
                         │    └─ /api/payments/webhook    │ ◄──── Stripe
                         │                               │
                         │  Web Frontend                 │ ◄──── Officers (mobile)
                         │    ├─ Dashboard               │ ◄──── Supervisor (desktop)
                         │    ├─ Permit management       │ ◄──── Finance (desktop)
                         │    └─ Reports                 │
                         │                               │
                         │  Student Payment Portal       │ ◄──── Students (mobile/desktop)
                         │    └─ /pay                    │
                         │                               │
                         │  Database (PostgreSQL)         │
                         └──────────────────────────────┘
```

## Tech stack

### Backend

**Python (FastAPI).** Reasons: you already have Python running on the Pi gateway, FastAPI is fast to build, async-native (handles webhook callbacks and real-time updates well), and has excellent OpenAPI documentation generation. One language across the gateway and the server reduces context switching for a solo developer.

**PostgreSQL.** Relational data (permits, tickets, payments) with strong consistency. Supports JSON columns for flexible metadata without needing a document store. Runs fine on a single VM.

**SQLAlchemy + Alembic.** ORM and migrations. Keeps the schema versioned and deployable.

### Frontend

**React + TypeScript.** Component-based, responsive. The dashboard has enough interactive state (live updates, filtering, drill-downs) that a SPA makes sense over server-rendered pages.

**Tailwind CSS.** Utility-first, responsive out of the box. Handles the desktop-vs-mobile layout switching without maintaining two codebases.

**Recharts or Chart.js.** For dashboard visualizations (ticket pipeline, lot utilization, revenue charts).

### Student payment portal

Minimal standalone page (could be a separate React route or a simple server-rendered page). Doesn't need the full dashboard framework. Student enters plate or ticket number, sees the fine, pays via Stripe Checkout (hosted payment page, so we never touch card numbers and PCI scope stays minimal).

### Deployment

**On-prem Coolify VM.** FastAPI server, PostgreSQL, and the React frontend (built and served as static files by the API server or nginx). No microservices, no Kubernetes. One developer, one box. Coolify handles container orchestration, SSL, and deploys from the git repo.

For development: Docker Compose with two containers (app + postgres). For production: same stack deployed via Coolify.

## API design

RESTful JSON API. All endpoints require authentication except the student payment portal lookup and Stripe webhooks.

### Permit endpoints

```
GET    /api/permits                    List/search permits (paginated, filterable)
POST   /api/permits                    Create permit
PUT    /api/permits/{id}               Update permit
DELETE /api/permits/{id}               Deactivate permit (soft delete)
POST   /api/permits/import             Bulk import from CSV
GET    /api/permits/export             Export to CSV
```

### Sync endpoints (Bird Dog ↔ Hound Dog)

```
GET    /api/sync/permits?since={ts}    Incremental permit sync (Bird Dog polls this)
POST   /api/sync/tickets               Bird Dog uploads new tickets
GET    /api/sync/status                 Health check + last sync timestamp
```

**Sync protocol:**

1. Bird Dog stores a `lastSyncTimestamp` locally.
2. On app launch and periodically (every 60 seconds when on WiFi), Bird Dog calls `GET /api/sync/permits?since={lastSyncTimestamp}`.
3. Response includes all permits created/updated/deleted since that timestamp, plus the new server timestamp.
4. Bird Dog applies the delta to its local SwiftData store.
5. First sync (no timestamp): full permit dump.
6. If offline, Bird Dog uses cached data. Tickets created offline are queued and uploaded on reconnect.

**Authentication for Bird Dog:** API key per device, issued when the iPad is registered in Hound Dog. Sent as `Authorization: Bearer {key}` header. Simple, no OAuth needed for device-to-server.

### Ticket endpoints

```
GET    /api/tickets                     List/search tickets (filterable by status, lot, date, officer)
GET    /api/tickets/{id}                Ticket detail
POST   /api/tickets                     Create ticket (from dashboard, manual entry)
PUT    /api/tickets/{id}                Update ticket (status change, appeal decision)
PUT    /api/tickets/{id}/void           Void a ticket
PUT    /api/tickets/{id}/appeal         Submit or decide appeal
GET    /api/tickets/pipeline            Aggregate counts by status (for dashboard)
```

### Occupancy endpoints

```
POST   /api/occupancy                   SheepDog gateway posts state changes here
GET    /api/occupancy/status            Current occupancy by lot/space
GET    /api/occupancy/history           Historical utilization data
```

This replaces the direct gateway-to-iPad POST from the SheepDog POC. In production, the gateway posts to Hound Dog, which stores the data and makes it available to both the dashboard and Bird Dog.

### Payment endpoints

```
POST   /api/payments/webhook            Stripe webhook (payment confirmation)
GET    /api/payments/{ticketId}         Payment status for a ticket
GET    /api/payments/reconciliation     Finance reconciliation report
POST   /api/payments/bursar-import      Batch import bursar payment confirmations
```

### Student portal

```
GET    /pay?plate={plate}               Look up tickets by plate number
GET    /pay?ticket={ticketId}           Look up specific ticket
POST   /pay/checkout                    Create Stripe Checkout session
GET    /pay/success                     Payment success redirect
```

## Data model

### Core tables

```sql
permits
  id              UUID PRIMARY KEY
  student_id      VARCHAR          -- Jenzabar ID
  name            VARCHAR
  plates          VARCHAR[]        -- array of plate numbers
  lot_assignment  VARCHAR
  permit_type     VARCHAR          -- faculty, student, visitor, reserved, temporary, service
  beacon_id       VARCHAR NULL     -- SheepDog hangtag Major/Minor
  start_date      DATE
  end_date        DATE
  status          VARCHAR          -- active, expired, suspended, revoked
  created_at      TIMESTAMP
  updated_at      TIMESTAMP        -- used for incremental sync
  deleted_at      TIMESTAMP NULL   -- soft delete

tickets
  id              UUID PRIMARY KEY
  plate           VARCHAR
  permit_id       UUID NULL REFERENCES permits
  lot             VARCHAR
  zone            VARCHAR NULL
  violation_type  VARCHAR
  fine_amount     DECIMAL(8,2)
  photo_url       VARCHAR NULL
  officer_id      VARCHAR
  issued_at       TIMESTAMP
  status          VARCHAR          -- issued, pending_payment, paid, appealed, escalated, voided
  appeal_note     TEXT NULL
  appeal_decision VARCHAR NULL     -- pending, approved, denied
  appeal_decided_by VARCHAR NULL
  created_at      TIMESTAMP
  updated_at      TIMESTAMP

payments
  id              UUID PRIMARY KEY
  ticket_id       UUID REFERENCES tickets
  amount          DECIMAL(8,2)
  method          VARCHAR          -- online_card, bursar, cash, waived
  stripe_payment_id VARCHAR NULL
  bursar_reference  VARCHAR NULL
  paid_at         TIMESTAMP
  created_at      TIMESTAMP

occupancy_events
  id              UUID PRIMARY KEY
  sensor_id       VARCHAR
  lot             VARCHAR
  space           VARCHAR NULL
  state           VARCHAR          -- occupied, vacant
  rssi            INTEGER
  recorded_at     TIMESTAMP

occupancy_current
  sensor_id       VARCHAR PRIMARY KEY
  lot             VARCHAR
  space           VARCHAR NULL
  state           VARCHAR
  last_updated    TIMESTAMP

devices
  id              UUID PRIMARY KEY
  name            VARCHAR          -- e.g. "Cart 1 iPad"
  api_key         VARCHAR UNIQUE
  device_type     VARCHAR          -- ipad, gateway
  last_seen       TIMESTAMP
  created_at      TIMESTAMP
```

### Indexes

```sql
CREATE INDEX idx_permits_plates ON permits USING GIN (plates);
CREATE INDEX idx_permits_updated ON permits (updated_at);
CREATE INDEX idx_permits_status ON permits (status);
CREATE INDEX idx_tickets_plate ON tickets (plate);
CREATE INDEX idx_tickets_status ON tickets (status);
CREATE INDEX idx_tickets_issued ON tickets (issued_at);
CREATE INDEX idx_occupancy_events_lot ON occupancy_events (lot, recorded_at);
```

## Bird Dog sync architecture

This is the most operationally critical piece. It replaces the current local JSON permit file with a live sync.

### Current state (Bird Dog today)

```
Bird Dog iPad
  └─ SwiftData
       └─ permits.json (loaded manually via admin UI)
```

### Target state (with Hound Dog)

```
Hound Dog Server
  └─ PostgreSQL (permits table)
       │
       ▼ GET /api/sync/permits?since=...
       │
Bird Dog iPad
  └─ SwiftData
       └─ PermitRecord (synced from Hound Dog, cached locally)
       └─ PendingTicket (queued for upload when offline)
```

### Swift changes in Bird Dog

New service: `HoundDogSyncService`

```swift
// Replaces the manual JSON import in DataProvider
class HoundDogSyncService {
    let baseURL: URL          // Hound Dog server
    let apiKey: String        // Device API key
    var lastSyncTimestamp: Date?  // Persisted in UserDefaults

    // Called on app launch and every 60s on WiFi
    func syncPermits() async throws {
        let delta = try await fetchPermitDelta(since: lastSyncTimestamp)
        try applyDelta(delta)  // Insert/update/delete in SwiftData
        lastSyncTimestamp = delta.serverTimestamp
    }

    // Called when Bird Dog creates a ticket in the field
    func uploadTicket(_ ticket: ScannedPlate) async throws {
        // POST to /api/sync/tickets
        // If offline, queue in PendingTicketStore
    }
}
```

`PlateAuthService` continues to read from SwiftData. It doesn't know or care where the data came from. The sync is transparent.

## Payment flow

### Online (Stripe)

```
Student visits /pay?plate=ABC1234
  → Hound Dog looks up unpaid tickets for that plate
  → Student selects ticket(s) to pay
  → POST /pay/checkout creates a Stripe Checkout Session
  → Student redirected to Stripe's hosted payment page
  → Student pays
  → Stripe sends webhook to POST /api/payments/webhook
  → Hound Dog creates payment record, updates ticket status to "paid"
  → Student redirected to /pay/success with receipt
```

PCI compliance: Hound Dog never sees card numbers. Stripe Checkout handles the payment form. Hound Dog only receives the confirmation webhook.

### Bursar

```
Business office exports payment batch from Jenzabar (CSV)
  → Finance uploads to POST /api/payments/bursar-import
  → Hound Dog matches payments to tickets by student ID or ticket ID
  → Matched tickets updated to "paid" with method "bursar"
  → Unmatched payments flagged for manual review
```

Or, if Jenzabar has an API (TBD): automated nightly sync instead of manual CSV upload.

## Dashboard views

### Officer view (mobile-optimized)

- **My recent tickets.** Last 10 tickets I issued, with status.
- **Ticket lookup.** Search by plate, ticket ID, or student name.
- **Lot status.** Quick occupancy counts from SheepDog (if available).
- **Permit check.** Look up a plate to see permit status (backup for Bird Dog).

### Supervisor view (desktop)

- **Ticket pipeline.** Funnel chart: issued → pending → paid/appealed/escalated/voided. Clickable to drill down.
- **Today's activity.** Tickets issued, payments received, active officers, lots patrolled.
- **Appeals queue.** Pending appeals for review and decision.
- **Officer performance.** Plates scanned, tickets issued, scan sessions (from Bird Dog session history data).
- **Occupancy.** Lot utilization from SheepDog, current and historical.

### Finance view (desktop)

- **Payment reconciliation.** Payments received by source (online vs. bursar), matched vs. unmatched.
- **Revenue summary.** By period, by lot, by violation type.
- **Outstanding fines.** Aging report: 0-30, 30-60, 60-90, 90+ days.
- **Export.** CSV/Excel for Oracle/Jenzabar import.

## Authentication and authorization

**Auth method:** Okta SSO (SAML/OIDC). Moravian already runs Okta. For licensing to other institutions, support generic SAML/OIDC so their IdP plugs in. Fallback: local accounts with password + TOTP for institutions without SSO.

**Roles:**

| Role | Permits | Tickets | Payments | Reports | Dashboard | Users |
|---|---|---|---|---|---|---|
| officer | read | create, read own | — | own stats | officer view | — |
| supervisor | read/write | read/write all, decide appeals | read | all | supervisor view | manage officers |
| finance | read | read | read/write, reconcile | all | finance view | — |
| admin | full | full | full | full | all | full |

**Bird Dog devices** authenticate with API keys (not user accounts). Keys are scoped to permit-read and ticket-write only.

## Real-time updates

**WebSocket or SSE** from the server to connected dashboard clients. When a ticket is created in the field, the dashboard updates immediately without polling. When an occupancy state changes, the lot status view refreshes.

Implementation: FastAPI WebSocket endpoint. Dashboard subscribes on load. Server broadcasts events:

```json
{"event": "ticket_created", "data": {"ticketId": "...", "plate": "...", "lot": "..."}}
{"event": "payment_received", "data": {"ticketId": "...", "amount": 50.00}}
{"event": "occupancy_change", "data": {"sensorId": "occ-001", "lot": "South", "state": "occupied"}}
```

## Repo structure addition

Hound Dog lives in the Quarry monorepo:

```
quarry/
  BirdDog.xcodeproj         ← iOS app
  BirdDog/                  ← Swift source (gains HoundDogSyncService)
  BirdDogTests/
  firmware/                 ← SheepDog hardware
    occupancy-sensor/
    gateway/
  hounddog/                 ← NEW: Hound Dog web app
    backend/
      app/
        main.py             ← FastAPI app
        models.py           ← SQLAlchemy models
        routers/
          permits.py
          tickets.py
          payments.py
          occupancy.py
          sync.py
        services/
          stripe_service.py
          bursar_service.py
          sync_service.py
      alembic/              ← database migrations
      requirements.txt
      Dockerfile
    frontend/
      src/
        components/
        pages/
          Dashboard.tsx
          Permits.tsx
          Tickets.tsx
          Payments.tsx
          Occupancy.tsx
        App.tsx
      package.json
      tailwind.config.js
    student-portal/         ← minimal payment page
      src/
      package.json
    docker-compose.yml      ← app + postgres for dev
  docs/
  brand/
  scripts/
```

## Migration path from current state

**Phase 1 (permit sync):** Build the permit API and sync endpoints. Add `HoundDogSyncService` to Bird Dog. Deploy Hound Dog on a Moravian VM. Import current permits from the spreadsheet. Bird Dog switches from local JSON to synced data. This is the smallest useful deployment.

**Phase 2 (ticketing):** Add ticket creation from Bird Dog, ticket lifecycle endpoints, supervisor dashboard views. Officers start seeing ticket status in the field.

**Phase 3 (payments):** Integrate Stripe, build the student payment portal, add bursar import. Finance gets reconciliation views.

**Phase 4 (occupancy + full dashboard):** Redirect SheepDog gateway to POST to Hound Dog instead of directly to the iPad. Build occupancy views and historical reporting.

## Scaling notes (for licensing to other institutions)

Each institution runs their own Hound Dog instance. No multi-tenant SaaS. This keeps data isolated (privacy story) and deployment simple (single VM per school). The Docker Compose setup makes this straightforward to replicate.

Configuration per institution: database connection, Stripe API keys, branding (logo, colors), SSO settings, fine schedule, lot definitions. All in environment variables or a config file, not in code.

## Open technical questions

- **Payment processor:** TBD. Stripe is the simplest integration but finance may require a specific higher-ed gateway. Resolve before Phase 3.
- **SheepDog data flow evolution:** POC: gateway → iPad (direct). Next: gateway → iPad → syncs to Hound Dog. Production (800 MHz): sensors → base station → Hound Dog directly. Each stage the device stays the first receiver, Hound Dog gets the data for dashboards and history.
