from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from PIL import Image

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.marketing import (
    MarketingIntegrationStatusResponse,
    MarketingIntegrationsStatusResponse,
)

X_SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access", "media.write"]
INSTAGRAM_SCOPES = [
    "instagram_business_basic",
    "instagram_business_content_publish",
]
MARKETING_ASSETS_BUCKET = "marketing-assets"
SIGNED_URL_TTL_SECONDS = 60 * 60 * 6
INSTAGRAM_API_VERSION = "v25.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode_oauth_state(payload: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return encoded.rstrip("=")


def _decode_oauth_state(state: str) -> dict[str, Any]:
    try:
        return json.loads(state)
    except json.JSONDecodeError:
        pass
    try:
        padded = state + ("=" * (-len(state) % 4))
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
        return json.loads(decoded)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.") from exc


def _is_local_origin(origin: str | None) -> bool:
    if not origin:
        return False
    host = urlparse(origin).hostname or ""
    return host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".localhost")


def _redirect_uri_for_provider(provider: str, origin: str | None) -> str:
    if provider == "x":
        local_uri = settings.marketing_x_redirect_uri_local or settings.marketing_x_redirect_uri
        production_uri = settings.marketing_x_redirect_uri_production or settings.marketing_x_redirect_uri
    else:
        local_uri = (
            settings.marketing_instagram_redirect_uri_local
            or settings.marketing_meta_redirect_uri_local
            or settings.marketing_meta_redirect_uri
        )
        production_uri = (
            settings.marketing_instagram_redirect_uri_production
            or settings.marketing_meta_redirect_uri_production
            or settings.marketing_meta_redirect_uri
        )
    return local_uri if _is_local_origin(origin) else production_uri


def _instagram_app_id() -> str:
    return settings.marketing_instagram_app_id


def _instagram_app_secret() -> str:
    return settings.marketing_instagram_app_secret


def _token_fernet() -> Fernet:
    raw_key = settings.marketing_token_encryption_key
    if not raw_key:
        raise HTTPException(status_code=501, detail="Marketing token encryption is not configured.")
    try:
        return Fernet(raw_key.encode())
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode()).digest())
        return Fernet(derived)


def _encrypt_token(value: str | None) -> str | None:
    if not value:
        return None
    return _token_fernet().encrypt(value.encode()).decode()


def _decrypt_token(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _token_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail="Stored marketing integration token could not be decrypted.") from exc


def _integration_row_to_status(provider: str, row: dict[str, Any] | None) -> MarketingIntegrationStatusResponse:
    if not row:
        return MarketingIntegrationStatusResponse(provider=provider, connected=False)
    return MarketingIntegrationStatusResponse(
        provider=provider,
        connected=bool(row.get("is_connected")),
        account_id=row.get("provider_account_id"),
        account_name=row.get("provider_account_name"),
        scopes=row.get("scopes") or [],
        last_error=row.get("last_error"),
        token_expires_at=row.get("token_expires_at"),
    )


