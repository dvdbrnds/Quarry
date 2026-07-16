# Omnilert Replacement: Development Plan

**Project:** Quarry HoundDog — Campus Alert System  
**Date:** July 13, 2026  
**Status:** Planning

---

## 1. Architecture Overview

All new work extends the existing HoundDog alert subsystem under `hounddog/backend/app/`. The codebase follows a consistent pattern: SQLAlchemy model → Pydantic schema → FastAPI router → service layer. Every new feature follows this exact pattern.

### Existing Foundation

| Layer | Location | Key Files |
|-------|----------|-----------|
| Models | `models/alert_log.py`, `models/alert_subscriber.py` | `AlertLog`, `AlertSubscriber` |
| Schemas | `schemas/alerts.py` | `AlertSendRequest`, `AlertLogRead`, etc. |
| Router | `routers/alerts.py` | `admin_router` (Okta-protected), `public_router` |
| Service | `services/alert_dispatcher.py` | `dispatch_alert()`, `clear_alert()`, `init_channels()` |
| Channels | `services/channels/*.py` | 9 channels, `AlertChannel` base class, `REGISTRY` |
| Scheduler | `services/closure_scheduler.py` | `_run_loop()` — asyncio.sleep(60) background loop |
| SMS | `services/sms.py` | `send_sms_async()` via Twilio REST client |

### New Modules Introduced

```
hounddog/backend/app/
├── models/
│   ├── alert_template.py          # Phase 1.1
│   ├── alert_response.py          # Phase 1.2
│   ├── subscriber_group.py        # Phase 1.4
│   └── alert_scenario.py          # Phase 1.5
├── schemas/
│   └── alerts.py                  # Extended (all phases)
├── routers/
│   └── alerts.py                  # Extended (all phases)
├── services/
│   ├── alert_dispatcher.py        # Extended: group filtering (1.4)
│   ├── scenario_runner.py         # Phase 1.5
│   └── twilio_webhook.py          # Phase 1.2 inbound SMS handler
│   └── alert_scheduler.py         # Phase 2.6

hounddog/frontend/src/
├── pages/
│   ├── Alerts.tsx                  # Extended: template picker, response view, groups, scenarios
│   └── AlertAnalytics.tsx          # Phase 2.9
```

### Important: Existing `MessageTemplate` Is Separate

The codebase already has `models/message_template.py` (`MessageTemplate`) used for **lot closure notifications** — it has fields like `reason_code`, `reason_label`, and templates with `{lot_name}` / `{closes_at}` placeholders. The new `AlertTemplate` model is purpose-built for the **campus-wide alert system** with fields matching `AlertSendRequest` (`category`, `subject`, `body_text`, `body_sms`). These are intentionally separate systems.

---

## 2. Database Migrations

