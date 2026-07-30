from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.marketing import (
    MarketingIntegrationStatusResponse,
    MarketingIntegrationsStatusResponse,
)

X_SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access", "media.write"]
INSTAGRAM_SCOPES = ["instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"]
MARKETING_ASSETS_BUCKET = "marketing-assets"
SIGNED_URL_TTL_SECONDS = 60 * 60 * 6


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
        local_uri = settings.marketing_meta_redirect_uri_local or settings.marketing_meta_redirect_uri
        production_uri = settings.marketing_meta_redirect_uri_production or settings.marketing_meta_redirect_uri
    return local_uri if _is_local_origin(origin) else production_uri


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
    if not settings.marketing_meta_app_id:
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
        "client_id": settings.marketing_meta_app_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(INSTAGRAM_SCOPES),
        "response_type": "code",
        "state": state,
    }
    return f"https://www.facebook.com/v20.0/dialog/oauth?{urlencode(params)}"


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
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.get(
            "https://graph.facebook.com/v20.0/oauth/access_token",
            params={
                "client_id": settings.marketing_meta_app_id,
                "client_secret": settings.marketing_meta_app_secret,
                "redirect_uri": parsed.get("redirect_uri") or settings.marketing_meta_redirect_uri,
                "code": code,
            },
        )
        if token_response.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Instagram token exchange failed: {token_response.text}")
        token_data = token_response.json()
        access_token = token_data["access_token"]
        long_response = await client.get(
            "https://graph.facebook.com/v20.0/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.marketing_meta_app_id,
                "client_secret": settings.marketing_meta_app_secret,
                "fb_exchange_token": access_token,
            },
        )
        if long_response.status_code < 400:
            token_data = long_response.json()
            access_token = token_data.get("access_token", access_token)
        pages_response = await client.get(
            "https://graph.facebook.com/v20.0/me/accounts",
            params={"fields": "id,name,instagram_business_account{id,username,name}", "access_token": access_token},
        )
        if pages_response.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Instagram account lookup failed: {pages_response.text}")
        pages = pages_response.json().get("data") or []
    page = next((item for item in pages if item.get("instagram_business_account")), None)
    if not page:
        raise HTTPException(status_code=400, detail="No linked Instagram Business/Creator account found for this Meta user.")
    ig_account = page["instagram_business_account"]
    expires_at = None
    if token_data.get("expires_in"):
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))).isoformat()
    return _upsert_integration(
        business_id=business_id,
        user_id=parsed["user_id"],
        provider="instagram",
        account_id=ig_account.get("id"),
        account_name=ig_account.get("username") or ig_account.get("name"),
        provider_page_id=page.get("id"),
        access_token=access_token,
        refresh_token=None,
        expires_at=expires_at,
        scopes=INSTAGRAM_SCOPES,
        metadata={"page_name": page.get("name")},
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


async def _publish_to_instagram(business_id: str, asset: dict[str, Any], caption: str) -> tuple[str, str]:
    row, access_token = await _access_token_for_provider(business_id, "instagram")
    ig_user_id = row.get("provider_account_id")
    if not ig_user_id:
        raise RuntimeError("Instagram account id is missing. Reconnect Instagram.")
    image_url = _signed_asset_url(asset)
    if not image_url:
        raise RuntimeError("Generated image URL is unavailable for Instagram publishing.")
    async with httpx.AsyncClient(timeout=60) as client:
        create_response = await client.post(
            f"https://graph.facebook.com/v20.0/{ig_user_id}/media",
            params={
                "image_url": image_url,
                "caption": caption[:2200],
                "access_token": access_token,
            },
        )
        if create_response.status_code >= 400:
            raise RuntimeError(f"Instagram media container failed: {create_response.text}")
        creation_id = create_response.json().get("id")
        if not creation_id:
            raise RuntimeError(f"Instagram media container returned no id: {create_response.text}")
        publish_response = await client.post(
            f"https://graph.facebook.com/v20.0/{ig_user_id}/media_publish",
            params={"creation_id": creation_id, "access_token": access_token},
        )
        if publish_response.status_code >= 400:
            raise RuntimeError(f"Instagram publish failed: {publish_response.text}")
        published_id = publish_response.json().get("id") or creation_id
        permalink_response = await client.get(
            f"https://graph.facebook.com/v20.0/{published_id}",
            params={"fields": "permalink", "access_token": access_token},
        )
        permalink = ""
        if permalink_response.status_code < 400:
            permalink = permalink_response.json().get("permalink") or ""
    return published_id, permalink


async def publish_scheduled_post(business_id: str, scheduled_post_id: str) -> dict[str, Any]:
    post = _get_single("marketing_scheduled_posts", scheduled_post_id, business_id)
    asset = _get_single("marketing_assets", post["asset_id"], business_id)
    provider_post_ids = dict(post.get("provider_post_ids") or {})
    metadata = dict(post.get("metadata") or {})
    provider_post_urls = dict(metadata.get("provider_post_urls") or {})
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
                post_id, post_url = await _publish_to_instagram(business_id, asset, post["caption"])
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
