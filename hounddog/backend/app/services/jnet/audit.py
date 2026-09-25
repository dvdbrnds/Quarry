"""
CJIS audit logging — writes to cjis_audit_logs for every JNET query.

This function MUST NEVER raise an exception. A failed audit write
should not prevent the query response from reaching the officer,
but should trigger an alert via structlog.
"""

import uuid
from datetime import datetime, timezone

import sentry_sdk
import structlog

from ...database import async_session
from ...models.cjis_audit_log import CJISAuditLog

logger = structlog.get_logger("quarry.cjis.audit")


async def log_jnet_query(
    *,
    user_id: uuid.UUID,
    user_email: str,
    user_full_name: str,
    action: str,
    query_plate: str,
    query_state: str,
    ori: str,
    source_ip: str,
    device_id: str | None = None,
    session_id: uuid.UUID | None = None,
    success: bool,
    error_message: str | None = None,
    response_time_ms: int = 0,
) -> CJISAuditLog | None:
    """
    Create an append-only CJIS audit log entry.

    Returns the created log entry on success, None on failure.
    NEVER raises — all errors are caught and logged.
    """
    try:
        entry = CJISAuditLog(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            user_email=user_email,
            user_full_name=user_full_name,
            action=action,
            query_plate=query_plate,
            query_state=query_state,
            ori=ori,
            source_ip=source_ip,
            device_id=device_id,
            session_id=session_id,
            success=success,
            error_message=error_message,
            response_time_ms=response_time_ms,
        )

        async with async_session() as session:
            async with session.begin():
                session.add(entry)

        logger.info(
            "cjis_audit_logged",
            user=user_email,
            action=action,
            plate=query_plate,
            success=success,
            response_time_ms=response_time_ms,
        )

        return entry

    except Exception as exc:
        # CRITICAL: audit write failure must not propagate, but must be visible
        sentry_sdk.capture_exception(exc)
        logger.error(
            "cjis_audit_write_failed",
            user=user_email,
            action=action,
            plate=query_plate,
            error=str(exc),
            exc_info=True,
        )
        return None
