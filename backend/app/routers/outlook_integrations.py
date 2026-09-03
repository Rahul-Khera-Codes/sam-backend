"""
Outlook OAuth integration routes.

GET    /integrations/outlook/auth-url    → returns OAuth consent URL
POST   /integrations/outlook/callback   → exchange code for tokens, save to DB
GET    /integrations/outlook/status     → is Outlook connected for this business+location?
DELETE /integrations/outlook/disconnect → delete stored tokens (see note in
                                           outlook_email_service.py — Microsoft
                                           Graph has no revoke endpoint)
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import get_current_user, get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.services import outlook_email_service as outlook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/outlook", tags=["integrations"])


def _apply_location_filter(query, location_id: Optional[str]):
    """Apply location_id filter: eq if provided, is null if not."""
    if location_id:
        return query.eq("location_id", location_id)
    return query.is_("location_id", "null")


def _get_token_row_for_location(business_id: str, location_id: Optional[str]) -> Optional[dict]:
    """Fetch outlook token row scoped to (business_id, location_id)."""
    query = (
        supabase_admin.table("outlook_tokens")
        .select("*")
        .eq("business_id", business_id)
    )
    query = _apply_location_filter(query, location_id)
    result = query.limit(1).execute()
    return result.data[0] if result.data else None


def _get_business_token_row(business_id: str) -> Optional[dict]:
    result = (
        supabase_admin.table("outlook_tokens")
        .select("*")
        .eq("business_id", business_id)
        .is_("location_id", "null")
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# ── GET /integrations/outlook/auth-url ───────────────────────────────────────

@router.get("/auth-url")
async def get_auth_url(
    business_id: str,
    location_id: Optional[str] = None,
    return_to: str = "/dashboard/settings/business",
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    if not settings.microsoft_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Outlook integration is not configured on this server.",
        )

    state = json.dumps({
        "user_id": user_id,
        "business_id": business_id,
        "location_id": location_id,
        "return_to": return_to,
        "integration": "outlook",
    })
    logger.info("Outlook OAuth redirect_uri: %s", settings.outlook_redirect_uri)
    url = outlook.build_outlook_auth_url(
        client_id=settings.microsoft_client_id,
        redirect_uri=settings.outlook_redirect_uri,
        state=state,
    )
    return {"url": url}


# ── POST /integrations/outlook/callback ──────────────────────────────────────

class OutlookCallbackRequest(BaseModel):
    code: str
    state: str
    business_id: str


@router.post("/callback")
async def oauth_callback(body: OutlookCallbackRequest):
    if not settings.microsoft_client_id:
        raise HTTPException(status_code=501, detail="Outlook not configured.")

    try:
        state = json.loads(body.state)
        business_id = state["business_id"]
        location_id = state.get("location_id")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter.")

    try:
        token_data = await outlook.exchange_code_for_tokens(
            code=body.code,
            client_id=settings.microsoft_client_id,
            client_secret=settings.microsoft_client_secret,
            redirect_uri=settings.outlook_redirect_uri,
        )
    except Exception as e:
        logger.error("Outlook token exchange failed: %s", e)
        raise HTTPException(status_code=400, detail="Failed to exchange Outlook authorization code.")

    if "refresh_token" not in token_data:
        raise HTTPException(
            status_code=400,
            detail="No refresh token returned. User may need to revoke access and reconnect.",
        )

    if not outlook.has_outlook_send_scope(token_data.get("scope")):
        logger.warning(
            "Outlook OAuth callback missing Mail.Send scope for business %s loc %s. Granted scopes: %s",
            business_id,
            location_id,
            token_data.get("scope") or "<not returned>",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Outlook connected without mail-sending permission. Please disconnect Outlook, "
                "then reconnect and approve send access."
            ),
        )

    microsoft_email = await outlook.fetch_microsoft_email(token_data["access_token"])
    token_expiry = outlook.token_expiry_from_response(token_data)

    row = {
        "business_id": business_id,
        "microsoft_email": microsoft_email,
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
            supabase_admin.table("outlook_tokens").update(
                {k: v for k, v in row.items() if k not in ("business_id", "location_id")}
            ).eq("id", existing["id"]).execute()
        else:
            supabase_admin.table("outlook_tokens").insert(row).execute()
    except Exception as e:
        logger.error("Failed to save Outlook tokens: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save Outlook connection.")

    return {"connected": True, "microsoft_email": microsoft_email, "location_id": location_id}


# ── GET /integrations/outlook/status ─────────────────────────────────────────

@router.get("/status")
async def get_status(
    business_id: str,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    row = _get_token_row_for_location(business_id, location_id)
    if not row and location_id:
        row = _get_business_token_row(business_id)
    if row:
        return {
            "connected": True,
            "microsoft_email": row.get("microsoft_email", ""),
            "location_id": location_id,
        }
    return {"connected": False, "microsoft_email": "", "location_id": location_id}


# ── DELETE /integrations/outlook/disconnect ──────────────────────────────────

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

    # No Microsoft Graph revoke endpoint for delegated consent — deleting the
    # stored row is all we can do server-side. The user's consent grant itself
    # persists until removed at https://myaccount.microsoft.com/consents.
    try:
        supabase_admin.table("outlook_tokens").delete().eq("id", row["id"]).execute()
    except Exception as e:
        logger.error("Failed to delete Outlook tokens: %s", e)
        raise HTTPException(status_code=500, detail="Failed to disconnect Outlook.")

    return {"disconnected": True}
