# Moravian Infrastructure Constraints

Last updated: 2026-09-18

## WAF (Web Application Firewall)

- **HTTP DELETE is BLOCKED at the WAF level.** The frontend works around this by sending `POST` with an `X-HTTP-Method-Override: DELETE` header, which `MethodOverrideMiddleware` in `main.py` translates back to DELETE internally. New DELETE routes work automatically — just use `router.delete()` and the middleware handles the rest.
- **HTTP PATCH is BLOCKED.** Use PUT for full updates or POST for partial updates. `SafeRouter` enforces this at import time — see `backend/app/utils/safe_router.py`.
- **Field names containing "delete" in PATCH/PUT bodies may be blocked.** Rename fields to `revoke`, `deactivate`, `remove`, or `archive`.
- **Request bodies over ~10MB may be silently truncated.**

## CSP (Content Security Policy)

Required origins for features currently in use:

- **Google Maps:** `*.googleapis.com`, `*.gstatic.com` in `script-src` and `connect-src`; `fonts.googleapis.com` in `style-src`
- **Okta SSO:** `login.moravian.edu` AND `*.okta.com` in `frame-src` and `connect-src`
- **Stripe:** `js.stripe.com` in `script-src` and `frame-src`; `api.stripe.com` in `connect-src`
- **Sentry:** `*.ingest.us.sentry.io` in `connect-src`
- **Axiom:** `api.axiom.co` in `connect-src`

## Container (Coolify / Docker)

- **Filesystem is EPHEMERAL.** Never persist data to disk — it is lost on redeploy. Use PostgreSQL for all persistent state (branding settings, backups, uploads).
- **No system cron.** Use APScheduler or FastAPI background tasks.
- **Backups must write to external storage** (Google Drive or mounted volume), not to container-local paths like `/tmp` or `/data`.
- **Health check endpoint** must exist at `GET /health` and return 200 within 5 seconds.

## Okta SSO

- **ID token may not contain the `groups` claim.** Always fall back to the `/userinfo` endpoint to get group membership.
- **Callback page must initialize the auth SDK independently** — do not rely on app-level state being available on the callback route.
- **Session restoration:** If a restored session has no group data, force re-login.

## Database (PostgreSQL)

- **Startup migrations must not race with web workers.** Use a single-worker migration entrypoint or Alembic with proper lock management.
- **ARRAY columns:** Use `sqlalchemy.dialects.postgresql.ARRAY`, not the generic `sqlalchemy.ARRAY`.
- **Lot names:** Always normalize with `lot_filter_variants()` from `services/lot_assignment.py`. "Lot M", "lot m", and "M" are the same lot.

## External Services

- **SIS (Jenzabar):** Calls can take 10+ seconds. Always wrap in `asyncio.wait_for()` with a timeout. Never call from a synchronous request handler.
- **Stripe:** Webhook handlers must return quickly. Do heavy work in background tasks. Always log the full Stripe error, never swallow it.
- **Star Micronics printers (BirdDog):** Use classic Bluetooth discovery, not BLE. Per-job open/print/close pattern required (no persistent connection).
