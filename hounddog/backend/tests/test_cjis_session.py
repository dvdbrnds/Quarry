"""Tests for CJIS session management — 30-minute timeout, re-auth required."""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from fastapi import HTTPException

from app.services.jnet.middleware import _check_session_timeout
from app.models.jnet_authorized_user import JNETAuthorizedUser


def _make_user(**overrides) -> JNETAuthorizedUser:
    defaults = {
        "id": uuid.uuid4(),
        "okta_sub": "test",
        "email": "test@moravian.edu",
        "jnet_last_activity": None,
    }
    defaults.update(overrides)
    user = MagicMock(spec=JNETAuthorizedUser)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


class TestSessionTimeout:
    """CJIS requires 30-minute inactivity timeout for JNET sessions."""

    def test_first_query_allowed(self):
        """First JNET query of a session should be allowed."""
        user = _make_user(jnet_last_activity=None)
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            _check_session_timeout(user)

    def test_recent_activity_allowed(self):
        """Activity within 30 minutes is allowed."""
        user = _make_user(
            jnet_last_activity=datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            _check_session_timeout(user)

    def test_exactly_at_boundary(self):
        """Activity at exactly 30 minutes should be expired."""
        user = _make_user(
            jnet_last_activity=datetime.now(timezone.utc) - timedelta(minutes=30, seconds=1)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            with pytest.raises(HTTPException) as exc:
                _check_session_timeout(user)
            assert exc.value.status_code == 401

    def test_expired_returns_cjis_session_expired_detail(self):
        """Expired session must return 'cjis_session_expired' detail for iOS handling."""
        user = _make_user(
            jnet_last_activity=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            with pytest.raises(HTTPException) as exc:
                _check_session_timeout(user)
            assert exc.value.detail == "cjis_session_expired"

    def test_configurable_timeout(self):
        """Timeout should respect configuration."""
        user = _make_user(
            jnet_last_activity=datetime.now(timezone.utc) - timedelta(minutes=20)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 15
            with pytest.raises(HTTPException):
                _check_session_timeout(user)

    def test_naive_datetime_handled(self):
        """Should handle timezone-naive datetimes from DB."""
        user = _make_user(
            jnet_last_activity=datetime.utcnow() - timedelta(minutes=5)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            _check_session_timeout(user)
