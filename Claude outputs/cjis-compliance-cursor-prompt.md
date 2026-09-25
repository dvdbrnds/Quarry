# CJIS Compliance Implementation for JNET Integration

You are working on **Quarry**, a campus parking management platform for Moravian University. The backend is **FastAPI + SQLAlchemy (async, PostgreSQL)**. The frontend is **React 18 / Vite / TypeScript / Tailwind / Ant Design**. The mobile client is **BirdDog**, a Swift/iOS 17+ app. Deployed via Docker on Coolify at quarry.moravian.edu. Authentication is via **Microsoft Entra ID SSO (Okta JWT for admin endpoints)**.

## Goal

Implement everything needed for FBI CJIS Security Policy v6.1 compliance so Quarry can integrate with Pennsylvania's JNET (Justice Network) for license plate and registered owner lookups. An officer taps a "JNET Lookup" button in BirdDog, Quarry's backend queries JNET web services, and the result is displayed on the device. CJI (Criminal Justice Information) is never persisted -- display only.

This is a compliance-first implementation. Every feature exists to satisfy a specific CJIS policy area. Do not skip or defer any item.

---

## 1. JNET Service Layer (Backend)

Create `backend/app/services/jnet/` with the following modules:

### `backend/app/services/jnet/__init__.py`
- Export the public interface.

### `backend/app/services/jnet/client.py`
- `JNETClient` class that handles communication with JNET web services.
- Configure mutual TLS (mTLS): Quarry authenticates to JNET with a client certificate. Load cert and key paths from config (`JNET_CLIENT_CERT_PATH`, `JNET_CLIENT_KEY_PATH`, `JNET_CA_BUNDLE_PATH`).
- Use `httpx.AsyncClient` with the mTLS config.
- All requests must include the ORI (Originating Agency Identifier) from config (`JNET_ORI`).
- Method: `async def plate_lookup(self, plate_number: str, state: str = "PA") -> JNETPlateResult`
- Method: `async def registered_owner_lookup(self, plate_number: str, state: str = "PA") -> JNETOwnerResult`
- Enforce TLS 1.2+ only (`ssl.SSLContext` with `PROTOCOL_TLS_CLIENT`, `minimum_version = TLSVersion.TLSv1_2`).
- Set request timeout to 15 seconds.
- Raise `JNETError` on failure (timeout, auth failure, invalid response).
- **Never log CJI response data.** Log only: query timestamp, user, plate queried, success/failure, response time.

### `backend/app/services/jnet/models.py`
- Pydantic models for JNET responses: `JNETPlateResult`, `JNETOwnerResult`, `JNETError`.
- These models are for transit only -- they are never written to the database.
- Mark all CJI fields with a `cji: bool = True` field metadata annotation for downstream awareness.

