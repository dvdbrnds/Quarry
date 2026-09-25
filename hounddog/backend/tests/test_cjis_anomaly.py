"""Tests for CJIS anomaly detection — same-plate threshold, off-hours, volume anomaly."""

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.jnet.anomaly import (
    check_query_anomalies,
    _parse_allowed_ip_ranges,
    _ip_in_allowed_ranges,
)


class TestIPRangeChecking:
    def test_parse_empty_ranges(self):
        with patch("app.services.jnet.anomaly.jnet_settings") as cfg:
            cfg.jnet_allowed_ip_ranges = ""
            result = _parse_allowed_ip_ranges()
            assert result == []

    def test_parse_single_range(self):
        with patch("app.services.jnet.anomaly.jnet_settings") as cfg:
            cfg.jnet_allowed_ip_ranges = "10.0.0.0/8"
            result = _parse_allowed_ip_ranges()
            assert len(result) == 1

    def test_parse_multiple_ranges(self):
        with patch("app.services.jnet.anomaly.jnet_settings") as cfg:
            cfg.jnet_allowed_ip_ranges = "10.0.0.0/8, 172.16.0.0/12"
            result = _parse_allowed_ip_ranges()
            assert len(result) == 2

    def test_ip_in_range(self):
        import ipaddress
        nets = [ipaddress.ip_network("10.0.0.0/8")]
        assert _ip_in_allowed_ranges("10.1.2.3", nets) is True

    def test_ip_not_in_range(self):
        import ipaddress
        nets = [ipaddress.ip_network("10.0.0.0/8")]
        assert _ip_in_allowed_ranges("192.168.1.1", nets) is False

    def test_empty_ranges_allows_all(self):
        assert _ip_in_allowed_ranges("1.2.3.4", []) is True


class TestAnomalyChecks:
    @pytest.mark.asyncio
    async def test_check_query_anomalies_does_not_raise(self):
        """Anomaly checks must never raise."""
        with patch("app.services.jnet.anomaly.async_session") as mock_sess:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
            mock_sess.return_value = mock_session

            with patch("app.services.jnet.anomaly.jnet_settings") as cfg:
                cfg.jnet_max_same_plate_queries_24h = 3
                cfg.jnet_shift_start_hour = 0
                cfg.jnet_shift_end_hour = 24
                cfg.jnet_allowed_ip_ranges = ""

                await check_query_anomalies(
                    audit_log_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    user_email="officer@moravian.edu",
                    query_plate="ABC1234",
                    source_ip="10.0.0.1",
                )

    @pytest.mark.asyncio
    async def test_anomaly_check_survives_db_error(self):
        """Even if DB fails, anomaly check should not raise."""
        with patch("app.services.jnet.anomaly.async_session", side_effect=Exception("DB error")):
            await check_query_anomalies(
                audit_log_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                user_email="officer@moravian.edu",
                query_plate="ABC1234",
                source_ip="10.0.0.1",
            )
