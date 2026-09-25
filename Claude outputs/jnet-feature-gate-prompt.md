# JNET Feature Gate — Per-User Visibility & Stealth Mode

You are working on **Quarry**, a campus parking management platform for Moravian University. The backend is **FastAPI + SQLAlchemy (async, PostgreSQL)**. The frontend is **React 18 / Vite / TypeScript / Tailwind / Ant Design**. The mobile client is **BirdDog**, a Swift/iOS 17+ app. Deployed via Docker on Coolify at quarry.moravian.edu. Authentication is via **Microsoft Entra ID SSO (Okta JWT for admin endpoints)**.

You recently implemented a full CJIS v6.1 compliance layer for JNET integration. This prompt adds two things that are missing: a per-user feature gate so JNET is invisible to everyone except authorized users, and a settings page for system-wide JNET configuration.

## Philosophy

JNET features are in **stealth mode** during development. If a user is not in the `jnet_authorized_users` table, there must be zero evidence that JNET integration exists. No nav items, no menu entries, no 403 responses, no error messages mentioning JNET. The feature is invisible, not locked.

---

## 1. Backend — Stealth 404 Behavior

### Modify `backend/app/routers/jnet.py`

The existing JNET endpoints (`POST /api/jnet/plate-lookup`, `GET /api/jnet/status`) currently return 403 for unauthorized users. Change this:

- If `JNET_ENABLED` is `false` in settings, ALL JNET endpoints return **404 Not Found** with the generic message `{"detail": "Not found"}`. Same 404 as any nonexistent route. No mention of JNET, CJIS, or authorization.
- If `JNET_ENABLED` is `true` but the requesting user is NOT in `jnet_authorized_users` with `jnet_authorized = true`, return **404 Not Found**. Same generic message.
- Only if `JNET_ENABLED` is `true` AND the user IS authorized do the endpoints behave normally. At that point, the existing CJIS middleware (background check, training, session timeout) kicks in and those CAN return 403 with specific error details, because the user is already known to be JNET-authorized.

### Modify `backend/app/routers/cjis_audit.py`

Same pattern for all `/api/cjis/*` admin endpoints:

- If user does not have `cjis_admin` role in `jnet_authorized_users`, return 404 (not 403).
- The CJIS admin section is invisible to non-CJIS users.

### Create a reusable dependency for this

Create `backend/app/services/jnet/dependencies.py`:

```python
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

async def require_jnet_visible(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Gate that makes JNET endpoints invisible to unauthorized users.
    Returns 404 (not 403) so the feature's existence is not disclosed.
    """
    settings = get_jnet_settings()
    if not settings.JNET_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    
    user = get_current_user(request)
    authorized = await get_jnet_authorized_user(db, user.okta_sub)
    if not authorized or not authorized.jnet_authorized:
        raise HTTPException(status_code=404, detail="Not found")
    
    return authorized

async def require_cjis_admin(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Gate for CJIS admin endpoints. Same stealth behavior.
    """
    settings = get_jnet_settings()
    if not settings.JNET_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    
    user = get_current_user(request)
    authorized = await get_jnet_authorized_user(db, user.okta_sub)
    if not authorized or authorized.role != "cjis_admin":
        raise HTTPException(status_code=404, detail="Not found")
    
    return authorized
```

Apply `require_jnet_visible` as a dependency on ALL endpoints in `routers/jnet.py`. Apply `require_cjis_admin` on ALL endpoints in `routers/cjis_audit.py`. Remove any existing auth checks that return 403 for the "is this user JNET-authorized at all" question — that check now returns 404 via the dependency. The downstream CJIS middleware (background check expired, training expired, session timeout) still returns 403 because at that point the user is known to be JNET-authorized and those are actionable errors they need to see.

---

## 2. Backend — JNET Settings Endpoint

### Create `backend/app/routers/jnet_settings.py`

A settings endpoint that lets a `cjis_admin` toggle the JNET system on/off and view configuration status. This is separate from the env var `JNET_ENABLED` — think of it as a two-key system: the env var must be `true` AND the database setting must be enabled.

```
GET  /api/settings/jnet          — requires cjis_admin (stealth 404 otherwise)
PUT  /api/settings/jnet          — requires cjis_admin (stealth 404 otherwise)
```

**GET response:**
```json
{
  "jnet_enabled": true,
  "mock_mode": true,
  "jnet_base_url_configured": false,
  "client_cert_configured": false,
  "ori_configured": false,
  "authorized_user_count": 1,
  "status": "mock_mode"
}
```

Status values: `disabled`, `mock_mode`, `misconfigured` (enabled but missing certs/URL/ORI), `ready` (everything configured), `live` (ready + at least one successful real query in audit log).

**PUT body:**
```json
{
  "jnet_enabled": true
}
```

This toggles the database-level feature flag. Only `cjis_admin` can toggle it. Toggling OFF immediately invalidates all active JNET sessions (clear the session cache/store). Log the toggle action to the CJIS audit log with action `jnet_system_toggle`.

### Database

Add a `system_settings` table if one doesn't already exist, or add JNET settings to whatever key-value or settings mechanism Quarry already uses. The setting is:

