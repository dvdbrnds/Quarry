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
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
