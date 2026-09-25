"""Tests for JNET settings endpoint and system status computation."""

import pytest
from app.routers.jnet_settings import _compute_system_status


class TestComputeSystemStatus:
    def test_disabled_when_env_off(self):
        assert _compute_system_status(
            env_enabled=False, db_enabled=True,
            base_url="https://ws.jnet.pa.gov",
            cert_path="/certs/jnet.pem", ori="PA0390100",
            has_live_query=True,
        ) == "disabled"

    def test_disabled_when_db_off(self):
        assert _compute_system_status(
            env_enabled=True, db_enabled=False,
            base_url="https://ws.jnet.pa.gov",
            cert_path="/certs/jnet.pem", ori="PA0390100",
            has_live_query=True,
        ) == "disabled"

    def test_mock_mode_when_no_base_url(self):
        assert _compute_system_status(
            env_enabled=True, db_enabled=True,
            base_url="", cert_path="", ori="",
            has_live_query=False,
        ) == "mock_mode"

    def test_misconfigured_when_no_cert(self):
        assert _compute_system_status(
            env_enabled=True, db_enabled=True,
            base_url="https://ws.jnet.pa.gov",
            cert_path="", ori="PA0390100",
            has_live_query=False,
        ) == "misconfigured"

    def test_misconfigured_when_no_ori(self):
        assert _compute_system_status(
            env_enabled=True, db_enabled=True,
            base_url="https://ws.jnet.pa.gov",
            cert_path="/certs/jnet.pem", ori="",
            has_live_query=False,
        ) == "misconfigured"

    def test_ready_when_all_configured_no_queries(self):
        assert _compute_system_status(
            env_enabled=True, db_enabled=True,
            base_url="https://ws.jnet.pa.gov",
            cert_path="/certs/jnet.pem", ori="PA0390100",
            has_live_query=False,
        ) == "ready"

    def test_live_when_has_queries(self):
        assert _compute_system_status(
            env_enabled=True, db_enabled=True,
            base_url="https://ws.jnet.pa.gov",
            cert_path="/certs/jnet.pem", ori="PA0390100",
            has_live_query=True,
        ) == "live"