def _get_integration_row(business_id: str, provider: str) -> dict[str, Any] | None:
    result = (
        supabase_admin.table("marketing_platform_integrations")
        .select("*")
        .eq("business_id", business_id)
        .eq("provider", provider)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _get_single(table: str, row_id: str, business_id: str) -> dict[str, Any]:
    result = (
        supabase_admin.table(table)
        .select("*")
        .eq("id", row_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"{table} row not found")
    return result.data[0]


def _signed_asset_url(asset: dict[str, Any]) -> str | None:
    bucket = asset.get("storage_bucket")
    path = asset.get("storage_path")
    if not bucket or not path:
        return None
    signed = supabase_admin.storage.from_(bucket).create_signed_url(path, SIGNED_URL_TTL_SECONDS)
    return signed.get("signedURL") or signed.get("signed_url") or signed.get("signedUrl")


def _download_asset_bytes(asset: dict[str, Any]) -> bytes:
    bucket = asset.get("storage_bucket") or MARKETING_ASSETS_BUCKET
    path = asset.get("storage_path")
    if not path:
        raise HTTPException(status_code=422, detail="Selected marketing asset does not have generated media.")
    data = supabase_admin.storage.from_(bucket).download(path)
    if isinstance(data, bytes):
        return data
    if hasattr(data, "content"):
        return data.content
    raise HTTPException(status_code=500, detail="Failed to download generated marketing asset.")


def _instagram_alt_text(asset: dict[str, Any]) -> str:
    title = str(asset.get("title") or "AI generated marketing image")
    prompt = str(asset.get("prompt") or "").strip()
    caption = str(asset.get("caption") or "").strip()
    details = prompt or caption
    alt_text = f"{title}. {details}" if details else title
    return alt_text[:1000]


def _convert_image_to_jpeg(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=92, optimize=True)
        return output.getvalue()


def _instagram_jpeg_signed_url(business_id: str, asset: dict[str, Any]) -> str:
    original_bytes = _download_asset_bytes(asset)
    jpeg_bytes = _convert_image_to_jpeg(original_bytes)
    storage_path = f"{business_id}/instagram-publish/{asset['id']}.jpg"
    try:
        supabase_admin.storage.from_(MARKETING_ASSETS_BUCKET).remove([storage_path])
    except Exception:
        pass
    supabase_admin.storage.from_(MARKETING_ASSETS_BUCKET).upload(
        storage_path,
        jpeg_bytes,
        {"content-type": "image/jpeg"},
    )
    return _signed_asset_url({"storage_bucket": MARKETING_ASSETS_BUCKET, "storage_path": storage_path}) or ""


def _update_scheduled_post(business_id: str, post_id: str, values: dict[str, Any]) -> None:
    supabase_admin.table("marketing_scheduled_posts").update(values).eq("id", post_id).eq("business_id", business_id).execute()


def get_marketing_integrations_status(business_id: str) -> MarketingIntegrationsStatusResponse:
    rows = (
        supabase_admin.table("marketing_platform_integrations")
        .select("*")
        .eq("business_id", business_id)
        .execute()
        .data
        or []
    )
    by_provider = {row["provider"]: row for row in rows}
    return MarketingIntegrationsStatusResponse(
        integrations=[
            _integration_row_to_status("instagram", by_provider.get("instagram")),
            _integration_row_to_status("x", by_provider.get("x")),
        ]
    )


def _upsert_integration(
    *,
    business_id: str,
    user_id: str,
    provider: str,
    account_id: str | None,
    account_name: str | None,
    access_token: str,
    refresh_token: str | None,
    expires_at: str | None,
    scopes: list[str],
    provider_page_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> MarketingIntegrationStatusResponse:
    row = {
        "business_id": business_id,
        "connected_by": user_id,
        "provider": provider,
        "provider_account_id": account_id,
        "provider_account_name": account_name,
        "provider_page_id": provider_page_id,
        "encrypted_access_token": _encrypt_token(access_token),
        "encrypted_refresh_token": _encrypt_token(refresh_token),
        "token_expires_at": expires_at,
        "scopes": scopes,
        "is_connected": True,
        "last_error": None,
        "metadata": metadata or {},
    }
    existing = _get_integration_row(business_id, provider)
    if existing:
        result = (
            supabase_admin.table("marketing_platform_integrations")
            .update(row)
            .eq("id", existing["id"])
            .eq("business_id", business_id)
            .execute()
        )
    else:
        result = supabase_admin.table("marketing_platform_integrations").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail=f"Failed to save {provider} integration.")
    return _integration_row_to_status(provider, result.data[0])


def build_x_auth_url(business_id: str, user_id: str, return_to: str, origin: str | None = None) -> str:
    if not settings.marketing_x_client_id:
        raise HTTPException(status_code=501, detail="X integration is not configured.")
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    redirect_uri = _redirect_uri_for_provider("x", origin)
    state = _encode_oauth_state(
        {
            "provider": "x",
            "business_id": business_id,
            "user_id": user_id,
            "return_to": return_to,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
    )
    params = {
        "response_type": "code",
        "client_id": settings.marketing_x_client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(X_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"https://x.com/i/oauth2/authorize?{urlencode(params)}"


def build_instagram_auth_url(business_id: str, user_id: str, return_to: str, origin: str | None = None) -> str:
    instagram_app_id = _instagram_app_id()
    if not instagram_app_id:
        raise HTTPException(status_code=501, detail="Instagram integration is not configured.")
    redirect_uri = _redirect_uri_for_provider("instagram", origin)
    state = _encode_oauth_state(
        {
            "provider": "instagram",
            "business_id": business_id,
            "user_id": user_id,
            "return_to": return_to,
            "redirect_uri": redirect_uri,
        }
    )
    params = {
        "client_id": instagram_app_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(INSTAGRAM_SCOPES),
        "response_type": "code",
        "state": state,
    }
    return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"


async def complete_x_oauth(code: str, state: str, business_id: str) -> MarketingIntegrationStatusResponse:
    parsed = _decode_oauth_state(state)
    if parsed.get("provider") != "x" or parsed.get("business_id") != business_id:
        raise HTTPException(status_code=400, detail="Invalid X OAuth state.")
    auth_header = None
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": parsed.get("redirect_uri") or settings.marketing_x_redirect_uri,
        "code_verifier": parsed["code_verifier"],
        "client_id": settings.marketing_x_client_id,
    }
    if settings.marketing_x_client_secret:
        encoded = base64.b64encode(f"{settings.marketing_x_client_id}:{settings.marketing_x_client_secret}".encode()).decode()
        auth_header = {"Authorization": f"Basic {encoded}"}
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(
            "https://api.x.com/2/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", **(auth_header or {})},
        )
        if token_response.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"X token exchange failed: {token_response.text}")
        token_data = token_response.json()
        access_token = token_data["access_token"]
        user_response = await client.get("https://api.x.com/2/users/me", headers={"Authorization": f"Bearer {access_token}"})
        user_data = user_response.json() if user_response.status_code < 400 else {}
    expires_at = None
    if token_data.get("expires_in"):
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))).isoformat()
    user = user_data.get("data") or {}
    scopes = str(token_data.get("scope") or " ".join(X_SCOPES)).split()
    return _upsert_integration(
        business_id=business_id,
        user_id=parsed["user_id"],
        provider="x",
        account_id=user.get("id"),
        account_name=user.get("username") or user.get("name"),
        access_token=access_token,
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
        scopes=scopes,
        metadata={"raw_user": user},
    )


