"""Tests for CJIS access control — 403 for unauthorized, expired training, missing background check."""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import HTTPException

from app.services.jnet.middleware import (
    _check_background_check,
    _check_training,
    _check_session_timeout,
    _check_rate_limit,
    _check_jnet_enabled,
)
from app.models.jnet_authorized_user import JNETAuthorizedUser


def _make_jnet_user(**overrides) -> JNETAuthorizedUser:
    """Create a mock JNETAuthorizedUser for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "okta_sub": "test-sub",
        "email": "officer@moravian.edu",
        "full_name": "Test Officer",
        "role": "jnet_officer",
        "jnet_authorized": True,
        "jnet_background_check_date": datetime.now(timezone.utc) - timedelta(days=30),
        "jnet_training_completed_at": datetime.now(timezone.utc) - timedelta(days=30),
        "jnet_last_activity": datetime.now(timezone.utc) - timedelta(minutes=5),
    }
    defaults.update(overrides)
    user = MagicMock(spec=JNETAuthorizedUser)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


class TestJNETEnabled:
    def test_raises_503_when_disabled(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_enabled = False
            with pytest.raises(HTTPException) as exc:
                _check_jnet_enabled()
            assert exc.value.status_code == 503


class TestBackgroundCheck:
    def test_passes_with_valid_date(self):
        user = _make_jnet_user()
        _check_background_check(user)  # should not raise

    def test_raises_403_when_missing(self):
        user = _make_jnet_user(jnet_background_check_date=None)
        with pytest.raises(HTTPException) as exc:
            _check_background_check(user)
        assert exc.value.status_code == 403
        assert "background check" in exc.value.detail.lower()


class TestTraining:
    def test_passes_with_current_training(self):
        user = _make_jnet_user(
            jnet_training_completed_at=datetime.now(timezone.utc) - timedelta(days=30)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_training_validity_days = 365
            _check_training(user)

    def test_raises_403_when_not_completed(self):
        user = _make_jnet_user(jnet_training_completed_at=None)
        with pytest.raises(HTTPException) as exc:
            _check_training(user)
        assert exc.value.status_code == 403
        assert "training" in exc.value.detail.lower()

    def test_raises_403_when_expired(self):
        user = _make_jnet_user(
            jnet_training_completed_at=datetime.now(timezone.utc) - timedelta(days=400)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_training_validity_days = 365
            with pytest.raises(HTTPException) as exc:
                _check_training(user)
            assert exc.value.status_code == 403
            assert "expired" in exc.value.detail.lower()


class TestSessionTimeout:
    def test_passes_with_recent_activity(self):
        user = _make_jnet_user(
            jnet_last_activity=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            _check_session_timeout(user)

    def test_passes_on_first_query(self):
        user = _make_jnet_user(jnet_last_activity=None)
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            _check_session_timeout(user)

    def test_raises_401_when_expired(self):
        user = _make_jnet_user(
            jnet_last_activity=datetime.now(timezone.utc) - timedelta(minutes=35)
        )
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_session_timeout_minutes = 30
            with pytest.raises(HTTPException) as exc:
                _check_session_timeout(user)
            assert exc.value.status_code == 401
            assert "cjis_session_expired" in exc.value.detail


class TestRateLimit:
    def test_allows_under_limit(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 10
            # Reset rate limiter
            from app.services.jnet.middleware import _rate_limit_windows
            _rate_limit_windows.clear()
            _check_rate_limit("test-sub")  # should not raise

    def test_raises_429_over_limit(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 2
            from app.services.jnet.middleware import _rate_limit_windows
            _rate_limit_windows.clear()
            _check_rate_limit("rate-test")
            _check_rate_limit("rate-test")
            with pytest.raises(HTTPException) as exc:
                _check_rate_limit("rate-test")
            assert exc.value.status_code == 429
