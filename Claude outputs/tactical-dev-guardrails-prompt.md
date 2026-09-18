# Cursor Prompt — Tactical Dev Guardrails

## Context

Quarry is the parking management monorepo (Hounddog backend + React frontend, BirdDog iOS app). A git commit audit of 1,077 commits found ~130 rework commits (~85 hours wasted) across 22 repeated fix clusters. The biggest culprits: errors silently swallowed (27 commits), WAF blocking HTTP methods discovered repeatedly (10 commits), business rules coded without specs (20+ commits), and pure functions breaking with no tests (30+ commits).

This prompt installs three layers of protection without changing the deploy flow (commit → push → Coolify redeploy). Nothing here gates deploys or adds a staging server.

**Important constraints:**
- Do NOT create a CI pipeline, GitHub Actions, or pre-commit hooks
- Do NOT set up a staging server or second Coolify instance
- Do NOT add pytest, jest, or any test framework as a dependency
- Do NOT change how deploys work -- commit, push, redeploy in Coolify stays the same
- Do NOT refactor application logic in this prompt -- only add the guardrail infrastructure

---

## Step 0: Orientation — Read the codebase first

**You are starting cold on this repo. Do NOT write any code until you have completed this step.**

### 0a. Understand the repo layout

Explore the top-level directory structure. Find:
- Where the backend lives (likely `backend/` or `hounddog/`)
- Where the frontend lives (likely `frontend/`)
- Where the iOS app lives (likely `BirdDog/`)
- Whether a `CLAUDE.md` or `.cursorrules` file already exists at the repo root

### 0b. Map the backend structure

Find and read:
- The FastAPI entry point (`main.py` -- find the file that creates the `FastAPI()` app instance)
- The routers directory (where API route files live)
- The services directory (where business logic lives, if it exists)
- The middleware directory (if it exists)
- `requirements.txt` or `pyproject.toml` (wherever Python dependencies are declared)
- The Dockerfile (understand how the app is built and started)

### 0c. Map the iOS app structure

Find and read:
- `BirdDog/project.yml` (XcodeGen project definition -- this is where packages and dependencies are declared)
- The app entry point (the `@main` App struct or AppDelegate)
- The existing `packages` section in project.yml to understand the current dependency format

### 0d. Find the specific code patterns you'll be modifying

Before writing anything, search for and understand:
1. **How routers are currently created:** `grep -r "APIRouter" backend/` -- find every file that imports and instantiates APIRouter. You will need to change all of them.
2. **How errors are currently handled:** `grep -rn "except.*Exception" backend/` -- find every silent exception handler. Note which ones swallow errors with `pass` or just `logger.error`.
3. **Existing DELETE/PATCH routes:** `grep -rn "\.delete\|\.patch\|DELETE\|PATCH" backend/app/routers/` -- find any routes using blocked HTTP methods that need to be converted.
4. **Where access/lot/capacity logic lives:** Search for functions that check lot access by time of day, normalize lot names/codes, or match lots to capacity numbers. Note their file paths and function signatures -- you'll extract these into pure functions for smoke tests.
5. **Existing middleware:** Read how middleware is currently registered in main.py so you add new middleware in the right place and order.

### 0e. Check for existing guardrails