async def complete_instagram_oauth(code: str, state: str, business_id: str) -> MarketingIntegrationStatusResponse:
    parsed = _decode_oauth_state(state)
    if parsed.get("provider") != "instagram" or parsed.get("business_id") != business_id:
        raise HTTPException(status_code=400, detail="Invalid Instagram OAuth state.")
    instagram_app_id = _instagram_app_id()
    instagram_app_secret = _instagram_app_secret()
    if not instagram_app_id or not instagram_app_secret:
        raise HTTPException(status_code=501, detail="Instagram integration is not configured.")
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": instagram_app_id,
                "client_secret": instagram_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": parsed.get("redirect_uri") or settings.marketing_meta_redirect_uri,
                "code": code,
            },
        )
        if token_response.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Instagram token exchange failed: {token_response.text}")
        token_data = token_response.json()
        access_token = token_data["access_token"]
        long_response = await client.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": instagram_app_secret,
                "access_token": access_token,
            },
        )
        if long_response.status_code < 400:
            token_data = long_response.json()
            access_token = token_data.get("access_token", access_token)
        profile_response = await client.get(
            f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/me",
            params={"fields": "user_id,username,account_type", "access_token": access_token},
        )
        if profile_response.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Instagram account lookup failed: {profile_response.text}")
        profile = profile_response.json()
    account_type = str(profile.get("account_type") or "").upper()
    if account_type and account_type not in {"BUSINESS", "CREATOR"}:
        raise HTTPException(status_code=400, detail="The selected Instagram account must be Business or Creator.")
    expires_at = None
    if token_data.get("expires_in"):
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))).isoformat()
    return _upsert_integration(
        business_id=business_id,
        user_id=parsed["user_id"],
        provider="instagram",
        account_id=str(profile.get("user_id") or profile.get("id") or token_data.get("user_id") or ""),
        account_name=profile.get("username"),
        provider_page_id=None,
        access_token=access_token,
        refresh_token=None,
        expires_at=expires_at,
        scopes=INSTAGRAM_SCOPES,
        metadata={"account_type": profile.get("account_type")},
    )


