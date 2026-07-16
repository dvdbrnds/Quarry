import json
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..auth.okta import require_role
from ..config import settings

admin_router = APIRouter(dependencies=[Depends(require_role("admin"))])
public_router = APIRouter()

_UPLOAD_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "branding")
_STATE_FILE = os.path.join(_UPLOAD_BASE, "branding.json")
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}
_MAX_SIZE = 5 * 1024 * 1024


def _load_state() -> dict:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    os.makedirs(_UPLOAD_BASE, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f)


def _resolve_upload_url(rel_path: str | None) -> str | None:
    """Return a URL only if the file actually exists on disk."""
    if not rel_path:
        return None
    abs_path = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", rel_path)
    if os.path.isfile(abs_path):
        return f"/uploads/{rel_path}"
    return None


def _logo_path() -> str:
    return _load_state().get("logo_path", "") or settings.brand_logo_path


def _favicon_path() -> str:
    return _load_state().get("favicon_path", "") or settings.brand_favicon_path


@public_router.get("")
async def get_branding():
    state = _load_state()
    logo_url = _resolve_upload_url(_logo_path())
    favicon_url = _resolve_upload_url(_favicon_path()) or "/favicon.png"
    return {
        "brand_name": state.get("brand_name") or settings.brand_name,
        "primary_color": state.get("primary_color") or settings.brand_primary_color,
        "accent_color": state.get("accent_color") or settings.brand_accent_color,
        "logo_url": logo_url,
        "favicon_url": favicon_url,
        "school_name": settings.school_name,
    }


class BrandIdentityUpdate(BaseModel):
    brand_name: str
    primary_color: str
    accent_color: str


@admin_router.put("")
async def update_brand_identity(body: BrandIdentityUpdate):
    settings.brand_name = body.brand_name
    settings.brand_primary_color = body.primary_color
    settings.brand_accent_color = body.accent_color
    state = _load_state()
    state["brand_name"] = body.brand_name
    state["primary_color"] = body.primary_color
    state["accent_color"] = body.accent_color
    _save_state(state)
    return {"ok": True}


async def _save_upload(file: UploadFile, filename: str) -> str:
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Invalid file type. Allowed: {', '.join(_ALLOWED_TYPES)}")
    contents = await file.read()
    if len(contents) > _MAX_SIZE:
        raise HTTPException(413, "File too large. Maximum size is 5MB.")
    os.makedirs(_UPLOAD_BASE, exist_ok=True)
    ext = os.path.splitext(file.filename or filename)[1] or ".png"
    dest = os.path.join(_UPLOAD_BASE, f"{filename}{ext}")
    with open(dest, "wb") as f:
        f.write(contents)
    return f"branding/{filename}{ext}"


@admin_router.post("/logo")
async def upload_logo(file: UploadFile = File(...)):
    rel_path = await _save_upload(file, "logo")
    settings.brand_logo_path = rel_path
    state = _load_state()
    state["logo_path"] = rel_path
    _save_state(state)
    return {"logo_url": f"/uploads/{rel_path}"}


@admin_router.post("/favicon")
async def upload_favicon(file: UploadFile = File(...)):
    rel_path = await _save_upload(file, "favicon")
    settings.brand_favicon_path = rel_path
    state = _load_state()
    state["favicon_path"] = rel_path
    _save_state(state)
    return {"favicon_url": f"/uploads/{rel_path}"}
