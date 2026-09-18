"""
Image upload router — avatars and business logos.

Both were previously uploaded directly from the browser straight to Supabase
Storage (public buckets, no server in the path at all), trusting only the
client-supplied filename/Content-Type. Since the buckets are public and serve
content inline with no CSP anywhere in the app, an attacker could set
Content-Type: image/svg+xml (or text/html) on arbitrary bytes and get back a
permanent public URL that executes script when opened directly (outside an
<img> tag) — a stored-XSS-via-file-upload vector (CASA 5.2.1).

These endpoints replace that direct-upload path: the file is decoded with
Pillow (Image.open + verify(), which rejects anything that isn't a genuine
raster image — including SVG/HTML/script payloads) and only PNG/JPEG/WEBP/GIF
are accepted. The stored Content-Type is derived from the verified image
format, never the client-supplied header, so a spoofed header can't smuggle
a dangerous MIME type onto the public object.
"""

import io
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.auth import get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.schemas.uploads import UploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

_FORMAT_TO_CONTENT_TYPE = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/gif", "gif"),
}


def _validate_and_normalize_image(raw: bytes) -> tuple[bytes, str, str]:
    """Verify `raw` is a genuine raster image and return (bytes, content_type, ext).

    Rejects anything Pillow can't decode as one of PNG/JPEG/WEBP/GIF — this is
    a content-based check, not a filename/header check, so a renamed .svg or
    .html file fails here regardless of what extension or Content-Type header
    it was uploaded with.
    """
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="Image exceeds the 5MB size limit")

    try:
        # verify() checks integrity but leaves the image object unusable
        # afterward per Pillow's docs — reopen to read the format safely.
        Image.open(io.BytesIO(raw)).verify()
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=422, detail="File is not a valid image")

    mapped = _FORMAT_TO_CONTENT_TYPE.get(image.format or "")
    if not mapped:
        raise HTTPException(
            status_code=422,
            detail="Only PNG, JPEG, WEBP, or GIF images are allowed",
        )
    content_type, ext = mapped
    return raw, content_type, ext


@router.post("/avatar", response_model=UploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    raw = await file.read()
    image_bytes, content_type, ext = _validate_and_normalize_image(raw)

    storage_path = f"{user_id}/avatar.{ext}"
    try:
        supabase_admin.storage.from_("avatars").upload(
            storage_path,
            image_bytes,
            {"content-type": content_type, "upsert": "true"},
        )
    except Exception as e:
        logger.error("Avatar storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to upload avatar")

    public_url = supabase_admin.storage.from_("avatars").get_public_url(storage_path)
    # Cache-bust so the new image shows immediately even though the path is stable.
    public_url = f"{public_url}?v={uuid.uuid4().hex[:8]}"

    supabase_admin.table("profiles").update({"avatar_url": public_url}).eq("id", user_id).execute()

    return UploadResponse(url=public_url)


@router.post("/logo", response_model=UploadResponse)
async def upload_logo(
    business_id: str = Form(...),
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    role = verify_business_access(user_id, business_id)
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Only super admins can upload a business logo")

    raw = await file.read()
    image_bytes, content_type, ext = _validate_and_normalize_image(raw)

    storage_path = f"{business_id}/logo.{ext}"
    try:
        supabase_admin.storage.from_("logos").upload(
            storage_path,
            image_bytes,
            {"content-type": content_type, "upsert": "true"},
        )
    except Exception as e:
        logger.error("Logo storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to upload logo")

    public_url = supabase_admin.storage.from_("logos").get_public_url(storage_path)
    public_url = f"{public_url}?v={uuid.uuid4().hex[:8]}"

    supabase_admin.table("businesses").update({"logo_url": public_url}).eq("id", business_id).execute()

    return UploadResponse(url=public_url)