Look for any of these that might already exist (don't create duplicates):
- `INFRASTRUCTURE.md`
- `BUSINESS_RULES.md`
- A `tests/` directory in the backend
- Any existing Sentry or Axiom integration
- Any `.env.example` or environment variable documentation

**Only proceed to Step 1 after you have a clear mental map of the codebase.** The file paths used in subsequent steps are best guesses -- use the actual paths you discovered in this step.

---

## Step 1: Add Sentry to Hounddog (backend)

### 1a. Install the SDK

```bash
pip install sentry-sdk[fastapi]
```

Add `sentry-sdk[fastapi]` to `requirements.txt`.

### 1b. Initialize Sentry in main.py

At the very top of `backend/app/main.py`, before the `FastAPI()` constructor:

```python
import sentry_sdk

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    traces_sample_rate=0.1,
    profiles_sample_rate=0.1,
    environment=os.environ.get("DEPLOY_ENV", "production"),
    release=os.environ.get("GIT_SHA", "dev"),
)
```

### 1c. Add Coolify environment variables

These go in the Coolify service environment variables (not in code):

```
SENTRY_DSN=<will be provided after creating the Sentry project>
GIT_SHA=${SOURCE_COMMIT}
DEPLOY_ENV=production
```

### 1d. Audit silent exception handlers

Search the entire backend for patterns that swallow errors. For every instance of these patterns:

```python
# Pattern 1: bare except pass
except Exception:
    pass

# Pattern 2: log and continue
except Exception as e:
    logger.error(e)
```

Replace with:

```python
except Exception as e:
    sentry_sdk.capture_exception(e)
    # keep the existing fallback behavior (return None, continue, etc.)
```

**Do NOT change the control flow.** If the code currently returns None on error, it should still return None. Just add the `sentry_sdk.capture_exception(e)` call so the error is reported.

Key files to audit (based on the rework clusters):
- `backend/app/routers/payments.py` -- Stripe webhook handlers
- `backend/app/services/capacity.py` or wherever capacity audit lives
- `backend/app/services/sis_student_data.py` -- SIS external calls
- Any backup/scheduler code
- Any middleware that catches exceptions

---

## Step 2: Add Sentry to BirdDog (iOS)

### 2a. Add the Swift package

In `project.yml`, add to the `packages` section:

```yaml
Sentry:
  url: https://github.com/getsentry/sentry-cocoa
  from: "8.0.0"
```

And add `Sentry` to the target's dependencies:

```yaml
dependencies:
  - package: Sentry
```

### 2b. Initialize in the app entry point

In the `@main` App struct or AppDelegate, add:

```swift
import Sentry

// In init() or application(_:didFinishLaunchingWithOptions:)
SentrySDK.start { options in
    options.dsn = "https://your-key@o123.ingest.us.sentry.io/456"
    options.tracesSampleRate = 0.2
    options.enableAutoPerformanceTracing = true
    options.attachScreenshot = true
    options.environment = "production"
}
```

### 2c. Regenerate the Xcode project

```bash
xcodegen generate
```

---

## Step 3: Add Axiom request logging middleware

### 3a. Create the middleware file

Create `backend/app/middleware/axiom_logging.py`:

```python
import time
import os
import logging
import httpx
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

AXIOM_TOKEN = os.environ.get("AXIOM_TOKEN")
AXIOM_DATASET = os.environ.get("AXIOM_DATASET", "hounddog")
AXIOM_URL = f"https://api.axiom.co/v1/datasets/{AXIOM_DATASET}/ingest"


class AxiomRequestLogger(BaseHTTPMiddleware):
    """Logs every request to Axiom with timing, user, status, and deploy SHA."""

    async def dispatch(self, request, call_next):
        start = time.monotonic()
        response = None
        error = None

        try:
            response = await call_next(request)
            return response
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            user = getattr(request.state, "user", None)

            event = {
                "_time": time.time(),
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query) if request.url.query else None,
                "status": response.status_code if response else 500,
                "duration_ms": round(duration_ms, 1),
                "user": user.email if user and hasattr(user, "email") else None,
                "user_agent": request.headers.get("user-agent", "")[:200],
                "error": error,
                "deploy_sha": os.environ.get("GIT_SHA", "unknown"),
            }

            if AXIOM_TOKEN:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            AXIOM_URL,
                            json=[event],
                            headers={
                                "Authorization": f"Bearer {AXIOM_TOKEN}",
                                "Content-Type": "application/json",
                            },
                            timeout=2.0,
                        )
                except Exception:
                    pass  # Logging must never break the app
```

### 3b. Register the middleware in main.py

In `backend/app/main.py`, after the FastAPI app is created:

```python
from app.middleware.axiom_logging import AxiomRequestLogger

app.add_middleware(AxiomRequestLogger)
```

Add it AFTER Sentry init so Sentry's middleware wraps it (Sentry should be outermost).

### 3c. Add Coolify environment variables

```
AXIOM_TOKEN=<your axiom API token>
AXIOM_DATASET=hounddog
AXIOM_ORG_ID=<your axiom org id>
```

**Reminder:** The user still needs to create the `hounddog` dataset in Axiom and generate the API token. The BirdDog dataset is separate and was discussed in a prior session.

---

## Step 4: Create SafeRouter to prevent WAF-blocked methods

### 4a. Create the utility

Create `backend/app/utils/safe_router.py`:

```python
"""
APIRouter subclass that refuses to register HTTP DELETE or PATCH routes.

Moravian's WAF silently blocks these methods in production. This was
discovered and re-discovered three separate times (10 commits, ~6 hours
wasted). SafeRouter makes the failure happen at import time with a clear
message instead of silently in production weeks later.

See INFRASTRUCTURE.md for the full list of WAF constraints.
"""

from fastapi import APIRouter


class SafeRouter(APIRouter):

    def api_route(self, path, *, methods=None, **kwargs):
        if methods:
            blocked = {"DELETE", "PATCH"} & {m.upper() for m in methods}
            if blocked:
                raise ValueError(
                    f"WAF blocks {blocked} -- see INFRASTRUCTURE.md. "
                    f"Use POST with an action verb instead: "
                    f"POST {path}/revoke, POST {path}/archive"
                )
        return super().api_route(path, methods=methods, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "WAF blocks HTTP DELETE -- use POST with /revoke or /archive. "
            "See INFRASTRUCTURE.md."
        )

    def patch(self, *args, **kwargs):
        raise ValueError(
            "WAF blocks HTTP PATCH -- use PUT or POST. "
            "See INFRASTRUCTURE.md."
        )
```

### 4b. Replace APIRouter imports in all route files

Use the list of files you found in Step 0d (grep for APIRouter). In every route file, change:

```python
# Before:
from fastapi import APIRouter
router = APIRouter()

# After:
from app.utils.safe_router import SafeRouter
router = SafeRouter()
```

If any existing routes use `router.delete()` or `router.patch()`, they need to be converted:

- `DELETE /api/something/{id}` → `POST /api/something/{id}/revoke` or `POST /api/something/{id}/archive`
- `PATCH /api/something/{id}` → `PUT /api/something/{id}` or `POST /api/something/{id}/update`

Update the corresponding frontend fetch calls to use the new method and URL.

**Known existing DELETE/PATCH routes to convert** (you already found these in Step 0d -- use that list). From the git history, likely candidates include:

- Sponsor permit deletion (was already converted to POST /revoke in a prior fix -- verify it stayed that way)
- Any lot deletion endpoints
- Any permit deactivation endpoints
- Any ticket deletion endpoints

For each one: change the route decorator, update the URL path to include an action verb, and search the frontend for the corresponding fetch/axios call to update the method and URL there too.

---

## Step 5: Create INFRASTRUCTURE.md

Create `INFRASTRUCTURE.md` in the repo root:

```markdown
# Moravian Infrastructure Constraints

Last updated: 2026-09-18

## WAF (Web Application Firewall)

- **HTTP DELETE is BLOCKED.** Requests silently receive a 403 or are dropped. Use POST endpoints with action verbs: `/revoke`, `/archive`, `/deactivate`.
- **HTTP PATCH is BLOCKED.** Use PUT for full updates or POST for partial updates.
- **Field names containing "delete" in PATCH/PUT bodies may be blocked.** Rename fields to `revoke`, `deactivate`, `remove`, or `archive`.
- **Request bodies over ~10MB may be silently truncated.**
- **SafeRouter enforces this in code.** All backend routes must use `SafeRouter` instead of `APIRouter`. See `backend/app/utils/safe_router.py`.

## CSP (Content Security Policy)

Required origins for features currently in use:

- **Google Maps:** `*.googleapis.com`, `*.gstatic.com` in `script-src` and `connect-src`; `fonts.googleapis.com` in `style-src`
- **Okta SSO:** `login.moravian.edu` AND `*.okta.com` in `frame-src` and `connect-src`
- **Stripe:** `js.stripe.com` in `script-src` and `frame-src`; `api.stripe.com` in `connect-src`
- **Sentry:** `*.ingest.us.sentry.io` in `connect-src`
- **Axiom:** `api.axiom.co` in `connect-src`

## Container (Coolify / Docker)

- **Filesystem is EPHEMERAL.** Never persist data to disk -- it is lost on redeploy. Use PostgreSQL for all persistent state (branding settings, backups, uploads).
- **No system cron.** Use APScheduler or FastAPI background tasks.
- **Backups must write to external storage** (mounted volume or S3), not to container-local paths like `/tmp` or `/data`.
- **Health check endpoint** must exist at `GET /health` and return 200 within 5 seconds.

## Okta SSO

- **ID token may not contain the `groups` claim.** Always fall back to the `/userinfo` endpoint to get group membership.
- **Callback page must initialize the auth SDK independently** -- do not rely on app-level state being available on the callback route.
- **Session restoration:** If a restored session has no group data, force re-login.

## Database (PostgreSQL)

- **Startup migrations must not race with web workers.** Use a single-worker migration entrypoint or Alembic with proper lock management.
- **ARRAY columns:** Use `sqlalchemy.dialects.postgresql.ARRAY`, not the generic `sqlalchemy.ARRAY`.
- **Lot names:** Always normalize with the `normalize_lot_code()` function. "Lot M", "lot m", and "M" are the same lot.

## External Services

- **SIS (Jenzabar):** Calls can take 10+ seconds. Always wrap in `asyncio.wait_for()` with a timeout. Never call from a synchronous request handler.
- **Stripe:** Webhook handlers must return quickly. Do heavy work in background tasks. Always log the full Stripe error, never swallow it.
- **Star Micronics printers (BirdDog):** Use classic Bluetooth discovery, not BLE. Per-job open/print/close pattern required (no persistent connection).
```

---

## Step 6: Create BUSINESS_RULES.md

Create `BUSINESS_RULES.md` in the repo root:

```markdown
# Business Rules -- Quarry Parking

Last updated: 2026-09-18

**Before changing any of these rules in code, update this file FIRST.**

## Lottery Eligibility

- Freshmen (class year = current academic year + 4) are excluded from residential parking lotteries by default.
- Each lottery cycle can override this with its own "Allow Freshmen" toggle.
- Commuter permits are NOT subject to the freshmen restriction.
- Lottery draw is time-based only (auto_draw_days). There is no threshold trigger.
- Application timing does not affect lottery outcome -- all applications submitted before the deadline are weighted equally by seniority.

## After-Hours Access

- Commuter permits gain access to FS and FSC lots after 4:00 PM local time.
- "After 4:00 PM" means >= 16:00. Midnight (00:00) counts as after hours.
- Faculty/staff permits have 24/7 access to all assigned lots.
- Extended Premium Commuter has full-time access to FS, FSC, and all street lots.

## Permit Lifecycle

- All permits expire June 30 annually.
- Renewal emails offer one-click Renew or Decline.
- Decline soft-deletes the permit (recoverable by admin).
- Permit numbers follow QPS format.

## Fee Exemptions and Discounts

- RA status: checked via SIS stored procedure first, falls back to fee_exempt_roster CSV.
- ABSN discount: checked via SIS AccelNursing flag first, falls back to discount_roster/Okta groups.
- Fee-exempt students pay $0. Discount students pay full price minus the configured discount amount.

## Ticket / Citation Rules

- Ticket numbers are sequential: CIT-00001 format.
- QR code on printed ticket links to the payment portal.
- Payment URL format must match between BirdDog (generator) and Hounddog (resolver).

## Sponsor Permits

- Deletion uses POST /revoke (not HTTP DELETE -- WAF blocks it).
- Revocation is soft-delete (recoverable).
```

---

## Step 7: Create smoke tests

Create `backend/tests/smoke.py`:

```python
"""
Smoke tests for the logic that keeps breaking.
Run manually: python -m tests.smoke (from backend/)
No frameworks. No fixtures. Just assertions on pure functions.

These cover the 5 areas with the most rework commits:
- After-hours access logic (8 rework commits)
- Lot name normalization (4 rework commits)
- Capacity matching (4 rework commits)

Add tests here when you fix a bug in any of these areas.
"""

import sys
from datetime import time


def test_after_hours_access():
    """
    After-hours access was reimplemented 8 times.
    These assertions encode the rules from BUSINESS_RULES.md.
    """
    from app.services.access import check_lot_access

    # Commuter before 4 PM -- NO FSC access
    assert not check_lot_access("commuter", "FSC", time(15, 59)), \
        "Commuter should NOT have FSC access at 3:59 PM"

    # Commuter at exactly 4 PM -- YES
    assert check_lot_access("commuter", "FSC", time(16, 0)), \
        "Commuter SHOULD have FSC access at 4:00 PM"

    # Commuter at midnight -- YES (midnight counts as after hours)
    assert check_lot_access("commuter", "FSC", time(0, 0)), \
        "Commuter SHOULD have FSC access at midnight"

    # Faculty -- always has access
    assert check_lot_access("faculty", "FSC", time(8, 0)), \
        "Faculty SHOULD have FSC access at 8 AM"
    assert check_lot_access("faculty", "FSC", time(15, 0)), \
        "Faculty SHOULD have FSC access at 3 PM"

    # Extended Premium Commuter -- always has access
    assert check_lot_access("extended_premium_commuter", "FSC", time(10, 0)), \
        "Extended Premium Commuter SHOULD have 24/7 FSC access"

    print("  ✓ after-hours access")


def test_lot_normalization():
    """
    Lot name normalization broke 4 times because of inconsistent
    prefix handling ("Lot M" vs "M" vs "lot m").
    """
    from app.services.lots import normalize_lot_code

    assert normalize_lot_code("Lot M") == "M"
    assert normalize_lot_code("lot m") == "M"
    assert normalize_lot_code("M") == "M"
    assert normalize_lot_code("  Lot M  ") == "M"
    assert normalize_lot_code("FSC") == "FSC"
    assert normalize_lot_code("lot fsc") == "FSC"

    print("  ✓ lot normalization")


def test_capacity_matching():
    """
    Capacity matching broke 4 times because lots were matched
    by name OR by ID with inconsistent prefix handling.
    """
    from app.services.capacity import match_lot_to_capacity

    lots = [
        {"id": 1, "name": "Lot M"},
        {"id": 2, "name": "FSC"},
        {"id": 3, "name": "Lot G"},
    ]

    # Match by full name
    assert match_lot_to_capacity("Lot M", lots) == 1
    # Match by code without prefix
    assert match_lot_to_capacity("M", lots) == 1
    # Match by ID
    assert match_lot_to_capacity(2, lots) == 2
    # No match returns None (not crash)
    assert match_lot_to_capacity("NONEXISTENT", lots) is None

    print("  ✓ capacity matching")


if __name__ == "__main__":
    print("Running smoke tests...")
    passed = 0
    failed = 0

    for name, func in list(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                passed += 1
            except Exception as e:
                print(f"  ✗ {name}: {e}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
```

**Important:** The imports above (`app.services.access`, `app.services.lots`, `app.services.capacity`) are examples -- use the actual module paths you discovered in Step 0. These assume the access-checking, lot normalization, and capacity matching logic has been extracted into pure functions in service modules. If this logic currently lives inline in route handlers (which is likely -- check what you found in Step 0d):

1. Find the access-checking logic (the after-hours time window check)
2. Extract it into `backend/app/services/access.py` as a function `check_lot_access(permit_type: str, lot_code: str, current_time: time) -> bool`
3. Find the lot normalization logic
4. Extract it into `backend/app/services/lots.py` as a function `normalize_lot_code(raw: str) -> str`
5. Find the capacity matching logic
6. Extract it into `backend/app/services/capacity.py` as a function `match_lot_to_capacity(identifier, lots: list) -> int | None`

These extractions should be simple cut-and-paste -- move the logic, import the function where it was, verify the app still works.

---

## Step 8: Update CLAUDE.md

Append this to the existing `CLAUDE.md` (or `.cursorrules`) in the repo root:

```markdown
## Guardrails -- Read Before Writing Code

### Before writing any backend route or API endpoint:
- Read INFRASTRUCTURE.md for WAF/CSP/container constraints
- Read BUSINESS_RULES.md for current rule definitions
- Use SafeRouter (from app.utils.safe_router) instead of APIRouter
- Never use HTTP DELETE or PATCH methods -- the WAF blocks them silently
- Never persist files to the container filesystem -- it's ephemeral
- Always surface errors to Sentry -- never silently swallow exceptions
- Log structured events to Axiom for any new endpoint that handles money, external services, or user-facing operations

### Before changing lottery, access, or permit logic:
- Check BUSINESS_RULES.md for the current rule
- If the rule is changing, update BUSINESS_RULES.md FIRST, then implement
- Update or add the corresponding test in tests/smoke.py
- Run `python -m tests.smoke` from backend/ before committing

### Error handling pattern:
```python
try:
    result = await risky_operation()
except Exception as e:
    sentry_sdk.capture_exception(e)
    # degrade gracefully but NEVER silently
    result = fallback_value
```
```

---

## Verification

After completing all steps:

1. **Sentry:** Redeploy Hounddog. Visit a page that doesn't exist (e.g., `/api/nonexistent`). Check Sentry dashboard -- you should see a 404 event within 30 seconds.

2. **Axiom:** Visit any page on the Quarry frontend. Check Axiom -- you should see the request logged with method, path, status, and duration_ms.

3. **SafeRouter:** Try adding a test route with `router.delete("/test", ...)` anywhere. The app should fail to start with a clear ValueError message.

4. **Smoke tests:** Run `cd backend && python -m tests.smoke`. All tests should pass. Then intentionally break one assertion and verify it fails with a clear message.

5. **Docs:** Confirm INFRASTRUCTURE.md, BUSINESS_RULES.md, and the CLAUDE.md additions are committed.

---

## What NOT to do

- Do NOT refactor existing route logic beyond the SafeRouter swap and extracting pure functions for smoke tests
- Do NOT add a test framework or test runner
- Do NOT modify the Dockerfile or docker-compose beyond adding env vars
- Do NOT change the deploy process
- Do NOT set up GitHub Actions or any CI
- Do NOT create a staging environment or second Coolify service