- `jnet_system_enabled: bool` (default `false`)

The effective JNET state is: `env JNET_ENABLED` AND `db jnet_system_enabled`. Both must be true for any JNET functionality to be available.

---

## 3. Frontend — Conditional Rendering

### Modify the user context / auth hook

Add a `jnet_status` field to whatever user context or auth response the frontend already uses. The backend should include this in the existing user/me endpoint response:

```json
{
  "existing_fields": "...",
  "jnet_status": null
}
```

If the user is NOT JNET-authorized, `jnet_status` is `null`. Not `false`, not `"unauthorized"` — `null`. The frontend treats null as "this field doesn't exist."

If the user IS JNET-authorized, `jnet_status` is an object:
```json
{
  "jnet_status": {
    "role": "jnet_officer",
    "authorized": true,
    "background_check_valid": true,
    "training_valid": true,
    "system_status": "mock_mode"
  }
}
```

For `cjis_admin`:
```json
{
  "jnet_status": {
    "role": "cjis_admin",
    "authorized": true,
    "background_check_valid": true,
    "training_valid": true,
    "system_status": "mock_mode"
  }
}
```

### Modify `App.tsx` — Conditional navigation

The CJIS nav items and routes that Cursor added should ONLY render when `jnet_status` is not null:

```tsx
// Only render if user has JNET access
{user.jnet_status && (
  <>
    {user.jnet_status.role === 'cjis_admin' && (
      <NavItem to="/admin/cjis/dashboard" icon={ShieldCheck} label="CJIS" />
    )}
  </>
)}
```

If `jnet_status` is null, no CJIS menu items, no CJIS routes registered, no CJIS components loaded. The React bundle still includes the code (tree-shaking the routes would add complexity for no real security gain — the backend is the enforcement layer), but nothing renders.

### JNET Settings Page

Create `frontend/src/pages/admin/JNETSettings.tsx`:

- Only accessible to `cjis_admin` users (render nothing if not).
- Shows the system status from `GET /api/settings/jnet`.
- Toggle switch to enable/disable JNET system-wide.
- Status indicators showing: mock mode vs live, cert configured, ORI configured, authorized user count.
- Link to the CJIS Users management page.
- This page is the "control panel" for the entire JNET integration.

Add this page to the admin nav, gated behind `jnet_status.role === 'cjis_admin'`.

---

## 4. iOS (BirdDog) — Conditional UI

### Modify the main tab bar or menu

The JNET Lookup button/tab should only appear if the user's auth response includes `jnet_status` with `authorized: true`.

```swift
// In whatever view builds the officer's main interface
if let jnetStatus = authService.currentUser?.jnetStatus, jnetStatus.authorized {
    // Show JNET Lookup button
    JNETLookupButton()
}
```

If `jnetStatus` is nil, no button, no menu item, no hint that JNET exists. The officer sees the same BirdDog they've always used.

### Add `jnet_status` to the auth response model

Update the Swift model that parses the `/api/users/me` (or equivalent) response to include an optional `jnetStatus` field:

```swift
struct JNETStatus: Codable {
    let role: String
    let authorized: Bool
    let backgroundCheckValid: Bool
    let trainingValid: Bool
    let systemStatus: String
    
    enum CodingKeys: String, CodingKey {
        case role
        case authorized
        case backgroundCheckValid = "background_check_valid"
        case trainingValid = "training_valid"
        case systemStatus = "system_status"
    }
}

// In your existing User model:
let jnetStatus: JNETStatus?  // nil = JNET doesn't exist for this user
```

---

## 5. Testing Checklist

After implementing, verify these scenarios:

1. **Non-JNET user hits `/api/jnet/plate-lookup`** → 404 (not 403)
2. **Non-JNET user hits `/api/cjis/audit/logs`** → 404
3. **Non-JNET user hits `/api/settings/jnet`** → 404
4. **Non-JNET user's `/api/users/me` response** → `jnet_status` is `null`
5. **Frontend as non-JNET user** → no CJIS nav items visible anywhere
6. **iOS as non-JNET user** → no JNET Lookup button
7. **JNET-authorized user (jnet_officer)** → can see lookup button, can query, gets 404 on admin endpoints
8. **CJIS admin** → can see admin dashboard, settings page, can toggle system on/off
9. **System toggle OFF while officer is using JNET** → next request returns 404, session cleared
10. **`JNET_ENABLED=false` in env** → everything returns 404 regardless of database settings or user authorization

---

## Summary

The goal is a two-layer gate:

| Layer | Controls | Who sets it |
|---|---|---|
| Environment variable `JNET_ENABLED` | Master kill switch — must be `true` for anything to work | DevOps (you, in Coolify) |
| Database `jnet_system_enabled` | Operational toggle — admin can turn JNET on/off without a redeploy | `cjis_admin` via settings page |
| `jnet_authorized_users` table | Per-user access — only listed users see JNET features | `cjis_admin` via user management page |

All three must align for an officer to see and use JNET. If any layer says no, the feature is invisible (404), not forbidden (403).
