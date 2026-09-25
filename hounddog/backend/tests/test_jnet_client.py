"""Tests for the JNET client — mock mode, mTLS config, timeout, no CJI in logs."""

import pytest
import logging
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.jnet.client import JNETClient, _build_ssl_context
from app.services.jnet.models import JNETPlateResult, JNETOwnerResult, JNETError


class TestJNETClientMockMode:
    """Tests for mock mode (JNET_BASE_URL is empty)."""

    def test_client_defaults_to_mock_mode(self):
        client = JNETClient()
        assert client._mock_mode is True

    @pytest.mark.asyncio
    async def test_plate_lookup_mock_returns_result(self):
        client = JNETClient()
        result, elapsed_ms = await client.plate_lookup("ABC1234", "PA")
        assert isinstance(result, JNETPlateResult)
        assert result.vehicle is not None
        assert result.vehicle.plate_number == "ABC1234"
        assert result.vehicle.plate_state == "PA"
        assert result.owner is not None
        assert result.cjis_notice != ""
        assert elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_owner_lookup_mock_returns_result(self):
        client = JNETClient()
        result, elapsed_ms = await client.registered_owner_lookup("XYZ789", "PA")
        assert isinstance(result, JNETOwnerResult)
        assert result.owner is not None
        assert result.vehicle is not None

    def test_cjis_notice_present(self):
        result = JNETPlateResult()
        assert "federal offense" in result.cjis_notice.lower()


class TestJNETClientNoLogCJI:
    """Verify that CJI response data is never logged."""

    @pytest.mark.asyncio
    async def test_plate_lookup_does_not_log_cji(self, caplog):
        client = JNETClient()
        with caplog.at_level(logging.DEBUG):
            result, _ = await client.plate_lookup("TEST123", "PA")

        log_text = caplog.text.lower()
        # CJI fields should not appear in logs
        assert "john" not in log_text
        assert "doe" not in log_text
        assert "123 main st" not in log_text
        assert "1hgbh41jxmn109186" not in log_text


class TestSSLContext:
    """Test mTLS SSL context construction."""

    def test_build_ssl_context_enforces_tls_12(self):
        import ssl
        with patch("app.services.jnet.client.jnet_settings") as mock_cfg:
            mock_cfg.jnet_ca_bundle_path = ""
            mock_cfg.jnet_client_cert_path = ""
            mock_cfg.jnet_client_key_path = ""
            ctx = _build_ssl_context()
            assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


class TestJNETError:
    """Test JNETError exception."""

    def test_jnet_error_attributes(self):
        err = JNETError("timeout", status_code=504)
        assert err.message == "timeout"
        assert err.status_code == 504
        assert str(err) == "timeout"
