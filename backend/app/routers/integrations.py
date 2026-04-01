"""
Google Calendar OAuth integration routes.

GET  /integrations/google/auth-url    → returns OAuth consent URL for frontend to redirect to
POST /integrations/google/callback    → exchange code for tokens, save to DB
GET  /integrations/google/status      → is current user connected?
DELETE /integrations/google/disconnect → revoke + delete tokens
"""

import json
import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import get_current_user, get_user_id
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.services import google_calendar_service as gcal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/google", tags=["integrations"])


# ── GET /integrations/google/auth-url ────────────────────────────────────────

@router.get("/auth-url")
async def get_auth_url(
    business_id: str,
    return_to: str = "/dashboard/settings/integrations",
    user_id: str = Depends(get_user_id),
):
    """
    Returns the Google OAuth consent URL.
    `return_to` is the frontend path Google should redirect back to after OAuth.
    `state` encodes user_id + business_id + return_to.
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google Calendar integration is not configured on this server.",
        )

    state = json.dumps({"user_id": user_id, "business_id": business_id, "return_to": return_to})
    url = gcal.build_auth_url(
        client_id=settings.google_client_id,
        redirect_uri=settings.google_redirect_uri,
        state=state,
    )
    return {"url": url}


# ── POST /integrations/google/callback ───────────────────────────────────────

class CallbackRequest(BaseModel):
    code: str
    state: str          # JSON string: {"user_id": "...", "business_id": "..."}
    business_id: str    # redundant but lets us validate against the state


@router.post("/callback")
async def oauth_callback(body: CallbackRequest):
    """
    Exchange the OAuth code for tokens and save to google_calendar_tokens.
    Called by the frontend after Google redirects back with ?code=...&state=...
    """
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google Calendar not configured.")

    try:
        state = json.loads(body.state)
        user_id = state["user_id"]
        business_id = state["business_id"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter.")

    # Exchange code for tokens
    try:
        token_data = await gcal.exchange_code_for_tokens(
            code=body.code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
        )
    except Exception as e:
        logger.error("Google token exchange failed: %s", e)
        raise HTTPException(status_code=400, detail="Failed to exchange Google authorization code.")

    if "refresh_token" not in token_data:
        raise HTTPException(
            status_code=400,
            detail="No refresh token returned. User may need to revoke access and reconnect.",
        )

    # Fetch Google account email from tokeninfo
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

    token_expiry = gcal.token_expiry_from_response(token_data)

    row = {
        "staff_id": user_id,
        "business_id": business_id,
        "google_email": google_email,
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "token_expiry": token_expiry.isoformat(),
    }

    # Upsert (update if already exists for this staff + business)
    try:
        supabase_admin.table("google_calendar_tokens").upsert(
            row, on_conflict="staff_id,business_id"
        ).execute()
    except Exception as e:
        logger.error("Failed to save Google tokens: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save Google Calendar connection.")

    return {"connected": True, "google_email": google_email}


# ── GET /integrations/google/status ──────────────────────────────────────────

@router.get("/status")
async def get_status(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    """Returns whether the current user has connected Google Calendar for this business."""
    token_row = gcal.get_token_row(supabase_admin, user_id)
    if token_row and token_row.get("business_id") == business_id:
        google_email = token_row.get("google_email", "")
        # Backfill email if missing — fetch from Google userinfo and persist
        if not google_email and token_row.get("access_token"):
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {token_row['access_token']}"},
                    )
                    if resp.status_code == 200:
                        google_email = resp.json().get("email", "")
                        if google_email:
                            supabase_admin.table("google_calendar_tokens").update(
                                {"google_email": google_email}
                            ).eq("staff_id", user_id).execute()
            except Exception:
                pass
        return {"connected": True, "google_email": google_email}
    return {"connected": False, "google_email": ""}


# ── DELETE /integrations/google/disconnect ────────────────────────────────────

@router.delete("/disconnect")
async def disconnect(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    """Revoke Google tokens and remove the DB record."""
    token_row = gcal.get_token_row(supabase_admin, user_id)
    if not token_row:
        return {"disconnected": True}

    # Revoke with Google (best effort)
    try:
        await gcal.revoke_token(token_row["refresh_token"])
    except Exception:
        pass

    try:
        supabase_admin.table("google_calendar_tokens").delete().eq("staff_id", user_id).execute()
    except Exception as e:
        logger.error("Failed to delete Google tokens from DB: %s", e)
        raise HTTPException(status_code=500, detail="Failed to disconnect Google Calendar.")

    return {"disconnected": True}
