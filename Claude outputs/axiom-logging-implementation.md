# Axiom Logging Implementation Guide — Quarry/Hounddog

## Overview

Replace plain-text `logging.getLogger()` calls with **structlog** (JSON output), ship logs to **Axiom** via their Python SDK, and add a device-log ingestion endpoint for BirdDog iOS devices. The existing PostgreSQL audit middleware stays untouched — it's the legal chain of evidence. Axiom is the operational observability layer.

## What Changes

| Component | Before | After |
|-----------|--------|-------|
| Log format | Plain text to stdout | JSON to stdout + Axiom |
| Log library | stdlib `logging` | `structlog` wrapping stdlib |
| BirdDog logs | None (on-device only) | Batched POST to `/api/device-logs` → Axiom |
| AI access | None | Read-only Axiom API tokens per tool |
| Alerting | Sentry (errors only) | Sentry (errors) + Axiom monitors (ops) |

---

## 1. New Dependencies

Add to `backend/requirements.txt`:

```
structlog>=24.1.0
axiom-py>=1.0.0
```

Add to `.env.example`:

```bash
# ─── Axiom (Observability) ───────────────────────────────────
AXIOM_TOKEN=xaat-...           # API token with ingest + query permissions
AXIOM_ORG_ID=moravian-parking  # your Axiom org slug
AXIOM_DATASET=hounddog         # main app logs
AXIOM_DEVICE_DATASET=birddog   # enforcement device logs
```

---

## 2. Config Changes

In `app/config.py`, add these fields to the Settings class:

```python
# Axiom
axiom_token: str = ""
axiom_org_id: str = ""
axiom_dataset: str = "hounddog"
axiom_device_dataset: str = "birddog"
```

---

## 3. Structured Logging Setup

Create a new file `backend/app/logging_config.py`:

```python
"""Structured logging with Axiom shipping."""
import logging
import os
import structlog
from axiom_py import Client as AxiomClient

_axiom_client = None


def get_axiom_client() -> AxiomClient | None:
    global _axiom_client
    if _axiom_client is None:
        token = os.getenv("AXIOM_TOKEN", "")
        org = os.getenv("AXIOM_ORG_ID", "")
        if token:
            _axiom_client = AxiomClient(token=token, org_id=org)
    return _axiom_client


class AxiomHandler(logging.Handler):
    """Ship log records to Axiom in batches via the Python SDK."""

    def __init__(self, dataset: str):
        super().__init__()
        self.dataset = dataset
        self._buffer: list[dict] = []
        self._buffer_limit = 50

    def emit(self, record: logging.LogRecord):
        client = get_axiom_client()
        if not client:
            return
        # structlog puts the full event dict on record._structlog if we use
        # the stdlib foreign pre-chain; otherwise fall back to basic fields
        event = getattr(record, "_structlog", None)
        if event is None:
            event = {
                "message": record.getMessage(),
                "level": record.levelname.lower(),
                "logger": record.name,
            }
        self._buffer.append(event)
        if len(self._buffer) >= self._buffer_limit:
            self.flush()

    def flush(self):
        client = get_axiom_client()
        if not client or not self._buffer:
            return
        try:
            client.ingest_events(self.dataset, self._buffer)
        except Exception:
            # Don't crash the app if Axiom is unreachable
            pass
        self._buffer.clear()


def setup_logging():
    """Call once at startup, before any logger is used."""
    from .config import settings

    # Shared processors that run on every log line
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Configure structlog to wrap stdlib logging
    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare event_dict for stdlib logging
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # JSON formatter for stdlib handlers
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
        if os.getenv("DEBUG")
        else structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    # Root handler: stdout (picked up by supervisord/Docker)
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(console)
    root.setLevel(logging.INFO)

    # Axiom handler (if configured)
    if settings.axiom_token:
        # JSON formatter for Axiom (always JSON, never console)
        axiom_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )

        axiom_handler = AxiomHandler(dataset=settings.axiom_dataset)
        axiom_handler.setFormatter(axiom_formatter)

        # Attach a custom emit that stashes the structlog event dict
        _orig_emit = axiom_handler.emit

        def _axiom_emit(record):
            # The ProcessorFormatter puts the rendered JSON string in
            # record.msg; for Axiom we want the dict. Grab it from
            # the structlog context if available.
            if hasattr(record, "_structlog_event"):
                record._structlog = record._structlog_event
            _orig_emit(record)

        axiom_handler.emit = _axiom_emit
        root.addHandler(axiom_handler)

    # Quiet down noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
```

