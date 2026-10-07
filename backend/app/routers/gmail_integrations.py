"""
Gmail OAuth integration routes.

GET    /integrations/gmail/auth-url    → returns OAuth consent URL
POST   /integrations/gmail/callback   → exchange code for tokens, save to DB
GET    /integrations/gmail/status     → is Gmail connected for this business+location?
DELETE /integrations/gmail/disconnect → revoke + delete tokens
"""

import json
import logging
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import get_current_user, get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.core.token_crypto import decrypt_oauth_token, encrypt_oauth_token
from app.services import email_service as gmail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/gmail", tags=["integrations"])


def _apply_location_filter(query, location_id: Optional[str]):
    """Apply location_id filter: eq if provided, is null if not."""
    if location_id:
        return query.eq("location_id", location_id)
    return query.is_("location_id", "null")


def _decrypt_row_tokens(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return row
    row["access_token"] = decrypt_oauth_token(row.get("access_token"))
    row["refresh_token"] = decrypt_oauth_token(row.get("refresh_token"))
    return row


def _get_token_row_for_location(business_id: str, location_id: Optional[str]) -> Optional[dict]:
    """Fetch gmail token row scoped to (business_id, location_id)."""
    query = (
        supabase_admin.table("gmail_tokens")
        .select("*")
        .eq("business_id", business_id)
    )
    query = _apply_location_filter(query, location_id)
    result = query.limit(1).execute()
    return _decrypt_row_tokens(result.data[0]) if result.data else None


def _get_business_token_row(business_id: str) -> Optional[dict]:
    """Newest Gmail token row for this business, regardless of location.
    Gmail is one connection per business — there's no per-location connect
    UI — so a stale row under one location_id shouldn't shadow a working one
    under a different location_id (AIE-90/AIE-99)."""
    result = (
        supabase_admin.table("gmail_tokens")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return _decrypt_row_tokens(result.data[0]) if result.data else None


# ── GET /integrations/gmail/auth-url ─────────────────────────────────────────

@router.get("/auth-url")
async def get_auth_url(
    business_id: str,
    location_id: Optional[str] = None,
    return_to: str = "/dashboard/settings/business",
    user_id: str = Depends(get_user_id),
    current_user: dict = Depends(get_current_user),
):
    verify_business_access(user_id, business_id)

    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Gmail integration is not configured on this server.",
        )

    state = json.dumps({
        "user_id": user_id,
        "business_id": business_id,
        "location_id": location_id,
        "return_to": return_to,
        "integration": "gmail",
    })
    logger.info("Gmail OAuth redirect_uri: %s", settings.gmail_redirect_uri)
    url = gmail.build_gmail_auth_url(
        client_id=settings.google_client_id,
        redirect_uri=settings.gmail_redirect_uri,
        state=state,
        login_hint=current_user.get("email"),
    )
    return {"url": url}


# ── POST /integrations/gmail/callback ────────────────────────────────────────

class GmailCallbackRequest(BaseModel):
    code: str
    state: str
    business_id: str


@router.post("/callback")
async def oauth_callback(
    body: GmailCallbackRequest,
    caller_user_id: str = Depends(get_user_id),
):
    """
    Requires the caller's own session and re-verifies it against both the
    supplied business_id and the state the flow was originally issued for —
    without this, state alone is just an unsigned JSON blob an attacker could
    forge to link their own Gmail account to an arbitrary victim business.
    """
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Gmail not configured.")

    verify_business_access(caller_user_id, body.business_id)

    try:
        state = json.loads(body.state)
        business_id = state["business_id"]
        location_id = state.get("location_id")
        initiating_user_id = state.get("user_id")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter.")

    if business_id != body.business_id or initiating_user_id != caller_user_id:
        raise HTTPException(status_code=400, detail="State does not match the authenticated request.")

    try:
        token_data = await gmail.exchange_code_for_tokens(
            code=body.code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.gmail_redirect_uri,
        )
    except Exception as e:
        logger.error("Gmail token exchange failed: %s", e)
        raise HTTPException(status_code=400, detail="Failed to exchange Gmail authorization code.")

    if "refresh_token" not in token_data:
        raise HTTPException(
            status_code=400,
            detail="No refresh token returned. User may need to revoke access and reconnect.",
        )

    granted_scopes = token_data.get("scope", "")
    has_send_scope = await gmail.has_gmail_send_scope(
        token_data["access_token"],
        granted_scopes,
    )
    if not has_send_scope:
        logger.warning(
            "Gmail OAuth callback missing gmail.send scope for business %s loc %s. Granted scopes: %s",
            business_id,
            location_id,
            granted_scopes or "<not returned>",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Gmail connected without mail-sending permission. Please disconnect Gmail, "
                "then reconnect and approve send access."
            ),
        )

    google_email = token_data.get("email", "")
    if not google_email:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {token_data['access_token']}"},
                )
                if resp.status_code == 200:
                    google_email = resp.json().get("email", "")
        except Exception:
            pass

    if google_email and initiating_user_id:
        profile = (
            supabase_admin.table("profiles")
            .select("email")
            .eq("id", initiating_user_id)
            .limit(1)
            .execute()
        )
        account_email = profile.data[0]["email"] if profile.data else None
        if account_email and account_email.strip().lower() != google_email.strip().lower():
            try:
                await gmail.revoke_token(token_data["access_token"])
            except Exception:
                pass
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The Gmail account you selected ({google_email}) doesn't match your "
                    f"account email ({account_email}). Please reconnect using the Gmail "
                    "account you use to sign in."
                ),
            )

    token_expiry = gmail.token_expiry_from_response(token_data)

    row = {
        "business_id": business_id,
        "google_email": google_email,
        "access_token": encrypt_oauth_token(token_data["access_token"]),
        "refresh_token": encrypt_oauth_token(token_data["refresh_token"]),
        "token_expiry": token_expiry.isoformat(),
    }
    if location_id:
        row["location_id"] = location_id

    # SELECT + INSERT/UPDATE (partial unique indexes don't work with upsert)
    try:
        existing = _get_token_row_for_location(business_id, location_id)
        if existing:
            supabase_admin.table("gmail_tokens").update(
                {k: v for k, v in row.items() if k not in ("business_id", "location_id")}
            ).eq("id", existing["id"]).execute()
        else:
            supabase_admin.table("gmail_tokens").insert(row).execute()
    except Exception as e:
        logger.error("Failed to save Gmail tokens: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save Gmail connection.")

    return {"connected": True, "google_email": google_email, "location_id": location_id}