All migrations use the existing startup migration pattern in `main.py` (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` inside the `pg_advisory_lock(42)` block). No Alembic version files needed.

### Phase 1.1 — `alert_templates` Table

```sql
CREATE TABLE IF NOT EXISTS alert_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(256) NOT NULL,
    category        VARCHAR(64) NOT NULL,
    subject         VARCHAR(512) NOT NULL,
    body_text       TEXT DEFAULT '',
    body_sms        VARCHAR(320) DEFAULT '',
    created_by      VARCHAR(256) NOT NULL,
    is_default      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

### Phase 1.2 — `alert_responses` Table + `alert_log` Columns

```sql
CREATE TABLE IF NOT EXISTS alert_responses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id        UUID NOT NULL REFERENCES alert_log(id) ON DELETE CASCADE,
    subscriber_id   UUID REFERENCES alert_subscribers(id) ON DELETE SET NULL,
    phone           VARCHAR(32),
    channel         VARCHAR(32) DEFAULT 'sms',
    response_text   VARCHAR(320),
    received_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alert_responses_alert ON alert_responses(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_responses_subscriber ON alert_responses(subscriber_id);

ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS response_options JSONB;
ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS is_checkin BOOLEAN DEFAULT false;
```

- `response_options` stores the options array (e.g., `["1=Safe", "2=Need Help"]`) sent with the alert
- `is_checkin` flags Safety Check-In alerts for dashboard filtering (Phase 1.3)

### Phase 1.3 — No New Tables

Safety Check-In reuses the `alert_responses` table and `is_checkin` column from Phase 1.2.

### Phase 1.4 — `subscriber_groups` + Junction Table

```sql
CREATE TABLE IF NOT EXISTS subscriber_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(256) NOT NULL,
    description     TEXT DEFAULT '',
    group_type      VARCHAR(64) DEFAULT 'custom',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subscriber_group_members (
    subscriber_id   UUID NOT NULL REFERENCES alert_subscribers(id) ON DELETE CASCADE,
    group_id        UUID NOT NULL REFERENCES subscriber_groups(id) ON DELETE CASCADE,
    PRIMARY KEY (subscriber_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_sgm_subscriber ON subscriber_group_members(subscriber_id);
CREATE INDEX IF NOT EXISTS idx_sgm_group ON subscriber_group_members(group_id);

ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS target_group_ids JSONB;
```

- `group_type` enum values: `building`, `department`, `role`, `custom`
- `target_group_ids` on `alert_log` records which groups were targeted (audit trail)

### Phase 1.5 — `alert_scenarios` Table

```sql
CREATE TABLE IF NOT EXISTS alert_scenarios (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(256) NOT NULL,
    description     TEXT DEFAULT '',
    steps           JSONB NOT NULL DEFAULT '[]',
    created_by      VARCHAR(256),
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

Steps JSON structure:

```json
[
  {
    "action": "send_alert",
    "template_id": "uuid",
    "group_ids": ["uuid"],
    "channels": ["sms", "email", "signage"],
    "delay_seconds": 0
  },
  {
    "action": "wait",
    "delay_seconds": 300
  },
  {
    "action": "send_alert",
    "template_id": "uuid-followup",
    "channels": ["sms", "email"]
  },
  {
    "action": "clear_previous"
  }
]
```

### Phase 2.6 — `alert_log` Columns for Scheduling

```sql
ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;
ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS recurrence_rule VARCHAR(256);
```

---

## 3. API Endpoints

All admin endpoints are under `admin_router` (requires Okta SSO, `admin` or `staff` role). All paths are relative to `/api/alerts`.

### Phase 1.1 — Alert Templates

| Method | Path | Request Body | Response | Notes |
|--------|------|-------------|----------|-------|
| `GET` | `/templates` | — | `list[AlertTemplateRead]` | List all templates. Optional `?category=` filter |
| `GET` | `/templates/{id}` | — | `AlertTemplateRead` | Single template |
| `POST` | `/templates` | `AlertTemplateCreate` | `AlertTemplateRead` (201) | Create template |
| `PUT` | `/templates/{id}` | `AlertTemplateUpdate` | `AlertTemplateRead` | Update template |
| `DELETE` | `/templates/{id}` | — | 204 | Delete template |

**New Schemas:**

```python
class AlertTemplateCreate(BaseModel):
    name: str
    category: str
    subject: str
    body_text: str = ""
    body_sms: str = ""
    is_default: bool = False

class AlertTemplateUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    subject: str | None = None
    body_text: str | None = None
    body_sms: str | None = None
    is_default: bool | None = None

class AlertTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    category: str
    subject: str
    body_text: str
    body_sms: str
    created_by: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
```

**Seed Data** (in `main.py` lifespan, same pattern as violation type seeding):

| Name | Category | Subject | SMS Body |
|------|----------|---------|----------|
| Active Shooter | emergency | ACTIVE SHOOTER — Seek shelter immediately | ACTIVE SHOOTER on campus. Run, Hide, Fight. Shelter in place. |
| Tornado Warning | emergency | TORNADO WARNING — Take shelter now | TORNADO WARNING for campus. Take shelter in lowest interior room NOW. |
| Campus Lockdown | emergency | CAMPUS LOCKDOWN — Shelter in place | LOCKDOWN: Campus is locked down. Shelter in place. Do not exit buildings. |
| Weather Closure | campus_closing | Campus Closed — Severe Weather | Campus closed due to severe weather. All classes cancelled. Stay home. |
| Power Outage | general | Power Outage Advisory | Power outage reported on campus. Updates to follow. |
| IT Outage | general | IT Systems Outage | IT systems are currently down. Updates to follow. |
| All-Clear | emergency | ALL CLEAR — Resume normal activity | ALL CLEAR: The emergency has ended. Resume normal activity. |

### Phase 1.2 — Two-Way SMS

| Method | Path | Request Body | Response | Auth | Notes |
|--------|------|-------------|----------|------|-------|
| `POST` | `/webhooks/twilio/inbound` | Twilio form data | TwiML 200 | None (Twilio signature validation) | Inbound SMS webhook |
| `GET` | `/{alert_id}/responses` | — | `AlertResponseSummary` | Admin | Aggregated response data |
| `GET` | `/{alert_id}/responses/detail` | — | `list[AlertResponseRead]` | Admin | Individual responses |
| `GET` | `/{alert_id}/non-responders` | — | `list[SubscriberRead]` | Admin | Subscribers who haven't replied |

**Webhook Registration:** The Twilio inbound webhook URL (`https://parking.moravian.edu/api/alerts/webhooks/twilio/inbound`) must be configured in the Twilio console for the `TWILIO_FROM_NUMBER` phone number.

**Extend `AlertSendRequest`:**

```python
class AlertSendRequest(BaseModel):
    category: str
    subject: str
    body_text: str = ""
    body_sms: str = ""
    send_email: bool = True
    send_sms: bool = True
    response_options: list[str] | None = None  # NEW: e.g., ["1=Safe", "2=Need Help"]
    group_ids: list[uuid.UUID] | None = None   # NEW: Phase 1.4
    is_checkin: bool = False                    # NEW: Phase 1.3
```

When `response_options` is set, the SMS channel appends to the message body:
```
Reply: 1=Safe, 2=Need Help
```

**New Schemas:**

```python
class AlertResponseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    alert_id: uuid.UUID
    subscriber_id: uuid.UUID | None
    phone: str | None
    channel: str
    response_text: str
    received_at: datetime

class AlertResponseSummary(BaseModel):
    alert_id: uuid.UUID
    total_sent: int
    total_responses: int
    response_counts: dict[str, int]   # {"Safe": 42, "Need Help": 3}
    non_responder_count: int
    first_response_at: datetime | None
    last_response_at: datetime | None
```

**Twilio Webhook Handler** (`services/twilio_webhook.py`):

- Validate Twilio request signature using `twilio.request_validator`
- Parse `From` phone number, look up `AlertSubscriber` by normalized phone
- Find the most recent active alert with `response_options` set
- Create `AlertResponse` row
- Return empty TwiML response (no auto-reply)

**New Config Setting:**

```python
# config.py
twilio_webhook_auth_token: str = ""  # Can reuse twilio_auth_token for validation
```

### Phase 1.3 — Safety Check-In

No new endpoints beyond Phase 1.2. The check-in behavior is triggered by:

1. Setting `is_checkin: true` on `AlertSendRequest`
2. When `is_checkin` is true, `response_options` defaults to `["SAFE", "HELP"]` if not explicitly set
3. SMS body auto-appends: `"Reply SAFE if you are OK. Reply HELP if you need assistance."`

**Admin Dashboard Additions** (extend `AlertResponseSummary` or add a dedicated widget endpoint):

| Method | Path | Response | Notes |
|--------|------|----------|-------|
| `GET` | `/{alert_id}/checkin-status` | `CheckInStatus` | Real-time check-in dashboard data |
| `POST` | `/{alert_id}/resend-non-responders` | `AlertSendResult` | Re-send to non-responders |

```python
class CheckInStatus(BaseModel):
    alert_id: uuid.UUID
    total_subscribers: int
    responded_safe: int
    responded_help: int
    no_response: int
    help_details: list[AlertResponseRead]
    response_timeline: list[TimelinePoint]

class TimelinePoint(BaseModel):
    timestamp: datetime
    cumulative_responses: int
    cumulative_safe: int
    cumulative_help: int
```

### Phase 1.4 — Groups / Segmentation

| Method | Path | Request Body | Response | Notes |
|--------|------|-------------|----------|-------|
| `GET` | `/groups` | — | `list[SubscriberGroupRead]` | List all groups with member counts |
| `GET` | `/groups/{id}` | — | `SubscriberGroupRead` | Single group with members |
| `POST` | `/groups` | `SubscriberGroupCreate` | `SubscriberGroupRead` (201) | Create group |
| `PUT` | `/groups/{id}` | `SubscriberGroupUpdate` | `SubscriberGroupRead` | Update group |
| `DELETE` | `/groups/{id}` | — | 204 | Delete group (removes junction rows) |
| `POST` | `/groups/{id}/members` | `GroupMembersBatch` | `{"added": int}` | Bulk-add subscribers to group |
| `DELETE` | `/groups/{id}/members` | `GroupMembersBatch` | `{"removed": int}` | Bulk-remove from group |

**Dispatcher Change:** Modify `_get_subscribers()` in `alert_dispatcher.py`:

```python
async def _get_subscribers(
    alert: AlertLog,
    db: AsyncSession,
    group_ids: list[uuid.UUID] | None = None,
) -> list:
    # If group_ids provided, filter by group membership
    # Emergency alerts still go to all, but can be scoped to groups
    ...
```

**New Schemas:**

```python
class SubscriberGroupCreate(BaseModel):
    name: str
    description: str = ""
    group_type: str = "custom"

class SubscriberGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    group_type: str | None = None

class SubscriberGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    group_type: str
    member_count: int
    created_at: datetime
    updated_at: datetime

class GroupMembersBatch(BaseModel):
    subscriber_ids: list[uuid.UUID]
```

**Seed Groups** (Moravian buildings):

Monocacy Hall, Comenius Hall, HUB, Zinzendorf Hall, Colonial Hall, PPHAC, Sally, Haupert Union Building, Steel Field, Breidegam Athletics, Main Street (offices), 1742 (off-campus)

### Phase 1.5 — Pre-Saved Scenarios

| Method | Path | Request Body | Response | Notes |
|--------|------|-------------|----------|-------|
| `GET` | `/scenarios` | — | `list[AlertScenarioRead]` | List all scenarios |
| `GET` | `/scenarios/{id}` | — | `AlertScenarioRead` | Single scenario |
| `POST` | `/scenarios` | `AlertScenarioCreate` | `AlertScenarioRead` (201) | Create scenario |
| `PUT` | `/scenarios/{id}` | `AlertScenarioUpdate` | `AlertScenarioRead` | Update scenario |
| `DELETE` | `/scenarios/{id}` | — | 204 | Delete scenario |
| `POST` | `/scenarios/{id}/run` | — | `{"task_id": str}` | Execute scenario (background) |
| `GET` | `/scenarios/running` | — | `list[RunningScenario]` | Active scenario runs |
| `POST` | `/scenarios/running/{task_id}/abort` | — | 200 | Cancel a running scenario |

**Scenario Runner** (`services/scenario_runner.py`):

- Maintains a dict of `{task_id: asyncio.Task}` for running scenarios
- Each step executes sequentially with `asyncio.sleep()` for delays
- `send_alert` steps call `dispatch_alert()` directly
- `clear_previous` steps call `clear_alert()` on the last sent alert
- Task ID is a UUID returned to the frontend for tracking

**New Schemas:**

```python
class ScenarioStep(BaseModel):
    action: str  # "send_alert" | "wait" | "clear_previous"
    template_id: uuid.UUID | None = None
    group_ids: list[uuid.UUID] | None = None
    channels: list[str] | None = None
    delay_seconds: int = 0

class AlertScenarioCreate(BaseModel):
    name: str
    description: str = ""
    steps: list[ScenarioStep]

class AlertScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[ScenarioStep] | None = None

class AlertScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    steps: list[dict]
    created_by: str | None
    created_at: datetime
    updated_at: datetime

class RunningScenario(BaseModel):
    task_id: str
    scenario_id: uuid.UUID
    scenario_name: str
    current_step: int
    total_steps: int
    started_at: datetime
    started_by: str
```

**Default Scenarios:**

1. **Active Shooter** — Immediate lockdown alert → 5 min wait → Follow-up with updates → Manual all-clear
2. **Tornado Warning** — Immediate tornado alert → 15 min wait → Status check-in (is_checkin=true)

---

## 4. Frontend Pages & Components

### Existing Page: `Alerts.tsx` — Modifications

The current `Alerts.tsx` has 6 tabs: Send Alert, History, Subscribers, Channels, Test, Signage. The following modifications and new tabs are needed:

#### Phase 1.1 — Template Picker on Send Tab

**Modify `SendSection` component:**
- Add a `Select` dropdown above the category selector: "Load Template..."
- Populates `subject`, `bodyText`, `bodySms`, and `category` from the selected `AlertTemplate`
- Add a "Save as Template" button after the SMS body field (opens a modal for template name)

**New Tab: "Templates"**
- Table of all templates with columns: Name, Category, Subject (truncated), Default, Actions (Edit/Delete)
- Inline create/edit form (same pattern as `SubscriberForm`)
- "Set as Default" toggle per-category (one default per category)

#### Phase 1.2/1.3 — Response Collection + Check-In

**Modify `SendSection` component:**
- Add a `Checkbox` for "Request SMS responses"
- When checked, show an editable tag list for response options (default: `["1=Safe", "2=Need Help"]`)
- Add a `Checkbox` for "Safety Check-In" which auto-sets response options to SAFE/HELP

**Modify `HistorySection` component:**
- Add a "Responses" column showing response count (clickable)
- In expanded row, show response summary: bar chart of response distribution
- Non-responder count with "Re-send" button
- Check-in alerts get a distinct visual treatment (blue badge "Check-In")

**New Tab: "Responses"** (or integrated into History detail)
- Real-time response dashboard when an active alert has response_options
- Three-number summary: Responded Safe / Responded Help / No Response
- Individual response table with timestamps
- Simple line chart: cumulative responses over time (use a `<canvas>` or simple CSS bar chart — no new charting library needed for Phase 1)

#### Phase 1.4 — Groups

**New Tab: "Groups"**
- Group management table: Name, Type (building/department/role/custom), Member Count, Actions
- Create/Edit group form
- Member management: multi-select subscriber picker (existing subscriber list with search)
- Drag-and-drop or checkbox bulk-assign

**Modify `SendSection` component:**
- Add a `Select` (mode="multiple") for "Target Groups" below category
- Preview updates to show filtered recipient count when groups are selected
- Emergency alert still shows warning that all subscribers will be contacted

#### Phase 1.5 — Scenarios

**New Tab: "Scenarios"**
- Scenario list: Name, Description, Steps count, Actions (Edit/Run/Delete)
- Scenario builder: ordered list of steps with add/remove/reorder
  - Step types: Send Alert (template picker + group picker + channel picker), Wait (duration input), Clear Previous
  - Each step is a collapsible card
- "Run Scenario" button with confirmation modal
- Active scenarios panel: shows running scenarios with current step indicator, abort button

### New Interfaces in `api.ts`

```typescript
export interface AlertTemplate {
  id: string;
  name: string;
  category: string;
  subject: string;
  body_text: string;
  body_sms: string;
  created_by: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertResponse {
  id: string;
  alert_id: string;
  subscriber_id: string | null;
  phone: string | null;
  channel: string;
  response_text: string;
  received_at: string;
}

export interface AlertResponseSummary {
  alert_id: string;
  total_sent: int;
  total_responses: int;
  response_counts: Record<string, number>;
  non_responder_count: number;
  first_response_at: string | null;
  last_response_at: string | null;
}

export interface SubscriberGroup {
  id: string;
  name: string;
  description: string;
  group_type: string;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface AlertScenario {
  id: string;
  name: string;
  description: string;
  steps: ScenarioStep[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScenarioStep {
  action: "send_alert" | "wait" | "clear_previous";
  template_id?: string;
  group_ids?: string[];
  channels?: string[];
  delay_seconds?: number;
}
```

### New API Methods

```typescript
// api.ts — add to the alerts namespace
templates: {
  list: (category?: string) => request<AlertTemplate[]>(`/alerts/templates${...}`),
  get: (id: string) => request<AlertTemplate>(`/alerts/templates/${id}`),
  create: (data: Partial<AlertTemplate>) => request<AlertTemplate>("/alerts/templates", { method: "POST", ... }),
  update: (id: string, data: Partial<AlertTemplate>) => request<AlertTemplate>(`/alerts/templates/${id}`, { method: "PUT", ... }),
  delete: (id: string) => request<void>(`/alerts/templates/${id}`, { method: "DELETE" }),
},
responses: {
  summary: (alertId: string) => request<AlertResponseSummary>(`/alerts/${alertId}/responses`),
  detail: (alertId: string) => request<AlertResponse[]>(`/alerts/${alertId}/responses/detail`),
  nonResponders: (alertId: string) => request<AlertSubscriber[]>(`/alerts/${alertId}/non-responders`),
  resend: (alertId: string) => request<AlertSendResult>(`/alerts/${alertId}/resend-non-responders`, { method: "POST" }),
},
groups: {
  list: () => request<SubscriberGroup[]>("/alerts/groups"),
  get: (id: string) => request<SubscriberGroup>(`/alerts/groups/${id}`),
  create: (data: ...) => ...,
  update: (id: string, data: ...) => ...,
  delete: (id: string) => ...,
  addMembers: (id: string, subscriberIds: string[]) => ...,
  removeMembers: (id: string, subscriberIds: string[]) => ...,
},
scenarios: {
  list: () => request<AlertScenario[]>("/alerts/scenarios"),
  create: (data: ...) => ...,
  update: (id: string, data: ...) => ...,
  delete: (id: string) => ...,
  run: (id: string) => request<{ task_id: string }>(`/alerts/scenarios/${id}/run`, { method: "POST" }),
  running: () => request<RunningScenario[]>("/alerts/scenarios/running"),
  abort: (taskId: string) => request<void>(`/alerts/scenarios/running/${taskId}/abort`, { method: "POST" }),
},
```

---

## 5. Dependencies

### Backend — New Python Packages

| Package | Version | Phase | Purpose |
|---------|---------|-------|---------|
| None required for Phase 1 | — | — | Twilio SDK already installed. asyncio sleep handles delays. |

Phase 2 additions:

| Package | Version | Phase | Purpose |
|---------|---------|-------|---------|
| `apscheduler` | ~4.0 | 2.6 | Scheduled/recurring alerts (or extend existing asyncio loop) |
| `python-docx` | ~1.1 | 2.9 | After-action report DOCX generation |
| `weasyprint` or `reportlab` | latest | 2.9 | PDF export for Clery compliance reports |

### Frontend — New npm Packages

| Package | Version | Phase | Purpose |
|---------|---------|-------|---------|
| None required for Phase 1 | — | — | Ant Design covers all needed UI components |

Phase 2 additions:

| Package | Version | Phase | Purpose |
|---------|---------|-------|---------|
| `recharts` or `@ant-design/charts` | latest | 2.9 | Analytics dashboard charts |

---

## 6. Phase 1 Timeline Estimates

Estimates assume a single developer familiar with the Quarry codebase.

| Item | Feature | Backend | Frontend | Total |
|------|---------|---------|----------|-------|
| 1.1 | Message Templates | 1 day | 1.5 days | **2.5 days** |
| 1.2 | Two-Way SMS (Response Collection) | 2.5 days | 2 days | **4.5 days** |
| 1.3 | Safety Check-In | 1 day | 1.5 days | **2.5 days** |
| 1.4 | Group / Building Segmentation | 2 days | 2 days | **4 days** |
| 1.5 | Pre-Saved Scenarios | 2 days | 2.5 days | **4.5 days** |
| — | Integration testing & hardening | — | — | **2 days** |
| — | **Phase 1 Total** | | | **~20 days** |

### Recommended Build Order

1. **Templates (1.1)** — Zero external dependencies, unlocks scenario builder
2. **Two-Way SMS (1.2)** — Highest compliance impact, requires Twilio console config
3. **Safety Check-In (1.3)** — Built directly on 1.2, incremental work
4. **Groups (1.4)** — Independent of 1.2/1.3, could be parallelized
5. **Scenarios (1.5)** — Depends on templates (1.1), benefits from groups (1.4)

### Phase 2 Estimates (Higher-Level)

| Item | Feature | Estimate |
|------|---------|----------|
| 2.6 | Scheduled / Recurring Alerts | 3-4 days |
| 2.7 | Desktop Alert Client | 5-7 days (Electron app + MSI packaging) |
| 2.8 | Weather Feed Auto-Triggers | 3-4 days |
| 2.9 | Reporting & Analytics Dashboard | 5-7 days |
| 2.10 | SIS/LDAP Subscriber Sync | 4-5 days (depends on Colleague API access) |

---

## 7. Risks & Open Questions

### Must Resolve Before Phase 1

1. **Twilio Phone Number Configuration**
   - The current `TWILIO_FROM_NUMBER` must support receiving inbound SMS. Verify with Twilio that the number type (local, toll-free, short code) supports two-way messaging.
   - Short codes have higher throughput but cost more and require a separate approval process.
   - **Action:** Check Twilio console for the current number's inbound SMS capability.

2. **Twilio Webhook URL Accessibility**
   - The inbound SMS webhook (`/api/alerts/webhooks/twilio/inbound`) must be publicly reachable from Twilio's servers. Quarry at `parking.moravian.edu` is public, but confirm Coolify/reverse proxy configuration passes POST requests to this path.
   - **Action:** Test with a curl from outside campus network.

3. **Twilio Request Signature Validation**
   - The webhook must validate the `X-Twilio-Signature` header to prevent spoofed inbound messages. The `twilio` Python SDK includes `RequestValidator` — use it.
   - **Action:** None (implementation detail, handled in code).

4. **Emergency Alert Override + Groups**
   - Design decision: When an admin sends an emergency alert targeted to specific groups, should it still override category preferences and go to ALL subscribers (current behavior), or respect the group filter?
   - **Recommendation:** Emergency + groups = send to all members of those groups, bypassing category opt-in. Emergency + no groups = send to all subscribers (current behavior). This preserves the Clery compliance guarantee while enabling targeted emergencies.

5. **Concurrent Scenario Execution**
   - Should multiple scenarios be allowed to run simultaneously? (e.g., tornado scenario running while admin manually sends a separate alert)
   - **Recommendation:** Allow it. Each scenario tracks its own state. The abort mechanism handles cleanup.

### Phase 2 Open Questions

6. **Desktop Client Distribution** — SCCM/GPO packaging requires IT department involvement. Coordinate with Moravian IT for MSI signing and deployment policies.

7. **NWS API Rate Limits** — The NWS API is free but requests should be throttled to ~1 per minute for the Bethlehem, PA zone. Check current NWS terms of service.

8. **Colleague Integration Scope** — The existing Colleague integration (parking system) uses specific API endpoints. The subscriber sync may need different Colleague views for department/building data. Requires coordination with the registrar's office / IT.

9. **Clery Compliance Report Format** — Confirm with Moravian's Clery compliance officer what fields/format the after-action report must include. This determines the PDF/DOCX template design.

### Phase 3 Notes (Bullet Points Only)

- **Push Notifications (2.11):** APNs key already exists in config (`apns_key_path`, etc.). FCM credentials needed. React Native vs Flutter decision. App store review timeline: 2-4 weeks.
- **Conference Bridge (2.12):** Twilio conference rooms are straightforward. Main question: who moderates the bridge? Auto-include in alert body or separate activation?
- **Social Media (2.13):** Twitter/X API costs have increased significantly. Confirm institutional accounts have API access. Facebook Graph API requires app review for page posting.
- **Access Control (2.14):** Vendor TBD. This cannot be scoped until the access control system is identified. Typical integration is HTTPS webhook from Quarry → vendor's lockdown API.

---

## Appendix: Twilio Webhook Data Flow (Phase 1.2)

```
Subscriber SMS reply
        │
        ▼
Twilio receives inbound SMS
        │
        ▼
POST /api/alerts/webhooks/twilio/inbound
  ├── Validate X-Twilio-Signature
  ├── Extract From, Body from form data
  ├── Normalize phone → lookup AlertSubscriber
  ├── Find most recent active alert with response_options
  ├── Create AlertResponse row
  └── Return 200 with empty TwiML
        │
        ▼
Admin polls GET /api/alerts/{id}/responses
  └── Returns aggregated counts + individual responses
```

## Appendix: Scenario Execution Flow (Phase 1.5)

```
Admin clicks "Run Scenario"
        │
        ▼
POST /api/alerts/scenarios/{id}/run
  ├── Load scenario steps
  ├── Create asyncio.Task
  ├── Register in _running_scenarios dict
  └── Return { task_id }
        │
        ▼
Background task executes sequentially:
  Step 1: send_alert → dispatch_alert()
  Step 2: wait 300s → asyncio.sleep(300)
  Step 3: send_alert → dispatch_alert()
  Step 4: clear_previous → clear_alert()
        │
        ▼
Task completes → removed from _running_scenarios
```