---

## 4. Hook Into main.py

Two changes in `backend/app/main.py`:

### 4a. Replace the logger declaration at the top

```python
# BEFORE (line 2 + line 72):
import logging
# ...
logger = logging.getLogger("quarry")

# AFTER:
import logging
import structlog
# ...
logger = structlog.get_logger("quarry")
```

### 4b. Call setup_logging() at the very start of lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from .logging_config import setup_logging
    setup_logging()

    # ... rest of existing lifespan code unchanged ...
```

### 4c. Add request-context middleware

Add this right after the CORS middleware block (around line 1416):

```python
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import structlog

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind correlation ID, user, and endpoint to every log line."""
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
        user_email = getattr(request.state, "user_email", None) or "anonymous"

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            user=user_email,
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        return response

# Add AFTER AuditMiddleware (middleware stack is LIFO):
app.add_middleware(RequestContextMiddleware)
```

---

## 5. Migrate Existing Logger Calls

Every file that does `logging.getLogger("quarry.xxx")` switches to structlog. The call sites themselves barely change:

```python
# BEFORE (e.g. in routers/payments.py):
import logging
logger = logging.getLogger("quarry.payments")
logger.info("Payment processed for %s: $%.2f", email, amount)

# AFTER:
import structlog
logger = structlog.get_logger("quarry.payments")
logger.info("payment_processed", email=email, amount=amount)
```

The key difference: instead of %-formatting strings, pass structured kwargs. This makes every field queryable in Axiom.

Files to update (6 total):

| File | Logger name |
|------|-------------|
| `main.py` | `quarry` |
| `middleware/audit.py` | `quarry.audit` |
| `routers/permits.py` | `quarry.permits` |
| `routers/payments.py` | `quarry.payments` |
| `routers/lottery_v2.py` | `quarry.lottery_v2` |
| `services/permit_lifecycle.py` | `quarry.permits` |
| `services/lottery_v2_runner.py` | (uses `__name__`) |

You don't have to migrate all the `logger.info("message %s", val)` calls at once. structlog's stdlib integration means old-style %-format calls still work — they just won't have structured fields. Migrate the high-value ones first (payments, permits, lottery) and clean up the rest over time.

---

## 6. BirdDog Device Log Endpoint

Create `backend/app/routers/device_logs.py`:

```python
"""Ingest logs from BirdDog enforcement devices."""
import structlog
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..auth.okta import require_office
from ..logging_config import get_axiom_client
from ..config import settings

logger = structlog.get_logger("quarry.device_logs")
router = APIRouter()


class DeviceLogEntry(BaseModel):
    timestamp: datetime
    level: str = "info"          # info | warning | error
    event: str                   # e.g. "ticket_issued", "scan_failed"
    device_id: str               # BirdDog device UUID
    officer_email: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    battery_pct: Optional[int] = None
    app_version: Optional[str] = None
    extra: Optional[dict] = None  # catch-all for action-specific data


class DeviceLogBatch(BaseModel):
    entries: list[DeviceLogEntry]


@router.post("", status_code=202)
async def ingest_device_logs(
    batch: DeviceLogBatch,
    _user=Depends(require_office),
):
    """Accept a batch of log entries from a BirdDog device.

    The iOS app collects logs locally and POSTs them in batches
    (every 30s or when the buffer hits 50 entries, whichever first).
    """
    if not batch.entries:
        raise HTTPException(400, "Empty batch")
    if len(batch.entries) > 500:
        raise HTTPException(400, "Batch too large (max 500)")

    client = get_axiom_client()
    if not client:
        logger.warning("device_logs_dropped", count=len(batch.entries),
                       reason="axiom_not_configured")
        return {"accepted": 0, "reason": "logging not configured"}

    events = []
    for entry in batch.entries:
        ev = {
            "_time": entry.timestamp.isoformat(),
            "level": entry.level,
            "event": entry.event,
            "device_id": entry.device_id,
            "officer": entry.officer_email,
            "app_version": entry.app_version,
        }
        if entry.lat and entry.lon:
            ev["location"] = {"lat": entry.lat, "lon": entry.lon}
        if entry.battery_pct is not None:
            ev["battery_pct"] = entry.battery_pct
        if entry.extra:
            ev.update(entry.extra)
        events.append(ev)

    try:
        client.ingest_events(settings.axiom_device_dataset, events)
    except Exception as exc:
        logger.error("axiom_ingest_failed", dataset="birddog", error=str(exc))
        raise HTTPException(502, "Log shipping failed")

    logger.info("device_logs_ingested", count=len(events),
                device_id=batch.entries[0].device_id)
    return {"accepted": len(events)}
```

Register in `main.py`:

```python
from .routers import device_logs
# ...
app.include_router(device_logs.router, prefix="/api/device-logs", tags=["device-logs"])
```

---

## 7. BirdDog iOS Changes

In the Swift app, add a `LogShipper` class that buffers log entries and POSTs them:

```swift
// LogShipper.swift
import Foundation

struct DeviceLogEntry: Codable {
    let timestamp: Date
    let level: String
    let event: String
    let deviceId: String
    let officerEmail: String?
    let lat: Double?
    let lon: Double?
    let batteryPct: Int?
    let appVersion: String?
    let extra: [String: AnyCodable]?

    enum CodingKeys: String, CodingKey {
        case timestamp, level, event
        case deviceId = "device_id"
        case officerEmail = "officer_email"
        case lat, lon
        case batteryPct = "battery_pct"
        case appVersion = "app_version"
        case extra
    }
}

actor LogShipper {
    static let shared = LogShipper()
    private var buffer: [DeviceLogEntry] = []
    private let maxBuffer = 50
    private let flushInterval: TimeInterval = 30

    func log(_ event: String, level: String = "info",
             extra: [String: AnyCodable]? = nil) {
        let entry = DeviceLogEntry(
            timestamp: Date(),
            level: level,
            event: event,
            deviceId: UIDevice.current.identifierForVendor?.uuidString ?? "unknown",
            officerEmail: AuthManager.shared.currentEmail,
            lat: LocationManager.shared.lastLocation?.coordinate.latitude,
            lon: LocationManager.shared.lastLocation?.coordinate.longitude,
            batteryPct: Int(UIDevice.current.batteryLevel * 100),
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String,
            extra: extra
        )
        buffer.append(entry)
        if buffer.count >= maxBuffer { await flush() }
    }

    func flush() async {
        guard !buffer.isEmpty else { return }
        let batch = buffer
        buffer.removeAll()
        // POST to /api/device-logs with auth header
        // On failure, re-add to buffer for retry
    }
}
```

Call it from enforcement actions:

```swift
await LogShipper.shared.log("ticket_issued", extra: [
    "plate": .string(plate),
    "violation": .string(violationType),
    "lot": .string(lotName)
])
```

---

## 8. Axiom Setup (Web Console)

1. **Create account** at axiom.co (free tier: 500 GB/month ingest, 30-day retention)
2. **Create two datasets**: `hounddog` (backend logs) and `birddog` (device logs)
3. **Create API tokens**:
   - `quarry-ingest` — Ingest permission on both datasets (goes in `.env`)
   - `quarry-ai-readonly` — Query-only permission on both datasets (for Claude/AI tools)
4. **Set the env vars** in your Coolify deployment

---

## 9. AI Access

Any AI tool that can make HTTP requests can query Axiom. The APL (Axiom Processing Language) is Kusto-like:

```bash
# Example: last 50 errors
curl -s https://api.axiom.co/v1/datasets/hounddog/query \
  -H "Authorization: Bearer xaat-READONLY-TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"apl": "hounddog | where level == \"error\" | sort by _time desc | take 50"}'
```

### Useful APL queries for AI tools

```kusto
// Errors in the last hour
hounddog
| where _time > ago(1h) and level == "error"
| project _time, logger, event, user, path

// Permit type changes (the thing that bit us in the lottery bug)
hounddog
| where logger == "quarry.permits" and event contains "permit_type"
| project _time, user, event, permit_id, old_type, new_type

// Payment failures
hounddog
| where logger == "quarry.payments" and level == "error"
| summarize count() by bin(_time, 1h)

// BirdDog device health
birddog
| summarize avg(battery_pct), count() by device_id, bin(_time, 1h)

// Officers with scan errors
birddog
| where level == "error"
| summarize error_count = count() by officer, event
| sort by error_count desc
```

### Claude scheduled task (optional)

Set up a Claude scheduled task that queries Axiom every morning for anomalies:

> Check the Quarry Axiom logs for the last 24 hours. Query the hounddog dataset for: error spikes (>10 errors in any 15-min window), any permit_type mutation events, payment failures, and 5xx responses. Query the birddog dataset for: devices that haven't reported in 8+ hours, scan error rates above 10%. Summarize findings and flag anything that needs attention.

---

## 10. Axiom Alerting (Monitors)

Set up in the Axiom web console under Monitors:

| Monitor | APL Query | Threshold | Notify |
|---------|-----------|-----------|--------|
| Error spike | `hounddog \| where level == "error" \| summarize count() by bin(_time, 15m)` | > 10 per 15 min | Email to parking@moravian.edu |
| Payment failure | `hounddog \| where logger == "quarry.payments" and level == "error"` | Any occurrence | Email + Slack |
| Device offline | `birddog \| summarize last_seen = max(_time) by device_id \| where last_seen < ago(8h)` | Any match | Email |
| Permit mutation | `hounddog \| where event contains "permit_type_changed"` | Any occurrence | Email |

---

## 11. Docker / Deployment Changes

No Dockerfile changes needed. structlog and axiom-py are pure Python — they install via `requirements.txt` and run inside the existing container. The only deployment change is adding the four `AXIOM_*` env vars in Coolify.

Supervisord config stays the same — structlog still writes to stdout, which supervisord pipes to Docker's log driver. Axiom shipping happens in-process via the AxiomHandler.

---

## 12. Rollout Order

1. **Add deps** — `structlog` and `axiom-py` to requirements.txt
2. **Add `logging_config.py`** — the new module
3. **Wire up lifespan** — call `setup_logging()` first thing
4. **Add RequestContextMiddleware** — correlation IDs on every request
5. **Add device_logs router** — the BirdDog ingestion endpoint
6. **Deploy without AXIOM_TOKEN** — validates structlog works, logs go to stdout as JSON
7. **Create Axiom account + datasets + tokens**
8. **Set AXIOM_TOKEN in Coolify** — logs start flowing to Axiom
9. **Migrate high-value loggers** — payments, permits, lottery to structured kwargs
10. **Add BirdDog LogShipper** — iOS app starts shipping device logs
11. **Set up monitors** — alerting in Axiom console
12. **Create AI read-only token** — hand to Claude / other tools

Steps 1–6 are one PR. Steps 7–8 are Axiom console + Coolify config. Steps 9–12 are follow-up work.
