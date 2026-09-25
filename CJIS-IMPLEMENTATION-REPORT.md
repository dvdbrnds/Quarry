# CJIS Compliance for JNET Integration — Implementation Report

**FBI CJIS Security Policy v6.1 · Quarry / BirdDog · Sep 25, 2026**

---

## Summary

| Metric | Value |
|---|---|
| Lines added | ~5,147 |
| Files changed | 39 |
| CJIS policy areas covered | 14 |
| New DB tables | 4 |
| Test suites | 7 |
| Platforms | Backend (FastAPI), Frontend (React), iOS (Swift) |

---

## How It Works

An officer taps "JNET Lookup" in BirdDog, authenticates via Face ID, and Quarry's backend queries Pennsylvania's JNET web services over mutual TLS. The result is displayed on the device and immediately discarded — CJI never touches disk, database, cache, logs, or Sentry.

### Key Principles

- **CJI is radioactive** — Display-only. Never persisted to disk, DB, cache, logs, or error tracking. `Cache-Control: no-store`. iOS clears memory on every state transition.
- **Fail closed** — If any CJIS check fails (auth, session, jailbreak, background check, training), the lookup is denied. Never fails open.
- **Audit everything** — Every query, every access attempt, every failure. Append-only — no UPDATE or DELETE at the application level.
- **Walled garden** — JNET has its own roles, session timeout, audit log, and admin pages. Does not leak into the rest of Quarry. Feature flag off by default.

---

## Architecture

### iOS (BirdDog) — 7 files

| File | Lines | Purpose |
|---|---|---|
| `JNET/JailbreakDetector.swift` | 114 | Cydia/Sileo/path/sandbox/dylib injection checks |
| `JNET/CJIDataStore.swift` | 66 | Ephemeral in-memory CJI — auto-clears on background/lock |
| `JNET/CJISSessionManager.swift` | 90 | 30-min inactivity timeout, clears CJI on expiry |
| `JNET/JNETService.swift` | 201 | API client for plate lookup + status |
| `JNET/JNETLookupView.swift` | 195 | Biometric auth per-lookup, CJIS notice display |
| `BirdDogApp.swift` (modified) | 56 | scenePhase observer + privacy screen overlay |
| `OfficerAuthService.swift` (modified) | 15 | isJNETAuthorized flag, CJI clear on logout |

### Backend (FastAPI) — 15 files

| File | Lines | Purpose |
|---|---|---|
| `models/jnet_authorized_user.py` | 62 | JNET authorization tracking (standalone, no FK to users) |
| `models/cjis_audit_log.py` | 54 | Append-only audit log — no CJI columns |
| `models/cjis_audit_alert.py` | 42 | Anomaly detection alerts with review tracking |
| `models/cjis_incident.py` | 44 | IR-4/IR-6 incident response records |
| `alembic/versions/0020_cjis_jnet_tables.py` | 111 | Migration: 4 tables, indexes, FK constraints |
| `services/jnet/config.py` | 42 | Pydantic BaseSettings — all JNET/CJIS env vars |
| `services/jnet/client.py` | 333 | mTLS httpx client, TLS 1.2+, mock mode, no CJI logging |
| `services/jnet/models.py` | 67 | Pydantic response models with `cji=True` field metadata |
| `services/jnet/audit.py` | 88 | `log_jnet_query()` — never raises, fail-safe |
| `services/jnet/middleware.py` | 209 | Access control, session timeout, rate limiter |
| `services/jnet/anomaly.py` | 222 | Per-query + background anomaly detection |
| `services/jnet/incident.py` | 100 | Auto-triggered incident reports + email notification |
| `routers/jnet.py` | 181 | `POST /api/jnet/plate-lookup`, `GET /api/jnet/status` |
| `routers/cjis_audit.py` | 569 | Full CJIS admin CRUD — logs, alerts, users, incidents |
| `main.py` (modified) | 77 | Router registration + hourly background tasks |

### Frontend (React) — 5 files

| File | Lines | Purpose |
|---|---|---|
| `CJISDashboard.tsx` | 159 | System status, query stats, hourly distribution |
| `CJISAuditLog.tsx` | 179 | Paginated/filterable audit log + CSV export |
| `CJISAlerts.tsx` | 245 | Anomaly alerts — review/dismiss workflow |
| `CJISUsers.tsx` | 371 | User management — authorize/revoke/BG check/training |
| `App.tsx` (modified) | 24 | Routes + CJIS nav item gated by role check |

### Tests — 7 files

| File | Lines | Purpose |
|---|---|---|
| `test_jnet_client.py` | 80 | Mock mode, mTLS config, no CJI in logs |
| `test_cjis_audit.py` | 112 | Log creation, never-raise, no CJI columns |
| `test_cjis_access_control.py` | 135 | 403 for all prerequisite failures |
| `test_cjis_session.py` | 86 | 30-min timeout, `cjis_session_expired` detail |
| `test_cjis_anomaly.py` | 83 | IP range checks, fail-safe behavior |
| `test_jnet_rate_limit.py` | 51 | 10/min per-user sliding window |
| `test_jnet_input_validation.py` | 70 | Plate regex, SQL injection, XSS rejection |

---

## Database Schema

| Table | Purpose | Constraints |
|---|---|---|
| `jnet_authorized_users` | JNET access authorization by Okta sub | Unique okta_sub + email, standalone (no FK to users) |
| `cjis_audit_logs` | Every JNET query — metadata only | Append-only, indexed on timestamp + user_id, no CJI columns |
| `cjis_audit_alerts` | Anomaly detection flags | FK to audit_logs, review tracking (reviewed_by, reviewed_at) |
| `cjis_incidents` | Security incident records | Indexed on timestamp + type, resolution tracking |

