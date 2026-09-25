"""Tests for JNET stealth feature gate — 404 for invisible features."""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import HTTPException

from app.services.jnet.dependencies import (
    get_effective_jnet_enabled,
    require_jnet_visible,
    require_cjis_admin_visible,
)
from app.models.jnet_authorized_user import JNETAuthorizedUser
from app.models.system_setting import SystemSetting


def _make_jnet_user(**overrides) -> JNETAuthorizedUser:
    defaults = {
        "id": uuid.uuid4(),
        "okta_sub": "test-sub",
        "email": "officer@moravian.edu",
        "full_name": "Test Officer",
        "role": "jnet_officer",
        "jnet_authorized": True,
    }
    defaults.update(overrides)
    user = MagicMock(spec=JNETAuthorizedUser)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _mock_db_returning(jnet_user=None, db_setting_value="true"):
    """Create a mock AsyncSession that returns the given JNET user and DB setting."""
    db = AsyncMock()

    async def _execute(query):
        result = MagicMock()
        query_str = str(query)
        if "system_settings" in query_str:
            result.scalar.return_value = db_setting_value
        else:
            result.scalars.return_value.first.return_value = jnet_user
        return result

    db.execute = _execute
    return db


def _mock_request():
    req = MagicMock()
    req.state = MagicMock()
    return req


def _mock_okta_user(sub="test-sub"):
    user = MagicMock()
    user.sub = sub
    return user


# ── get_effective_jnet_enabled ───────────────────────────────────────


class TestEffectiveJNETEnabled:
    @pytest.mark.asyncio
    async def test_false_when_env_disabled(self):
        db = _mock_db_returning(db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = False
            assert await get_effective_jnet_enabled(db) is False

    @pytest.mark.asyncio
    async def test_false_when_db_disabled(self):
        db = _mock_db_returning(db_setting_value="false")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            assert await get_effective_jnet_enabled(db) is False

    @pytest.mark.asyncio
    async def test_true_when_both_enabled(self):
        db = _mock_db_returning(db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            assert await get_effective_jnet_enabled(db) is True


# ── require_jnet_visible ─────────────────────────────────────────────


class TestRequireJNETVisible:
    @pytest.mark.asyncio
    async def test_404_when_jnet_disabled(self):
        db = _mock_db_returning(db_setting_value="false")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = False
            with pytest.raises(HTTPException) as exc:
                await require_jnet_visible(
                    _mock_request(), _mock_okta_user(), db
                )
            assert exc.value.status_code == 404
            assert exc.value.detail == "Not found"

    @pytest.mark.asyncio
    async def test_404_when_user_not_in_table(self):
        db = _mock_db_returning(jnet_user=None, db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            with pytest.raises(HTTPException) as exc:
                await require_jnet_visible(
                    _mock_request(), _mock_okta_user(), db
                )
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_user_not_authorized(self):
        user = _make_jnet_user(jnet_authorized=False)
        db = _mock_db_returning(jnet_user=user, db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            with pytest.raises(HTTPException) as exc:
                await require_jnet_visible(
                    _mock_request(), _mock_okta_user(), db
                )
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_user_when_authorized(self):
        jnet_user = _make_jnet_user()
        db = _mock_db_returning(jnet_user=jnet_user, db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            result = await require_jnet_visible(
                _mock_request(), _mock_okta_user(), db
            )
            assert result == jnet_user


# ── require_cjis_admin_visible ───────────────────────────────────────


class TestRequireCJISAdminVisible:
    @pytest.mark.asyncio
    async def test_404_for_jnet_officer(self):
        """jnet_officer should not see admin endpoints."""
        user = _make_jnet_user(role="jnet_officer")
        db = _mock_db_returning(jnet_user=user, db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            with pytest.raises(HTTPException) as exc:
                await require_cjis_admin_visible(
                    _mock_request(), _mock_okta_user(), db
                )
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_admin_user(self):
        user = _make_jnet_user(role="cjis_admin")
        db = _mock_db_returning(jnet_user=user, db_setting_value="true")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            result = await require_cjis_admin_visible(
                _mock_request(), _mock_okta_user(), db
            )
            assert result == user

    @pytest.mark.asyncio
    async def test_404_when_system_disabled(self):
        user = _make_jnet_user(role="cjis_admin")
        db = _mock_db_returning(jnet_user=user, db_setting_value="false")
        with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
            cfg.jnet_enabled = True
            with pytest.raises(HTTPException) as exc:
                await require_cjis_admin_visible(
                    _mock_request(), _mock_okta_user(), db
                )
            assert exc.value.status_code == 404


# ── Stealth response identity ───────────────────────────────────────


class TestStealthResponseIdentity:
    """All 404 responses must be identical to prevent information leakage."""

    @pytest.mark.asyncio
    async def test_all_404s_have_same_detail(self):
        """Regardless of reason, the 404 detail must always be 'Not found'."""
        db_disabled = _mock_db_returning(db_setting_value="false")
        db_no_user = _mock_db_returning(jnet_user=None, db_setting_value="true")
        db_revoked = _mock_db_returning(
            jnet_user=_make_jnet_user(jnet_authorized=False),
            db_setting_value="true",
        )

        details = []
        for db in [db_disabled, db_no_user, db_revoked]:
            with patch("app.services.jnet.dependencies.jnet_settings") as cfg:
                cfg.jnet_enabled = True if db != db_disabled else False
                try:
                    await require_jnet_visible(
                        _mock_request(), _mock_okta_user(), db
                    )
                except HTTPException as e:
                    details.append(e.detail)

        assert all(d == "Not found" for d in details)
        assert len(details) == 3
