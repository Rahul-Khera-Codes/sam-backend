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
from app.services import email_service as gmail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/gmail", tags=["integrations"])


def _apply_location_filter(query, location_id: Optional[str]):
    """Apply location_id filter: eq if provided, is null if not."""
    if location_id:
        return query.eq("location_id", location_id)
    return query.is_("location_id", "null")


def _get_token_row_for_location(business_id: str, location_id: Optional[str]) -> Optional[dict]:
    """Fetch gmail token row scoped to (business_id, location_id)."""
    query = (
        supabase_admin.table("gmail_tokens")
        .select("*")
        .eq("business_id", business_id)
    )
    query = _apply_location_filter(query, location_id)
    result = query.limit(1).execute()
    return result.data[0] if result.data else None


# ── GET /integrations/gmail/auth-url ─────────────────────────────────────────

@router.get("/auth-url")
async def get_auth_url(
    business_id: str,
    location_id: Optional[str] = None,
    return_to: str = "/dashboard/settings/business",
    user_id: str = Depends(get_user_id),
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
    )
    return {"url": url}


# ── POST /integrations/gmail/callback ────────────────────────────────────────

class GmailCallbackRequest(BaseModel):
    code: str
    state: str
    business_id: str


@router.post("/callback")
async def oauth_callback(body: GmailCallbackRequest):
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Gmail not configured.")

    try:
        state = json.loads(body.state)
        business_id = state["business_id"]
        location_id = state.get("location_id")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter.")

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

    token_expiry = gmail.token_expiry_from_response(token_data)

    row = {
        "business_id": business_id,
        "google_email": google_email,
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
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
    row = _get_token_row_for_location(business_id, location_id)
    if row:
        google_email = row.get("google_email", "")
        if not google_email and row.get("access_token"):
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {row['access_token']}"},
                    )
                    if resp.status_code == 200:
                        google_email = resp.json().get("email", "")
                        if google_email:
                            supabase_admin.table("gmail_tokens").update(
                                {"google_email": google_email}
                            ).eq("id", row["id"]).execute()
            except Exception:
                pass
        return {"connected": True, "google_email": google_email, "location_id": location_id}
    return {"connected": False, "google_email": "", "location_id": location_id}


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