# ── GET /integrations/gmail/status ───────────────────────────────────────────

@router.get("/status")
async def get_status(
    business_id: str,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    row = _get_business_token_row(business_id)
    if not row:
        return {"connected": False, "google_email": "", "location_id": location_id}

    # Row existence alone doesn't mean the connection still works — a revoked
    # or dead refresh token would still show "Connected" if we only checked
    # for a row (this masked the real Gmail outage behind AIE-90). Refresh if
    # expired, then confirm the token actually authenticates against Google,
    # every call — not just once when google_email was first cached.
    google_email = row.get("google_email", "")
    access_token = await gmail.get_valid_access_token(
        supabase_admin, business_id, settings.google_client_id, settings.google_client_secret, location_id,
    )
    if not access_token:
        return {"connected": False, "google_email": google_email, "location_id": location_id}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Gmail status validation failed for business %s loc %s: %s %s",
                    business_id, location_id, resp.status_code, resp.text[:200],
                )
                return {"connected": False, "google_email": google_email, "location_id": location_id}
            fetched_email = resp.json().get("email", "")
            if fetched_email and fetched_email != google_email:
                google_email = fetched_email
                supabase_admin.table("gmail_tokens").update(
                    {"google_email": google_email}
                ).eq("id", row["id"]).execute()
    except Exception as e:
        logger.warning("Gmail status validation request failed for business %s loc %s: %s", business_id, location_id, e)
        return {"connected": False, "google_email": google_email, "location_id": location_id}

    return {"connected": True, "google_email": google_email, "location_id": location_id}


# ── DELETE /integrations/gmail/disconnect ─────────────────────────────────────

@router.delete("/disconnect")
async def disconnect(
    business_id: str,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    row = _get_token_row_for_location(business_id, location_id)
    if not row:
        return {"disconnected": True}

    try:
        await gmail.revoke_token(row["refresh_token"])
    except Exception:
        pass

    try:
        supabase_admin.table("gmail_tokens").delete().eq("id", row["id"]).execute()
    except Exception as e:
        logger.error("Failed to delete Gmail tokens: %s", e)
        raise HTTPException(status_code=500, detail="Failed to disconnect Gmail.")

    return {"disconnected": True}
