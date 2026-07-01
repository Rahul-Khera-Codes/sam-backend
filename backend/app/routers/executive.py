"""
Executive Agent router.
POST /executive/session — creates a LiveKit room for a browser-based
executive assistant session and returns the token for the frontend to join.
"""
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.services import livekit_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/executive", tags=["executive"])

EXECUTIVE_AGENT_NAME = "executive-agent"


class ExecutiveSessionRequest(BaseModel):
    business_id: str
    location_id: str | None = None
    avatar_enabled: bool = True


class ExecutiveSessionResponse(BaseModel):
    room_name: str
    token: str
    livekit_url: str
    avatar_available: bool


@router.post("/session", response_model=ExecutiveSessionResponse)
async def create_executive_session(
    body: ExecutiveSessionRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)

    # Fetch business name for greeting context
    biz_row = (
        supabase_admin.table("businesses")
        .select("name")
        .eq("id", body.business_id)
        .limit(1)
        .execute()
    )
    if not biz_row.data:
        raise HTTPException(status_code=404, detail="Business not found.")

    # Create LiveKit room — prefix "executive-" distinguishes from call rooms
    room_name = f"executive-{body.business_id[:8]}-{uuid.uuid4().hex[:8]}"
    await livekit_service.create_room(room_name)

    # Generate participant token for the browser client
    token = livekit_service.generate_user_token(
        room_name,
        f"owner-{user_id[:12]}",
        metadata={
            "session_type": "executive",
            "business_id": body.business_id,
            "user_id": user_id,
            "location_id": body.location_id,
        },
    )

    # Dispatch the executive agent to the room
    await livekit_service.create_executive_agent_dispatch(
        room_name,
        metadata={
            "session_type": "executive",
            "business_id": body.business_id,
            "user_id": user_id,
            "location_id": body.location_id,
            "avatar_enabled": body.avatar_enabled,
        },
    )

    logger.info(
        "Executive session created: room=%s business=%s avatar_enabled=%s",
        room_name, body.business_id, body.avatar_enabled,
    )

    # avatar_available = env var set (future: also check billing tier)
    avatar_available = bool(os.environ.get("LIVEAVATAR_AVATAR_ID", ""))

    return ExecutiveSessionResponse(
        room_name=room_name,
        token=token,
        livekit_url=settings.livekit_url,
        avatar_available=avatar_available,
    )
