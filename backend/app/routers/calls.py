import os
import sys
import subprocess
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from app.core.auth import get_current_user, get_user_id
from app.core.config import settings
from app.core.supabase import supabase, supabase_admin
from app.schemas.calls import (
    InitiateCallRequest,
    InitiateCallResponse,
    OutboundCallRequest,
    OutboundCallResponse,
    CallResponse,
    TranscriptResponse,
    CallSummaryResponse,
)
from app.services import livekit_service
from typing import List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Backend root (parent of app/) — worker is run as python -m worker.voice_agent from here
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

router = APIRouter(prefix="/calls", tags=["calls"])


# ── GET /calls ────────────────────────────────
# Paginated call list for the recordings page

@router.get("", response_model=List[CallResponse])
async def list_calls(
    business_id: str,
    status: Optional[str] = None,
    direction: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    query = (
        supabase.table("calls")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .range((page - 1) * limit, page * limit - 1)
    )

    if status:
        query = query.eq("status", status)
    if direction:
        query = query.eq("direction", direction)
    if search:
        query = query.ilike("caller_name", f"%{search}%")

    result = query.execute()

    if result.data is None:
        raise HTTPException(status_code=500, detail="Failed to fetch calls")

    return result.data


# ── GET /calls/recent-activity ────────────────
# Live feed for the dashboard

@router.get("/recent-activity")
async def recent_activity(
    business_id: str,
    limit: int = 10,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("calls")
        .select("id, caller_name, caller_phone, status, sentiment, direction, created_at, duration_seconds")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    items = []
    for call in (result.data or []):
        caller = call.get("caller_name") or call.get("caller_phone") or "Unknown caller"
        direction = call.get("direction", "inbound")
        status = call.get("status", "")

        title_map = {
            "completed": f"Call completed — {caller}",
            "missed":    f"Missed call — {caller}",
            "forwarded": f"Call forwarded — {caller}",
            "failed":    f"Call failed — {caller}",
            "active":    f"Active call — {caller}",
        }
        title = title_map.get(status, f"Call — {caller}")

        # Simple time-ago
        created_at = datetime.fromisoformat(call["created_at"].replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - created_at
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            time_ago = "just now"
        elif minutes < 60:
            time_ago = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            hours = minutes // 60
            time_ago = f"{hours} hour{'s' if hours != 1 else ''} ago"

        items.append({
            "call_id": call["id"],
            "title": title,
            "description": f"{direction.capitalize()} call",
            "status": status,
            "sentiment": call.get("sentiment"),
            "time_ago": time_ago,
            "created_at": call["created_at"],
        })

    return {"items": items}


# ── GET /calls/{id} ───────────────────────────

@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("calls")
        .select("*")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Call not found")

    return result.data[0]


# ── GET /calls/{id}/transcript ────────────────

@router.get("/{call_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    call_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("transcripts")
        .select("*")
        .eq("call_id", call_id)
        .order("sequence_order", desc=False)
        .execute()
    )

    return {
        "call_id": call_id,
        "utterances": result.data or [],
    }


# ── GET /calls/{id}/summary ───────────────────

@router.get("/{call_id}/summary", response_model=CallSummaryResponse)
async def get_summary(
    call_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("call_summaries")
        .select("*")
        .eq("call_id", call_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Summary not found")

    return result.data[0]


# ── GET /calls/{id}/recording ─────────────────
# Returns a signed URL from Supabase Storage

@router.get("/{call_id}/recording")
async def get_recording(
    call_id: str,
    current_user: dict = Depends(get_current_user),
):
    # Get the recording reference
    result = (
        supabase.table("recordings")
        .select("*")
        .eq("call_id", call_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Recording not found")

    recording = result.data[0]
    bucket = recording.get("storage_bucket", "call-recordings")
    path = recording.get("storage_path")

    # Generate signed URL (valid for 1 hour)
    signed = supabase.storage.from_(bucket).create_signed_url(path, 3600)

    return {
        "recording_id": recording["id"],
        "url": signed.get("signedURL"),
        "expires_in_seconds": 3600,
        "duration_seconds": recording.get("duration_seconds"),
        "file_size_bytes": recording.get("file_size_bytes"),
    }


# ── POST /calls/initiate ──────────────────────
# Creates a call record + LiveKit room
# Returns token for frontend to join

@router.post("/initiate", response_model=InitiateCallResponse)
async def initiate_call(
    body: InitiateCallRequest,
    user_id: str = Depends(get_user_id),
):
    # 1. Generate a LiveKit room
    room_id = livekit_service.generate_room_id()
    await livekit_service.create_room(room_id)

    # 2. Create call record in Supabase
    call_data = {
        "business_id": body.business_id,
        "location_id": body.location_id,
        "caller_name": body.caller_name,
        "caller_phone": body.caller_phone,
        "direction": body.direction.value,
        "status": "initiating",
        "livekit_room_id": room_id,
        "handled_by": user_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    result = supabase_admin.table("calls").insert(call_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create call record")

    call_id = result.data[0]["id"]

    # 3. Generate LiveKit token for the frontend user (metadata for LiveKit Agents voice-agent)
    participant_name = body.caller_name or f"user-{user_id[:8]}"
    user_token = livekit_service.generate_user_token(
        room_id,
        participant_name,
        metadata={
            "call_id": call_id,
            "business_id": body.business_id,
            "location_id": body.location_id or "",
        },
    )

    # 4. Update call status to active
    supabase_admin.table("calls").update({"status": "active"}).eq("id", call_id).execute()

    # 5. Voice agent: LiveKit Agents (automatic dispatch when user joins) or legacy worker
    use_livekit_agent = settings.use_livekit_agent
    logger.warning(f"use_livekit_agent: {use_livekit_agent}")
    if not use_livekit_agent:
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "worker.voice_agent",
                    "--call-id", call_id,
                    "--room-id", room_id,
                    "--business-id", body.business_id,
                ],
                cwd=str(_BACKEND_ROOT),
                env=os.environ.copy(),
                start_new_session=True,
            )
        except Exception as e:
            logger.warning("Failed to spawn voice agent worker: %s", e)

    return {
        "call_id": call_id,
        "livekit_room_id": room_id,
        "livekit_token": user_token,
        "livekit_ws_url": settings.livekit_url,
        "status": "active",
    }


# ── POST /calls/outbound ──────────────────────
# Dials a customer via PSTN and puts agent in the room.
# Flow: create room → dispatch agent → SIP INVITE customer → DB record

@router.post("/outbound", response_model=OutboundCallResponse, status_code=201)
async def initiate_outbound_call(
    body: OutboundCallRequest,
    user_id: str = Depends(get_user_id),
):
    # Look up the business's active phone number (used as caller ID)
    phone_row = (
        supabase_admin.table("business_phone_numbers")
        .select("phone_number")
        .eq("business_id", body.business_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not phone_row.data:
        raise HTTPException(
            status_code=422,
            detail="No active phone number provisioned for this business. Provision one first.",
        )
    from_number = phone_row.data[0]["phone_number"]

    if not settings.livekit_sip_outbound_trunk_id:
        raise HTTPException(
            status_code=503,
            detail="Outbound SIP trunk not configured. Provision a phone number first.",
        )

    # 1. Create LiveKit room
    room_id = livekit_service.generate_room_id()
    await livekit_service.create_room(room_id)

    # 2. Create call record
    call_data = {
        "business_id": body.business_id,
        "location_id": body.location_id,
        "caller_phone": body.to_phone_number,
        "caller_name": body.call_purpose or None,
        "direction": "outbound",
        "status": "initiating",
        "livekit_room_id": room_id,
        "handled_by": user_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    result = supabase_admin.table("calls").insert(call_data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create call record")
    call_id = result.data[0]["id"]

    # 3. Dispatch voice agent with outbound context
    await livekit_service.create_agent_dispatch(
        room_id,
        metadata={
            "call_id": call_id,
            "business_id": body.business_id,
            "location_id": body.location_id or "",
            "call_direction": "outbound",
            "call_purpose": body.call_purpose or "",
        },
    )

    # 4. Dial the customer via SIP
    try:
        await livekit_service.create_sip_participant(
            room_id,
            to_number=body.to_phone_number,
            from_number=from_number,
        )
    except Exception as e:
        logger.error("SIP dial failed: %s", e)
        supabase_admin.table("calls").update({"status": "failed"}).eq("id", call_id).execute()
        raise HTTPException(status_code=502, detail=f"SIP dial failed: {e}")

    supabase_admin.table("calls").update({"status": "active"}).eq("id", call_id).execute()

    return {"call_id": call_id, "livekit_room_id": room_id, "status": "active"}


# ── PUT /calls/{id}/status ────────────────────
# Used by voice worker to update call status

@router.put("/{call_id}/status")
async def update_call_status(
    call_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    allowed_statuses = ["active", "completed", "forwarded", "failed", "missed"]
    new_status = body.get("status")

    if new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")

    update_data = {"status": new_status}

    if new_status in ["completed", "forwarded", "failed", "missed"]:
        update_data["ended_at"] = datetime.now(timezone.utc).isoformat()

    supabase_admin.table("calls").update(update_data).eq("id", call_id).execute()

    return {"call_id": call_id, "status": new_status}
