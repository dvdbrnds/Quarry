import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..auth.okta import require_role
from ..config import settings

admin_router = APIRouter(dependencies=[Depends(require_role("admin"))])
public_router = APIRouter()

_UPLOAD_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "branding")
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}
_MAX_SIZE = 5 * 1024 * 1024


@public_router.get("")
async def get_branding():
    logo_url = f"/uploads/{settings.brand_logo_path}" if settings.brand_logo_path else None
    favicon_url = f"/uploads/{settings.brand_favicon_path}" if settings.brand_favicon_path else "/favicon.png"
    return {
        "brand_name": settings.brand_name,
        "primary_color": settings.brand_primary_color,
        "accent_color": settings.brand_accent_color,
        "logo_url": logo_url,
        "favicon_url": favicon_url,
        "school_name": settings.school_name,
    }


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
    return {"logo_url": f"/uploads/{rel_path}"}


@admin_router.post("/favicon")
async def upload_favicon(file: UploadFile = File(...)):
    rel_path = await _save_upload(file, "favicon")
    settings.brand_favicon_path = rel_path
    return {"favicon_url": f"/uploads/{rel_path}"}
