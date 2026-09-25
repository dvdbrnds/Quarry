"""Tests for CJIS audit logging — every query creates a log, no CJI in logs, append-only."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

from app.services.jnet.audit import log_jnet_query
from app.models.cjis_audit_log import CJISAuditLog


class TestAuditLogging:
    """Verify audit log creation behavior."""

    @pytest.mark.asyncio
    async def test_log_jnet_query_creates_entry(self):
        """Every JNET query must create a log entry."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(), __aexit__=AsyncMock(return_value=False)
        ))

        with patch("app.services.jnet.audit.async_session", return_value=mock_session):
            result = await log_jnet_query(
                user_id=uuid.uuid4(),
                user_email="officer@moravian.edu",
                user_full_name="Test Officer",
                action="plate_lookup",
                query_plate="ABC1234",
                query_state="PA",
                ori="PA0123456",
                source_ip="10.0.0.1",
                success=True,
                response_time_ms=150,
            )

        assert result is not None
        assert isinstance(result, CJISAuditLog)
        assert result.query_plate == "ABC1234"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_log_jnet_query_never_raises(self):
        """Audit logging must never raise — failures are logged to structlog."""
        with patch("app.services.jnet.audit.async_session", side_effect=Exception("DB down")):
            result = await log_jnet_query(
                user_id=uuid.uuid4(),
                user_email="officer@moravian.edu",
                user_full_name="Test Officer",
                action="plate_lookup",
                query_plate="ABC1234",
                query_state="PA",
                ori="PA0123456",
                source_ip="10.0.0.1",
                success=False,
                error_message="JNET timeout",
                response_time_ms=15000,
            )

        # Must return None on failure, not raise
        assert result is None

    @pytest.mark.asyncio
    async def test_log_entry_contains_no_cji(self):
        """The audit log entry must never contain CJI response data."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(), __aexit__=AsyncMock(return_value=False)
        ))

        with patch("app.services.jnet.audit.async_session", return_value=mock_session):
            result = await log_jnet_query(
                user_id=uuid.uuid4(),
                user_email="officer@moravian.edu",
                user_full_name="Test Officer",
                action="plate_lookup",
                query_plate="ABC1234",
                query_state="PA",
                ori="PA0123456",
                source_ip="10.0.0.1",
                success=True,
                response_time_ms=100,
            )

        # Verify the model has no CJI fields
        assert not hasattr(result, "owner_name")
        assert not hasattr(result, "address")
        assert not hasattr(result, "vin")
        assert not hasattr(result, "response_data")


class TestAuditLogModel:
    """Verify the CJISAuditLog model constraints."""

    def test_model_has_no_cji_columns(self):
        """The CJISAuditLog model must not have columns for CJI data."""
        column_names = {c.name for c in CJISAuditLog.__table__.columns}
        cji_fields = {"owner_name", "owner_address", "vin", "vehicle_make",
                       "vehicle_model", "response_data", "response_body"}
        assert column_names.isdisjoint(cji_fields), (
            f"CJISAuditLog has CJI columns: {column_names & cji_fields}"
        )

    def test_table_comment_mentions_cjis_policy(self):
        """The table comment must reference CJIS policy."""
        comment = CJISAuditLog.__table__.comment or ""
        assert "CJIS" in comment
        assert "AU-2" in comment