### `backend/app/services/jnet/config.py`
- All JNET-related settings as a Pydantic `BaseSettings` class:
  - `JNET_ENABLED: bool = False` (feature flag -- off by default)
  - `JNET_BASE_URL: str`
  - `JNET_CLIENT_CERT_PATH: str`
  - `JNET_CLIENT_KEY_PATH: str`
  - `JNET_CA_BUNDLE_PATH: str`
  - `JNET_ORI: str` (Moravian's Originating Agency Identifier)
  - `JNET_TIMEOUT_SECONDS: int = 15`
  - `JNET_SESSION_TIMEOUT_MINUTES: int = 30`

---

## 2. CJIS Audit Logging (Backend) — Policy Areas AU-2, AU-3, AU-6, AU-9, AU-11

This is the most critical compliance component. Every JNET query must be audit-logged.

### `backend/app/models/cjis_audit_log.py`
- New SQLAlchemy model: `CJISAuditLog`
- Table: `cjis_audit_logs`
- Columns:
  - `id: UUID` (primary key)
  - `timestamp: DateTime` (UTC, indexed)
  - `user_id: UUID` (FK to users table)
  - `user_email: str` (denormalized for audit immutability)
  - `user_full_name: str` (denormalized)
  - `action: str` (e.g., "plate_lookup", "owner_lookup")
  - `query_plate: str` (the plate number queried)
  - `query_state: str` (state code, e.g., "PA")
  - `ori: str` (Originating Agency Identifier used)
  - `source_ip: str` (officer's device IP)
  - `device_id: str` (BirdDog device identifier, nullable)
  - `success: bool`
  - `error_message: str` (nullable, only on failure -- never contains CJI)
  - `response_time_ms: int`
  - `session_id: UUID` (to correlate with auth session)
  - `created_at: DateTime` (server timestamp)
- **Constraints:**
  - This table is append-only. No UPDATE or DELETE operations allowed at the application level.
  - Add a DB comment: "CJIS Security Policy v6.1 — AU-2/AU-3. Retain minimum 1 year. No CJI response data stored."
- **Do NOT store any CJI response data** (no registered owner name, address, or any JNET response content in this log).

### `backend/app/services/jnet/audit.py`
- `async def log_jnet_query(...)` — creates a `CJISAuditLog` entry for every JNET query, success or failure.
- Called by the JNET client before returning results.
- This function must never raise -- wrap in try/except and log failures to structlog. A failed audit write should NOT prevent the query response from reaching the officer, but should trigger an alert.

### Alembic Migration
- Create migration for the `cjis_audit_logs` table.
- Add a partial index on `timestamp` for efficient date-range queries.
- Add index on `user_id` for per-officer query history.

---

## 3. CJIS Audit Admin Endpoints (Backend) — Policy Areas AU-6, AU-9

### `backend/app/routers/cjis_audit.py`
- All endpoints require `cjis_admin` role (not regular admin, not officer).
- `GET /api/cjis/audit/logs` — paginated, filterable by date range, user, plate. Returns metadata only (no CJI).
- `GET /api/cjis/audit/logs/export` — CSV export for compliance reporting.
- `GET /api/cjis/audit/stats` — dashboard data: queries per day, per officer, per hour-of-day (for anomaly detection).
- `GET /api/cjis/audit/alerts` — list of flagged anomalies (see anomaly detection below).

### Anomaly Detection — Policy Area AU-6(1)
- `backend/app/services/jnet/anomaly.py`
- Run on each query (lightweight) and as a scheduled background task (comprehensive):
  - Flag if an officer queries the same plate more than 3 times in 24 hours.
  - Flag if queries occur outside configured shift hours (configurable: `JNET_SHIFT_START_HOUR`, `JNET_SHIFT_END_HOUR`).
  - Flag if an officer's daily query volume exceeds 2 standard deviations from their 30-day average.
  - Flag if queries come from an IP outside the expected campus network range (`JNET_ALLOWED_IP_RANGES`).
- Store flags in a `cjis_audit_alerts` table: `id`, `audit_log_id` (FK), `alert_type`, `description`, `reviewed_by` (nullable), `reviewed_at` (nullable), `dismissed: bool`.
- Alerts must be reviewed weekly per CJIS policy. Track review status.

---

## 4. JNET Access Control (Backend) — Policy Areas AC-2, AC-5, AC-6

### Role-Based Access
- Add a new role: `jnet_officer` — can perform JNET lookups.
- Add a new role: `cjis_admin` — can view JNET audit logs, manage JNET access, review alerts. Cannot perform lookups.
- These roles are separate from existing Quarry admin/staff roles.
- Add to the user model or roles table:
  - `jnet_authorized: bool = False`
  - `jnet_authorized_by: UUID` (FK, who granted access)
  - `jnet_authorized_at: DateTime`
  - `jnet_background_check_date: DateTime` (nullable — date of fingerprint-based background check)
  - `jnet_training_completed_at: DateTime` (nullable — date of CJIS security awareness training)
- **Access prerequisites (enforce in middleware):**
  - User must have `jnet_officer` role AND
  - `jnet_background_check_date` must be non-null AND
  - `jnet_training_completed_at` must be within the last 365 days
  - If any prerequisite fails, return 403 with a specific message indicating which requirement is missing.

### Admin Endpoints for JNET Access Management
- `GET /api/cjis/users` — list all users with their JNET authorization status, background check date, training date.
- `POST /api/cjis/users/{user_id}/authorize` — grant JNET access. Requires `cjis_admin` role. Records who authorized and when.
- `DELETE /api/cjis/users/{user_id}/authorize` — revoke JNET access.
- `PATCH /api/cjis/users/{user_id}/background-check` — record background check completion date.
- `PATCH /api/cjis/users/{user_id}/training` — record training completion date.
- `GET /api/cjis/users/access-review` — list users due for periodic access review (last review > 90 days ago).

### Automatic Access Revocation — Policy Area AC-2(5)
- Background task: disable JNET access for users who haven't logged in for 90 days.
- Background task: flag users whose training is expiring within 30 days. Auto-revoke when expired.

---

## 5. Session Management (Backend + iOS) — Policy Areas AC-11, AC-12

### Backend: JNET Session Tracking
- When an officer authenticates and their session can access JNET, record `jnet_session_start` in the session/token metadata.
- Middleware: check `jnet_session_start` on every JNET request. If more than 30 minutes since last JNET activity, require re-authentication. Return 401 with `cjis_session_expired` error code.
- Track `jnet_last_activity` — updated on every JNET query. The 30-minute timeout is from last JNET activity, not from login.
- On session expiry or logout, the backend must NOT retain any CJI in memory or cache.

### iOS (BirdDog): Session Timeout
- Track last JNET interaction time locally.
- After 30 minutes of inactivity (no JNET queries), lock the JNET feature. Clear any displayed CJI data from the screen immediately. Show a re-authentication prompt.
- When the app goes to background: immediately clear any CJI displayed on screen (override `sceneDidEnterBackground`). When returning to foreground, check the 30-minute timeout before showing any JNET UI.
- On device lock (screen off): same behavior — clear CJI.

---

## 6. JNET Lookup API Endpoint (Backend)

### `backend/app/routers/jnet.py`
- `POST /api/jnet/plate-lookup`
  - Request body: `{ "plate_number": str, "state": str = "PA" }`
  - Auth: requires valid session + `jnet_officer` role + all CJIS prerequisites met
  - Middleware chain: authenticate → check JNET authorization + prerequisites → check session timeout → rate limit → execute query → audit log → return result
  - Response: the JNET plate/owner data. **Set response header `Cache-Control: no-store, no-cache, must-revalidate`**. Set `Pragma: no-cache`.
  - Response body must include a `cjis_notice` field: "This information is from JNET/CJIS and is for authorized law enforcement use only. Unauthorized access or disclosure is a federal offense."
  - Rate limit: max 10 queries per minute per user (prevent bulk scraping).
  - Input validation: plate number must match regex `^[A-Z0-9]{1,8}$` (after uppercasing and stripping spaces/dashes). Reject anything else.
- `GET /api/jnet/status`
  - Returns whether JNET integration is enabled, connectivity status (last successful query time), and whether the current user is authorized.
  - No CJI in response.

---

## 7. iOS Implementation (BirdDog)

### JNET Lookup UI
- Add a "JNET Lookup" button on the citation/scan screen. Only visible if the officer has `jnet_officer` authorization (check on login and cache the flag).
- Tapping the button:
  1. Check jailbreak status (see below). If jailbroken, show error and refuse.
  2. Check device passcode is set (`LAContext.canEvaluatePolicy`). If not, show error requiring passcode setup.
  3. Prompt for biometric authentication (Face ID / Touch ID) via `LocalAuthentication` framework. This is a per-lookup authentication, separate from app login. If biometric fails, fall back to device passcode.
  4. Check JNET session timeout (30 minutes since last JNET activity). If expired, require full re-authentication (back to SSO login).
  5. Send plate to `POST /api/jnet/plate-lookup`.
  6. Display results in a modal/sheet. Include the CJIS notice text.
  7. Results are in-memory only. Never written to disk, Core Data, UserDefaults, or any local storage.
  8. When the modal is dismissed, the CJI data is released from memory.

### Jailbreak Detection — Policy Area 5.20
- Create `JailbreakDetector.swift`:
  - Check for Cydia/Sileo/Zebra app URLs (`UIApplication.shared.canOpenURL`)
  - Check for writable system paths (`/private/var/lib/apt`, `/Applications/Cydia.app`, `/usr/sbin/sshd`, `/etc/apt`, `/bin/bash`, `/usr/bin/ssh`)
  - Check if the app can write outside its sandbox (`/private/jailbreak_test`)
  - Check if the app binary has been tampered with (dylib injection detection)
  - Return `Bool` — if any check fails, JNET features are disabled.
- Call this check:
  - On app launch (disable JNET UI entirely if jailbroken)
  - Before every JNET lookup request
  - On return from background

### CJI Data Handling in Memory
- JNET response data must be stored in a dedicated `CJIDataStore` class (not mixed with regular app state).
- `CJIDataStore` clears all data:
  - When the JNET results modal is dismissed
  - When the app enters background
  - When the screen locks
  - When the 30-minute session timeout fires
  - On logout
- Override `applicationWillResignActive` / `sceneWillResignActive` to clear CJI and show a privacy screen (blur or blank overlay) so CJI doesn't appear in the app switcher screenshot.

### Device Passcode Requirement
- On app launch, check `LAContext().canEvaluatePolicy(.deviceOwnerAuthentication)`.
- If no passcode is set, show a blocking screen: "Device passcode required for enforcement features. Please set a passcode in Settings."
- This is a prerequisite for JNET features only -- basic app functionality (scanning, citations without JNET) can still work without a passcode.

---

## 8. Frontend: CJIS Administration (React)

### New Pages

#### `/admin/cjis/dashboard`
- JNET system status (enabled/disabled, last successful query, connectivity health)
- Summary stats: queries today, this week, this month
- Active alerts requiring review (count + link)
- Users with expiring training (within 30 days)

#### `/admin/cjis/audit-log`
- Paginated table of JNET audit log entries
- Filters: date range, officer, plate number, success/failure
- Columns: timestamp, officer name, plate queried, state, success, response time
- CSV export button
- **No CJI data displayed** — this shows query metadata only

#### `/admin/cjis/alerts`
- Table of anomaly alerts
- Columns: date, officer, alert type, description, status (pending/reviewed/dismissed)
- Action buttons: "Mark Reviewed", "Dismiss" (requires reason)
- Filter by alert type, status, date range
- Weekly review completion tracker: "Last full review: [date]. [X] alerts pending review."

#### `/admin/cjis/users`
- Table of all users with JNET-related fields
- Columns: name, email, JNET authorized (yes/no), background check date, training date, training status (current/expiring/expired), last JNET query date
- Actions: Authorize, Revoke, Record Background Check, Record Training
- Highlight users with expired training or due for access review
- "Access Review" tab: users whose access hasn't been reviewed in 90+ days

### Access Control
- All `/admin/cjis/*` pages require `cjis_admin` role.
- Regular admins and officers cannot see these pages.
- Add "CJIS Administration" to the admin sidebar, visible only to `cjis_admin` users.

---

## 9. Incident Response Scaffolding — Policy Area IR-4, IR-6

### `backend/app/services/jnet/incident.py`
- `async def report_cjis_incident(incident_type: str, description: str, affected_records: int, detected_by: str)` — creates an incident record and sends notifications.
- New model: `CJISIncident` — `id`, `timestamp`, `incident_type` (unauthorized_access, data_breach, system_compromise, policy_violation), `description`, `affected_records_count`, `detected_by`, `reported_to_iso_at` (nullable), `resolved_at` (nullable), `resolution_notes`.
- Auto-triggered when:
  - A JNET query is attempted by an unauthorized user (blocked, but logged as incident)
  - Jailbreak detected on a device that previously had JNET access
  - Anomaly detection flags a critical pattern (e.g., queries from outside campus network)
- Sends notification to `CJIS_INCIDENT_EMAIL` (configured in env) — this is the person responsible for reporting to the PA State Police CJIS ISO.

---

## 10. Configuration & Environment Variables

Add to `backend/app/config.py` (or a new CJIS-specific settings class):

```python
# JNET Integration
JNET_ENABLED: bool = False
JNET_BASE_URL: str = ""
JNET_CLIENT_CERT_PATH: str = ""
JNET_CLIENT_KEY_PATH: str = ""
JNET_CA_BUNDLE_PATH: str = ""
JNET_ORI: str = ""
JNET_TIMEOUT_SECONDS: int = 15

# CJIS Session
JNET_SESSION_TIMEOUT_MINUTES: int = 30

# CJIS Anomaly Detection
JNET_SHIFT_START_HOUR: int = 6   # 6 AM
JNET_SHIFT_END_HOUR: int = 23   # 11 PM
JNET_ALLOWED_IP_RANGES: str = ""  # comma-separated CIDRs
JNET_MAX_SAME_PLATE_QUERIES_24H: int = 3
JNET_MAX_QUERIES_PER_MINUTE: int = 10

# CJIS Incident Response
CJIS_INCIDENT_EMAIL: str = ""

# CJIS Access
JNET_INACTIVE_REVOKE_DAYS: int = 90
JNET_TRAINING_VALIDITY_DAYS: int = 365
```

---

## 11. Database Migration Summary

New tables:
1. `cjis_audit_logs` — every JNET query (append-only)
2. `cjis_audit_alerts` — anomaly detection flags
3. `cjis_incidents` — incident response tracking

Altered tables:
1. Users table — add `jnet_authorized`, `jnet_authorized_by`, `jnet_authorized_at`, `jnet_background_check_date`, `jnet_training_completed_at`, `jnet_last_activity` columns

---

## 12. Testing

Write tests for:
1. **JNET client** — mock JNET responses, verify mTLS config, verify timeout handling, verify no CJI in logs.
2. **Audit logging** — verify every query creates a log entry, verify no CJI in log entries, verify append-only (no update/delete).
3. **Access control** — verify unauthorized users get 403, verify expired training gets 403, verify missing background check gets 403.
4. **Session timeout** — verify 30-minute timeout enforced, verify re-auth required after timeout.
5. **Anomaly detection** — verify same-plate threshold, verify off-hours detection, verify volume anomaly detection.
6. **Rate limiting** — verify 10 queries/minute limit.
7. **Input validation** — verify plate number regex, verify SQL injection protection, verify XSS protection on display.

---

## Key Principles

1. **CJI is radioactive.** It is displayed to the officer and immediately discarded. Never persisted to disk, database, cache, logs, or error tracking (Sentry). Treat it like a credit card number.
2. **Audit everything.** Every query, every access attempt, every failure. The audit log is the proof of compliance.
3. **Fail closed.** If any CJIS check fails (auth, session, jailbreak, background check, training), deny the JNET lookup. Never fail open.
4. **The JNET feature is a walled garden.** It has its own roles, its own session timeout, its own audit log, its own admin pages. It doesn't leak into the rest of Quarry.

---

## File Structure Summary

```
backend/app/
├── models/
│   ├── cjis_audit_log.py          # NEW
│   ├── cjis_audit_alert.py        # NEW
│   └── cjis_incident.py           # NEW
├── routers/
│   ├── jnet.py                    # NEW — plate lookup endpoint
│   └── cjis_audit.py              # NEW — audit admin endpoints
├── services/
│   └── jnet/
│       ├── __init__.py            # NEW
│       ├── client.py              # NEW — JNET web service client
│       ├── models.py              # NEW — Pydantic response models
│       ├── config.py              # NEW — JNET settings
│       ├── audit.py               # NEW — audit logging
│       ├── anomaly.py             # NEW — anomaly detection
│       ├── incident.py            # NEW — incident response
│       └── middleware.py          # NEW — CJIS auth/session middleware
├── config.py                      # MODIFIED — add JNET env vars

frontend/src/pages/
├── cjis/
│   ├── CJISDashboard.tsx          # NEW
│   ├── CJISAuditLog.tsx           # NEW
│   ├── CJISAlerts.tsx             # NEW
│   └── CJISUsers.tsx              # NEW

ios/BirdDog/
├── JNET/
│   ├── JNETLookupView.swift       # NEW — lookup UI
│   ├── JNETService.swift          # NEW — API client
│   ├── CJIDataStore.swift         # NEW — ephemeral CJI storage
│   ├── JailbreakDetector.swift    # NEW — jailbreak detection
│   └── CJISSessionManager.swift  # NEW — 30-min timeout tracking
```

## Execution Order

1. Database models + migration (tables must exist first)
2. Config + settings
3. JNET client + service layer (mock JNET endpoint for now since we don't have credentials yet)
4. Audit logging
5. Access control (roles, prerequisites, middleware)
6. Session management
7. API endpoint (`/api/jnet/plate-lookup`)
8. Anomaly detection
9. Incident response
10. Frontend admin pages
11. iOS implementation (jailbreak detection, CJI handling, lookup UI)
12. Tests