def disconnect_marketing_integration(business_id: str, provider: str) -> dict[str, bool]:
    supabase_admin.table("marketing_platform_integrations").delete().eq("business_id", business_id).eq("provider", provider).execute()
    return {"disconnected": True}


async def _refresh_x_access_token(business_id: str, row: dict[str, Any]) -> str:
    refresh_token = _decrypt_token(row.get("encrypted_refresh_token"))
    if not refresh_token:
        raise RuntimeError("X refresh token is missing. Reconnect X.")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.marketing_x_client_id,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if settings.marketing_x_client_secret:
        encoded = base64.b64encode(f"{settings.marketing_x_client_id}:{settings.marketing_x_client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.x.com/2/oauth2/token", data=data, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"X token refresh failed: {response.text}")
    token_data = response.json()
    expires_at = None
    if token_data.get("expires_in"):
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))).isoformat()
    supabase_admin.table("marketing_platform_integrations").update(
        {
            "encrypted_access_token": _encrypt_token(token_data["access_token"]),
            "encrypted_refresh_token": _encrypt_token(token_data.get("refresh_token", refresh_token)),
            "token_expires_at": expires_at,
            "last_error": None,
        }
    ).eq("id", row["id"]).eq("business_id", business_id).execute()
    return token_data["access_token"]


async def _refresh_instagram_access_token(business_id: str, row: dict[str, Any]) -> str:
    access_token = _decrypt_token(row.get("encrypted_access_token"))
    if not access_token:
        raise RuntimeError("Instagram access token is missing. Reconnect Instagram.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": access_token},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Instagram token refresh failed: {response.text}")
    token_data = response.json()
    expires_at = None
    if token_data.get("expires_in"):
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))).isoformat()
    supabase_admin.table("marketing_platform_integrations").update(
        {
            "encrypted_access_token": _encrypt_token(token_data.get("access_token", access_token)),
            "token_expires_at": expires_at,
            "last_error": None,
        }
    ).eq("id", row["id"]).eq("business_id", business_id).execute()
    return token_data.get("access_token", access_token)


async def _access_token_for_provider(business_id: str, provider: str) -> tuple[dict[str, Any], str]:
    row = _get_integration_row(business_id, provider)
    if not row or not row.get("is_connected"):
        raise RuntimeError(f"{provider} is not connected for this business.")
    token = _decrypt_token(row.get("encrypted_access_token"))
    if not token:
        raise RuntimeError(f"{provider} access token is missing. Reconnect {provider}.")
    if provider == "x" and row.get("token_expires_at"):
        expires_at = datetime.fromisoformat(str(row["token_expires_at"]).replace("Z", "+00:00"))
        if expires_at <= datetime.now(timezone.utc) + timedelta(minutes=2):
            token = await _refresh_x_access_token(business_id, row)
            row = _get_integration_row(business_id, provider) or row
    if provider == "instagram" and row.get("token_expires_at"):
        expires_at = datetime.fromisoformat(str(row["token_expires_at"]).replace("Z", "+00:00"))
        if expires_at <= datetime.now(timezone.utc) + timedelta(days=3):
            token = await _refresh_instagram_access_token(business_id, row)
            row = _get_integration_row(business_id, provider) or row
    return row, token


