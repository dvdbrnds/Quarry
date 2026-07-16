import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import require_role
from ..config import settings
from ..database import get_db
from ..models.branding_settings import BrandingSettings
from ..services.email import invalidate_branding_cache

admin_router = APIRouter(dependencies=[Depends(require_role("admin"))])
public_router = APIRouter()

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}
_MAX_SIZE = 5 * 1024 * 1024
_MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg",
             "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico"}


async def _get_or_create(db: AsyncSession) -> BrandingSettings:
    result = await db.execute(select(BrandingSettings).where(BrandingSettings.id == 1))
    row = result.scalar()
    if not row:
        row = BrandingSettings(id=1)
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return row


def _etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


@public_router.get("")
async def get_branding(db: AsyncSession = Depends(get_db)):
    bs = await _get_or_create(db)
    logo_url = "/api/branding/logo" if bs.logo_data else None
    favicon_url = "/api/branding/favicon" if bs.favicon_data else "/favicon.png"
    return {
        "brand_name": bs.brand_name if bs.brand_name is not None else settings.brand_name,
        "primary_color": bs.primary_color or settings.brand_primary_color,
        "accent_color": bs.accent_color or settings.brand_accent_color,
        "logo_url": logo_url,
        "favicon_url": favicon_url,
        "school_name": settings.school_name,
    }


@public_router.get("/logo")
async def serve_logo(db: AsyncSession = Depends(get_db)):
    bs = await _get_or_create(db)
    if not bs.logo_data:
        raise HTTPException(404, "No logo uploaded")
    etag = _etag(bs.logo_data)
    return Response(
        content=bs.logo_data,
        media_type=bs.logo_mime or "image/png",
        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"},
    )


@public_router.get("/favicon")
async def serve_favicon(db: AsyncSession = Depends(get_db)):
    bs = await _get_or_create(db)
    if not bs.favicon_data:
        raise HTTPException(404, "No favicon uploaded")
    etag = _etag(bs.favicon_data)
    return Response(
        content=bs.favicon_data,
        media_type=bs.favicon_mime or "image/png",
        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"},
    )


class BrandIdentityUpdate(BaseModel):
    brand_name: str
    primary_color: str
    accent_color: str


@admin_router.put("")
async def update_brand_identity(body: BrandIdentityUpdate, db: AsyncSession = Depends(get_db)):
    bs = await _get_or_create(db)
    bs.brand_name = body.brand_name
    bs.primary_color = body.primary_color
    bs.accent_color = body.accent_color
    await db.flush()
    invalidate_branding_cache()
    return {"ok": True}


@admin_router.post("/reset")
async def reset_branding(db: AsyncSession = Depends(get_db)):
    bs = await _get_or_create(db)
    bs.brand_name = "Quarry"
    bs.primary_color = "#1a2744"
    bs.accent_color = "#c9a84c"
    bs.logo_data = None
    bs.logo_mime = None
    bs.favicon_data = None
    bs.favicon_mime = None
    await db.flush()
    invalidate_branding_cache()
    return {"ok": True}


@admin_router.post("/logo")
async def upload_logo(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Invalid file type. Allowed: {', '.join(_ALLOWED_TYPES)}")
    contents = await file.read()
    if len(contents) > _MAX_SIZE:
        raise HTTPException(413, "File too large. Maximum size is 5MB.")
    bs = await _get_or_create(db)
    bs.logo_data = contents
    bs.logo_mime = file.content_type
    await db.flush()
    invalidate_branding_cache()
    return {"logo_url": "/api/branding/logo"}


@admin_router.post("/favicon")
async def upload_favicon(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Invalid file type. Allowed: {', '.join(_ALLOWED_TYPES)}")
    contents = await file.read()
    if len(contents) > _MAX_SIZE:
        raise HTTPException(413, "File too large. Maximum size is 5MB.")
    bs = await _get_or_create(db)
    bs.favicon_data = contents
    bs.favicon_mime = file.content_type
    await db.flush()
    invalidate_branding_cache()
    return {"favicon_url": "/api/branding/favicon"}