---

## API Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/jnet/plate-lookup` | jnet_officer + all prerequisites | Plate + owner lookup via JNET |
| GET | `/api/jnet/status` | Any authenticated user | Feature flag, connectivity, user auth status |
| GET | `/api/cjis/audit/logs` | cjis_admin | Paginated audit log (no CJI) |
| GET | `/api/cjis/audit/logs/export` | cjis_admin | CSV export for compliance |
| GET | `/api/cjis/audit/stats` | cjis_admin | Dashboard aggregates |
| GET | `/api/cjis/audit/alerts` | cjis_admin | Anomaly alerts |
| POST | `/api/cjis/audit/alerts/{id}/review` | cjis_admin | Mark alert reviewed/dismissed |
| GET | `/api/cjis/users` | cjis_admin | All JNET-authorized users |
| POST | `/api/cjis/users/create` | cjis_admin | Create JNET user record |
| POST | `/api/cjis/users/{id}/authorize` | cjis_admin | Grant JNET access |
| POST | `/api/cjis/users/{id}/revoke` | cjis_admin | Revoke JNET access |
| PUT | `/api/cjis/users/{id}/background-check` | cjis_admin | Record BG check date |
| PUT | `/api/cjis/users/{id}/training` | cjis_admin | Record training date |
| GET | `/api/cjis/users/access-review` | cjis_admin | Users due for 90-day review |
| GET | `/api/cjis/incidents` | cjis_admin | Security incident history |

---

## CJIS Security Policy v6.1 Coverage

| Policy Area | Title | Implementation |
|---|---|---|
| AC-2 | Account Management | `jnet_authorized_users` table, authorize/revoke endpoints, 90-day inactive auto-revoke |
| AC-5 | Separation of Duties | `jnet_officer` (lookups) vs `cjis_admin` (audit/manage) — separate roles, no overlap |
| AC-6 | Least Privilege | Background check + training prerequisites enforced per-request in middleware |
| AC-11 | Session Lock | 30-min inactivity timeout, backend + iOS enforcement, CJI cleared on expiry |
| AC-12 | Session Termination | Auto-terminate on timeout, background transition, logout |
| AU-2 | Auditable Events | Every JNET query logged — success and failure |
| AU-3 | Audit Content | Who, what, when, where, outcome — no CJI response data |
| AU-6 | Audit Review | Admin dashboard, weekly review tracking, CSV export |
| AU-6(1) | Automated Review | Same-plate threshold, off-hours, IP range, volume anomaly detection |
| AU-9 | Audit Protection | Append-only table — no UPDATE/DELETE at application level |
| AU-11 | Audit Retention | Table comment: retain minimum 1 year |
| IR-4 | Incident Handling | `CJISIncident` model, auto-triggered on unauthorized access/jailbreak/IP anomaly |
| IR-6 | Incident Reporting | Email notification to `CJIS_INCIDENT_EMAIL` (LASO) |
| 5.20 | Mobile Device Mgmt | Jailbreak detection, device passcode requirement, biometric per-lookup |

---

## What You Need To Do Next

> Your PD already has JNET access, ORI, background checks, and training. The main task is registering Quarry as a new JNET application and getting a client certificate issued for the server.

### You can do right now

| # | Action | Effort |
|---|---|---|
| 4 | Deploy current code with `JNET_ENABLED=true`, empty `JNET_BASE_URL` (mock mode) | 15 min |
| 5 | Bootstrap first `cjis_admin` user via SQL INSERT (see below) | 5 min |
| 6 | Officers test full flow with mock data — biometrics, timeouts, audit trail | 1 session |
| 8 | Smoke test with real JNET endpoint once certs arrive | 1 hour |
| 9 | Record officer background check + training dates in CJIS admin UI | Per officer |

### Blocking on external parties

| # | Action | Effort |
|---|---|---|
| 1 | Get ORI + JNET endpoint URL from PD chief or TAC | Ask |
| 2 | Register Quarry as a new JNET application through the TAC | 1–2 weeks (state process) |
| 3 | Receive mTLS client certificate for Quarry's server | Comes with step 2 |
| 7 | Install certs on server, set all JNET env vars, flip to live | 30 min |

### Bootstrap first cjis_admin

```sql
INSERT INTO jnet_authorized_users (
  id, okta_sub, email, full_name, role,
  jnet_authorized, jnet_authorized_by_email,
  jnet_authorized_at, created_at, updated_at
) VALUES (
  gen_random_uuid(),
  'REPLACE_WITH_OKTA_SUB',
  'admin@moravian.edu',
  'CJIS Administrator Name',
  'cjis_admin',
  true,
  'system-bootstrap',
  now(), now(), now()
);
```

### Production environment variables

```env
JNET_ENABLED=true
JNET_BASE_URL=https://ws.jnet.pa.gov/...
JNET_CLIENT_CERT_PATH=/certs/quarry-jnet.pem
JNET_CLIENT_KEY_PATH=/certs/quarry-jnet.key
JNET_CA_BUNDLE_PATH=/certs/jnet-ca-bundle.pem
JNET_ORI=PA0390100
CJIS_INCIDENT_EMAIL=laso@moravian.edu
JNET_ALLOWED_IP_RANGES=10.0.0.0/8
```