async def _publish_to_x(business_id: str, asset: dict[str, Any], caption: str) -> tuple[str, str]:
    row, access_token = await _access_token_for_provider(business_id, "x")
    media_bytes = _download_asset_bytes(asset)
    content_type = asset.get("content_type") or "image/png"
    async with httpx.AsyncClient(timeout=60) as client:
        upload_response = await client.post(
            "https://api.x.com/2/media/upload",
            headers={"Authorization": f"Bearer {access_token}"},
            data={"media_category": "tweet_image", "media_type": content_type},
            files={"media": (asset.get("storage_path") or "marketing-image.png", media_bytes, content_type)},
        )
        if upload_response.status_code >= 400:
            raise RuntimeError(f"X media upload failed: {upload_response.text}")
        upload_json = upload_response.json()
        media_id = (
            (upload_json.get("data") or {}).get("id")
            or upload_json.get("media_id_string")
            or str(upload_json.get("media_id") or "")
        )
        if not media_id:
            raise RuntimeError(f"X media upload returned no media id: {upload_json}")
        tweet_response = await client.post(
            "https://api.x.com/2/tweets",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"text": caption[:280], "media": {"media_ids": [media_id]}},
        )
        if tweet_response.status_code >= 400:
            raise RuntimeError(f"X post failed: {tweet_response.text}")
        tweet_json = tweet_response.json()
    tweet_id = (tweet_json.get("data") or {}).get("id") or ""
    return tweet_id, f"https://x.com/i/web/status/{tweet_id}" if tweet_id else ""


async def _assert_instagram_publish_capacity(client: httpx.AsyncClient, ig_user_id: str, access_token: str) -> None:
    response = await client.get(
        f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/{ig_user_id}/content_publishing_limit",
        params={"access_token": access_token},
    )
    if response.status_code >= 400:
        return
    payload = response.json()
    data = payload.get("data") or []
    if not data:
        return
    quota_usage = int(data[0].get("quota_usage") or 0)
    if quota_usage >= 100:
        raise RuntimeError("Instagram content publishing limit reached for this account.")


