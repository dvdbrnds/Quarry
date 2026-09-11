# Cursor Prompt: Add Axiom Structured Logging to Hounddog

## Context

Quarry/Hounddog is a FastAPI parking management system. It currently uses plain stdlib `logging.getLogger("quarry")` with no structured output and no log shipping. We're adding **structlog** for JSON-formatted logs and **axiom-py** to ship them to Axiom for centralized observability. The existing PostgreSQL audit middleware in `app/middleware/audit.py` is a legal chain of evidence and must NOT be modified.

The app runs inside a Docker container managed by supervisord (uvicorn + nginx). Logs go to stdout. Sentry is already configured for error tracking in main.py. The config module uses Pydantic Settings and reads from environment variables.

## What to do

Complete these steps in order. Do not skip any step. Do not modify `app/middleware/audit.py` beyond swapping its logger to structlog.

### Step 1: Add dependencies to `backend/requirements.txt`

Add these two lines:

```
structlog>=24.1.0
axiom-py>=1.0.0
```

### Step 2: Add Axiom config fields to `app/config.py`

Add these four fields to the Settings class (all optional, defaulting to empty string or sensible defaults):

```python
# Axiom
axiom_token: str = ""
axiom_org_id: str = ""
axiom_dataset: str = "hounddog"
axiom_device_dataset: str = "birddog"
```

### Step 3: Add env vars to `.env.example`

Add this block:

```bash
# ─── Axiom (Observability) ───────────────────────────────────
AXIOM_TOKEN=xaat-...           # API token with ingest + query permissions
AXIOM_ORG_ID=moravian-parking  # your Axiom org slug
AXIOM_DATASET=hounddog         # main app logs
AXIOM_DEVICE_DATASET=birddog   # enforcement device logs
```

### Step 4: Create `backend/app/logging_config.py`

This is a brand new file. It contains:

1. `get_axiom_client()` -- singleton that returns an `AxiomClient` if AXIOM_TOKEN is set, else None.
2. `AxiomHandler(logging.Handler)` -- buffers log events and flushes to Axiom every 50 records. Must not crash the app if Axiom is unreachable (catch all exceptions in flush).
3. `setup_logging()` -- called once at startup. Configures structlog to wrap stdlib logging. Sets up:
   - Shared processors: `merge_contextvars`, `add_log_level`, `add_logger_name`, `TimeStamper(fmt="iso")`, `StackInfoRenderer()`, `format_exc_info`
   - Console handler on root logger with `ConsoleRenderer()` when DEBUG env var is set, otherwise `JSONRenderer()`
   - Axiom handler (only when `settings.axiom_token` is set) that ships JSON to the configured dataset
   - Quiets uvicorn.access and sqlalchemy.engine to WARNING level

Full implementation:

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
            pass
        self._buffer.clear()


def setup_logging():
    """Call once at startup, before any logger is used."""
    from .config import settings

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
        if os.getenv("DEBUG")
        else structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(console)
    root.setLevel(logging.INFO)

    if settings.axiom_token:
        axiom_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        axiom_handler = AxiomHandler(dataset=settings.axiom_dataset)
        axiom_handler.setFormatter(axiom_formatter)
        root.addHandler(axiom_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
```

### Step 5: Modify `app/main.py`

Three changes:

**5a.** Add `import structlog` near the top (after `import logging`). Change line 72 from:
```python
logger = logging.getLogger("quarry")
```
to:
```python
logger = structlog.get_logger("quarry")
```

**5b.** At the very top of the `lifespan()` function (before any DB or settings checks), add:
```python
from .logging_config import setup_logging
setup_logging()
```

**5c.** Add a RequestContextMiddleware class and register it. Place the class definition near the other middleware classes. Register it AFTER `app.add_middleware(AuditMiddleware)` (middleware stack is LIFO, so it runs before audit):

```python
import uuid as _uuid

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind correlation ID, user, and endpoint to every log line."""
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id", str(_uuid.uuid4())[:8])
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

app.add_middleware(RequestContextMiddleware)
```

**5d.** Add the device_logs router import and registration:
```python
from .routers import device_logs
# Add with the other router registrations:
app.include_router(device_logs.router, prefix="/api/device-logs", tags=["device-logs"])
```

### Step 6: Create `backend/app/routers/device_logs.py`

Brand new file. Accepts batched log entries from BirdDog iOS enforcement devices and forwards them to Axiom's birddog dataset. Protected by `require_office` auth. Max 500 entries per batch. Returns 202 on success.

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
    level: str = "info"
    event: str
    device_id: str
    officer_email: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    battery_pct: Optional[int] = None
    app_version: Optional[str] = None
    extra: Optional[dict] = None


class DeviceLogBatch(BaseModel):
    entries: list[DeviceLogEntry]


@router.post("", status_code=202)
async def ingest_device_logs(
    batch: DeviceLogBatch,
    _user=Depends(require_office),
):
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

### Step 7: Migrate existing loggers to structlog

In each of these files, replace `import logging` / `logging.getLogger(...)` with `import structlog` / `structlog.get_logger(...)`. The existing log call sites (logger.info, logger.warning, etc.) will still work because structlog wraps stdlib. For high-value log calls in these files, convert %-format strings to structured kwargs where practical.

Files to update:
- `app/middleware/audit.py` -- change `logging.getLogger("quarry.audit")` to `structlog.get_logger("quarry.audit")`. Do NOT change anything else in this file.
- `app/routers/permits.py` -- change `logging.getLogger("quarry.permits")` to `structlog.get_logger("quarry.permits")`
- `app/routers/payments.py` -- change `logging.getLogger("quarry.payments")` to `structlog.get_logger("quarry.payments")`
- `app/routers/lottery_v2.py` -- change `logging.getLogger("quarry.lottery_v2")` to `structlog.get_logger("quarry.lottery_v2")`
- `app/services/permit_lifecycle.py` -- change `logging.getLogger("quarry.permits")` to `structlog.get_logger("quarry.permits")`
- `app/services/lottery_v2_runner.py` -- change `logging.getLogger(__name__)` to `structlog.get_logger(__name__)`

Example conversion of a log call (optional, do where it makes sense):
```python
# Before:
logger.info("Payment processed for %s: $%.2f", email, amount)
# After:
logger.info("payment_processed", email=email, amount=amount)
```

## Important constraints

- Do NOT modify the audit middleware logic (the PostgreSQL writes). Only swap its logger import.
- Do NOT change the Dockerfile or supervisord.conf. structlog still writes to stdout.
- Do NOT add AXIOM_TOKEN to docker-compose.yml or docker-compose.prod.yml. It goes in the .env file which is already loaded via env_file.
- The AxiomHandler must never crash the app. All Axiom calls must be wrapped in try/except.
- If AXIOM_TOKEN is not set, everything still works -- logs just go to stdout only.
