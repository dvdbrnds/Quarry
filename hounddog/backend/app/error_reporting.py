"""Error reporting. Exceptions and alerts are logged at error level, which ships them to Axiom."""
import structlog

_log = structlog.get_logger("quarry.errors")
_LEVELS = {"debug", "info", "warning", "error", "critical"}


def capture_exception(exc: BaseException | None = None, **context) -> None:
    """Never raises — reporting must not break the caller."""
    try:
        if exc is None:
            _log.error("exception", exc_info=True, **context)
            return
        _log.error(
            "exception",
            error=f"{type(exc).__name__}: {exc}"[:2000],
            exc_info=(type(exc), exc, exc.__traceback__),
            **context,
        )
    except Exception:
        pass


def capture_message(message: str, level: str = "error", **context) -> None:
    try:
        getattr(_log, level if level in _LEVELS else "error")(message, **context)
    except Exception:
        pass