async def _wait_for_instagram_container_ready(client: httpx.AsyncClient, creation_id: str, access_token: str) -> None:
    last_status = "UNKNOWN"
    for attempt in range(3):
        response = await client.get(
            f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Instagram container status check failed: {response.text}")
        status_code = response.json().get("status_code")
        last_status = str(status_code or "UNKNOWN")
        if status_code in {"FINISHED", "PUBLISHED"}:
            return
        if status_code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media container is not publishable: {status_code}")
        if attempt < 2:
            await asyncio.sleep(5)
    raise RuntimeError(f"Instagram media container was not ready to publish: {last_status}")


def _instagram_asset_mode(asset: dict[str, Any], override: str | None = None) -> str:
    if override:
        return override.upper()
    content_type = str(asset.get("content_type") or "")
    format_ = str(asset.get("format") or "").lower()
    if format_ == "reel":
        return "REELS"
    if format_ == "story":
        return "STORIES"
    if format_ == "video" or content_type.startswith("video/"):
        return "VIDEO"
    return "IMAGE"


def _instagram_public_media_url(business_id: str, asset: dict[str, Any], mode: str) -> str:
    if mode in {"VIDEO", "REELS"}:
        return _signed_asset_url(asset) or ""
    if mode == "STORIES" and str(asset.get("content_type") or "").startswith("video/"):
        return _signed_asset_url(asset) or ""
    return _instagram_jpeg_signed_url(business_id, asset)


async def _create_instagram_media_container(
    client: httpx.AsyncClient,
    *,
    ig_user_id: str,
    access_token: str,
    asset: dict[str, Any],
    media_url: str,
    mode: str,
    caption: str | None,
    is_carousel_item: bool = False,
) -> str:
    payload: dict[str, Any] = {"is_ai_generated": True}
    if is_carousel_item:
        payload["is_carousel_item"] = True
    if mode in {"VIDEO", "REELS"}:
        payload["video_url"] = media_url
        payload["media_type"] = mode
    elif mode == "STORIES":
        if str(asset.get("content_type") or "").startswith("video/"):
            payload["video_url"] = media_url
        else:
            payload["image_url"] = media_url
            payload["alt_text"] = _instagram_alt_text(asset)
        payload["media_type"] = "STORIES"
    else:
        payload["image_url"] = media_url
        payload["alt_text"] = _instagram_alt_text(asset)
    if caption and mode != "STORIES" and not is_carousel_item:
        payload["caption"] = caption[:2200]
    response = await client.post(
        f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/{ig_user_id}/media",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Instagram media container failed: {response.text}")
    creation_id = response.json().get("id")
    if not creation_id:
        raise RuntimeError(f"Instagram media container returned no id: {response.text}")
    await _wait_for_instagram_container_ready(client, creation_id, access_token)
    return creation_id


async def _create_instagram_carousel_container(
    client: httpx.AsyncClient,
    *,
    ig_user_id: str,
    access_token: str,
    child_container_ids: list[str],
    caption: str,
) -> str:
    response = await client.post(
        f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/{ig_user_id}/media",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "media_type": "CAROUSEL",
            "children": ",".join(child_container_ids),
            "caption": caption[:2200],
            "is_ai_generated": True,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Instagram carousel container failed: {response.text}")
    creation_id = response.json().get("id")
    if not creation_id:
        raise RuntimeError(f"Instagram carousel container returned no id: {response.text}")
    await _wait_for_instagram_container_ready(client, creation_id, access_token)
    return creation_id


async def _publish_instagram_container(
    client: httpx.AsyncClient,
    *,
    ig_user_id: str,
    access_token: str,
    creation_id: str,
) -> tuple[str, str]:
    publish_response = await client.post(
        f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/{ig_user_id}/media_publish",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"creation_id": creation_id},
    )
    if publish_response.status_code >= 400:
        raise RuntimeError(f"Instagram publish failed: {publish_response.text}")
    published_id = publish_response.json().get("id") or creation_id
    permalink_response = await client.get(
        f"https://graph.instagram.com/{INSTAGRAM_API_VERSION}/{published_id}",
        params={"fields": "permalink", "access_token": access_token},
    )
    permalink = ""
    if permalink_response.status_code < 400:
        permalink = permalink_response.json().get("permalink") or ""
    return published_id, permalink


async def _publish_to_instagram(
    business_id: str,
    assets: list[dict[str, Any]],
    caption: str,
    media_type_override: str | None = None,
) -> tuple[str, str]:
    row, access_token = await _access_token_for_provider(business_id, "instagram")
    ig_user_id = row.get("provider_account_id")
    if not ig_user_id:
        raise RuntimeError("Instagram account id is missing. Reconnect Instagram.")
    if not assets:
        raise RuntimeError("No generated media asset selected for Instagram publishing.")
    async with httpx.AsyncClient(timeout=60) as client:
        await _assert_instagram_publish_capacity(client, ig_user_id, access_token)
        if len(assets) > 1:
            if len(assets) > 10:
                raise RuntimeError("Instagram carousel posts are limited to 10 media assets.")
            child_ids: list[str] = []
            for asset in assets:
                mode = _instagram_asset_mode(asset)
                if mode in {"REELS", "STORIES"}:
                    raise RuntimeError("Instagram carousel children can only be image or video assets.")
                media_url = _instagram_public_media_url(business_id, asset, mode)
                if not media_url:
                    raise RuntimeError("Generated media URL is unavailable for Instagram carousel publishing.")
                child_ids.append(
                    await _create_instagram_media_container(
                        client,
                        ig_user_id=ig_user_id,
                        access_token=access_token,
                        asset=asset,
                        media_url=media_url,
                        mode=mode,
                        caption=None,
                        is_carousel_item=True,
                    )
                )
            creation_id = await _create_instagram_carousel_container(
                client,
                ig_user_id=ig_user_id,
                access_token=access_token,
                child_container_ids=child_ids,
                caption=caption,
            )
            return await _publish_instagram_container(client, ig_user_id=ig_user_id, access_token=access_token, creation_id=creation_id)

        asset = assets[0]
        mode = _instagram_asset_mode(asset, media_type_override)
        media_url = _instagram_public_media_url(business_id, asset, mode)
        if not media_url:
            raise RuntimeError("Generated media URL is unavailable for Instagram publishing.")
        creation_id = await _create_instagram_media_container(
            client,
            ig_user_id=ig_user_id,
            access_token=access_token,
            asset=asset,
            media_url=media_url,
            mode=mode,
            caption=caption,
        )
        return await _publish_instagram_container(client, ig_user_id=ig_user_id, access_token=access_token, creation_id=creation_id)


async def publish_scheduled_post(business_id: str, scheduled_post_id: str) -> dict[str, Any]:
    post = _get_single("marketing_scheduled_posts", scheduled_post_id, business_id)
    asset = _get_single("marketing_assets", post["asset_id"], business_id)
    provider_post_ids = dict(post.get("provider_post_ids") or {})
    metadata = dict(post.get("metadata") or {})
    provider_post_urls = dict(metadata.get("provider_post_urls") or {})
    instagram_asset_ids = metadata.get("asset_ids") or [post["asset_id"]]
    instagram_assets = [asset]
    if isinstance(instagram_asset_ids, list) and len(instagram_asset_ids) > 1:
        rows = (
            supabase_admin.table("marketing_assets")
            .select("*")
            .eq("business_id", business_id)
            .in_("id", instagram_asset_ids[:10])
            .execute()
            .data
            or []
        )
        by_id = {row["id"]: row for row in rows}
        instagram_assets = [by_id[asset_id] for asset_id in instagram_asset_ids[:10] if asset_id in by_id]
    instagram_media_type = metadata.get("instagram_media_type")
    instagram_media_type = str(instagram_media_type).upper() if instagram_media_type else None
    errors: list[str] = []
    _update_scheduled_post(
        business_id,
        scheduled_post_id,
        {"status": "publishing", "publish_error": None, "attempt_count": int(post.get("attempt_count") or 0) + 1},
    )
    for provider in post.get("platforms") or []:
        if provider == "x":
            try:
                post_id, post_url = await _publish_to_x(business_id, asset, post["caption"])
                provider_post_ids["x"] = post_id
                if post_url:
                    provider_post_urls["x"] = post_url
            except Exception as exc:
                errors.append(f"X: {exc}")
        elif provider == "instagram":
            try:
                post_id, post_url = await _publish_to_instagram(
                    business_id,
                    instagram_assets,
                    post["caption"],
                    instagram_media_type,
                )
                provider_post_ids["instagram"] = post_id
                if post_url:
                    provider_post_urls["instagram"] = post_url
            except Exception as exc:
                errors.append(f"Instagram: {exc}")
        else:
            errors.append(f"{provider} publishing is not implemented yet.")
    if errors:
        _update_scheduled_post(
            business_id,
            scheduled_post_id,
            {
                "status": "failed",
                "provider_post_ids": provider_post_ids,
                "metadata": {**metadata, "provider_post_urls": provider_post_urls},
                "publish_error": "; ".join(errors),
            },
        )
        return {"published": False, "errors": errors, "provider_post_ids": provider_post_ids}
    _update_scheduled_post(
        business_id,
        scheduled_post_id,
        {
            "status": "published",
            "provider_post_ids": provider_post_ids,
            "metadata": {**metadata, "provider_post_urls": provider_post_urls},
            "publish_error": None,
            "published_at": _now_iso(),
        },
    )
    return {"published": True, "provider_post_ids": provider_post_ids}


async def publish_due_scheduled_posts(limit: int = 10) -> dict[str, int]:
    rows = (
        supabase_admin.table("marketing_scheduled_posts")
        .select("*")
        .eq("status", "scheduled")
        .lte("scheduled_for", _now_iso())
        .order("scheduled_for", desc=False)
        .limit(limit)
        .execute()
        .data
        or []
    )
    published = 0
    failed = 0
    for row in rows:
        result = await publish_scheduled_post(row["business_id"], row["id"])
        if result.get("published"):
            published += 1
        else:
            failed += 1
    return {"checked": len(rows), "published": published, "failed": failed}
