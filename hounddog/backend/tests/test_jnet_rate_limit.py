"""Tests for JNET rate limiting — 10 queries per minute per user."""

import pytest
from unittest.mock import patch

from fastapi import HTTPException

from app.services.jnet.middleware import _check_rate_limit, _rate_limit_windows


class TestRateLimit:
    def setup_method(self):
        _rate_limit_windows.clear()

    def test_first_query_allowed(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 10
            _check_rate_limit("user-a")

    def test_under_limit_allowed(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 10
            for _ in range(9):
                _check_rate_limit("user-b")

    def test_at_limit_raises_429(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 5
            for _ in range(5):
                _check_rate_limit("user-c")
            with pytest.raises(HTTPException) as exc:
                _check_rate_limit("user-c")
            assert exc.value.status_code == 429
            assert "rate limit" in exc.value.detail.lower()

    def test_different_users_independent(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 2
            _check_rate_limit("user-d")
            _check_rate_limit("user-d")
            # user-d is at limit, but user-e should be fine
            _check_rate_limit("user-e")

    def test_rate_limit_message_includes_limit(self):
        with patch("app.services.jnet.middleware.jnet_settings") as cfg:
            cfg.jnet_max_queries_per_minute = 3
            for _ in range(3):
                _check_rate_limit("user-f")
            with pytest.raises(HTTPException) as exc:
                _check_rate_limit("user-f")
            assert "3" in exc.value.detail
