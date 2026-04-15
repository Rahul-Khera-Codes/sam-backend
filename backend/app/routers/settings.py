from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user, get_user_id, require_business_access
from app.core.supabase import supabase_admin
from app.schemas.settings import (
    AgentSettingsResponse,
    UpdateAgentSettingsRequest,
    AgentStateResponse,
    ToggleAgentStateRequest,
    AgentScheduleResponse,
    UpdateAgentScheduleRequest,
    CommunicationSettingsResponse,
    UpdateCommunicationSettingsRequest,
)
from datetime import datetime, timezone

router = APIRouter(prefix="/settings", tags=["settings"])

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _apply_location_filter(query, location_id: Optional[str]):
    """Apply location_id filter: eq if provided, is null if not."""
    if location_id:
        return query.eq("location_id", location_id)
    return query.is_("location_id", "null")
DEFAULT_SCHEDULE = {
    "monday": {"is_open": True, "open_time": "09:00", "close_time": "17:00"},
    "tuesday": {"is_open": True, "open_time": "09:00", "close_time": "17:00"},
    "wednesday": {"is_open": True, "open_time": "09:00", "close_time": "17:00"},
    "thursday": {"is_open": True, "open_time": "09:00", "close_time": "17:00"},
    "friday": {"is_open": True, "open_time": "09:00", "close_time": "17:00"},
    "saturday": {"is_open": False, "open_time": None, "close_time": None},
    "sunday": {"is_open": False, "open_time": None, "close_time": None},
}


def _serialize_schedule_rows(rows: list[dict]) -> list[dict]:
    rows_by_day = {row["day_of_week"]: row for row in rows if row.get("day_of_week")}
    schedule = []
    for day in DAY_ORDER:
        row = rows_by_day.get(day)
        if row:
            schedule.append({
                "day_of_week": day,
                "is_open": bool(row.get("is_open")),
                "open_time": row.get("open_time"),
                "close_time": row.get("close_time"),
            })
        else:
            default = DEFAULT_SCHEDULE[day]
            schedule.append({
                "day_of_week": day,
                "is_open": default["is_open"],
                "open_time": default["open_time"],
                "close_time": default["close_time"],
            })
    return schedule


# ── GET /settings/agent ───────────────────────
# Returns all 10 feature flag toggles

@router.get("/agent")
async def get_agent_settings(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase_admin.table("agent_settings")
        .select("*")
        .eq("business_id", business_id)
        .order("feature_key")
    )
    query = _apply_location_filter(query, location_id)
    result = query.execute()

    return {
        "business_id": business_id,
        "location_id": location_id,
        "settings": result.data or [],
    }


# ── PUT /settings/agent ───────────────────────
# Saves feature flag changes + writes audit log

@router.put("/agent")
async def update_agent_settings(
    business_id: str,
    body: UpdateAgentSettingsRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    # Get current values for audit log
    current_query = (
        supabase_admin.table("agent_settings")
        .select("feature_key, is_enabled")
        .eq("business_id", business_id)
    )
    current_query = _apply_location_filter(current_query, location_id)
    current = current_query.execute()
    current_map = {s["feature_key"]: s["is_enabled"] for s in (current.data or [])}

    audit_entries = []
    for setting in body.settings:
        row = {
            "business_id": business_id,
            "feature_key": setting.feature_key,
            "is_enabled": setting.is_enabled,
            "config_value": setting.config_value or {},
            "updated_by": user_id,
        }
        if location_id:
            row["location_id"] = location_id

        # SELECT + INSERT/UPDATE (partial unique indexes don't work with upsert)
        existing = supabase_admin.table("agent_settings").select("id").eq("business_id", business_id).eq("feature_key", setting.feature_key)
        existing = _apply_location_filter(existing, location_id)
        existing_result = existing.limit(1).execute()

        if existing_result.data:
            supabase_admin.table("agent_settings").update(
                {"is_enabled": setting.is_enabled, "config_value": setting.config_value or {}, "updated_by": user_id}
            ).eq("id", existing_result.data[0]["id"]).execute()
        else:
            supabase_admin.table("agent_settings").insert(row).execute()

        old_val = current_map.get(setting.feature_key)
        if old_val != setting.is_enabled:
            audit_entries.append({
                "business_id": business_id,
                "location_id": location_id,
                "feature_key": setting.feature_key,
                "old_value": old_val,
                "new_value": setting.is_enabled,
                "changed_by": user_id,
            })

    if audit_entries:
        supabase_admin.table("settings_audit_log").insert(audit_entries).execute()

    return {"success": True, "updated": len(body.settings)}


# ── POST /settings/agent/reset ────────────────
# Resets all feature flags to defaults

@router.post("/agent/reset")
async def reset_agent_settings(
    business_id: str,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    defaults = {
        "inbound_calling": True,
        "outbound_calling": True,
        "call_forwarding": True,
        "send_texts_during_after_calls": True,
        "missed_call_text_back": True,
        "callback_scheduling": True,
        "reschedule_cancel_appointments": True,
        "confirmation_reminder_calls": True,
        "multi_language_support": False,
        "feedback_after_call": True,
    }

    for key, value in defaults.items():
        row = {
            "business_id": business_id,
            "feature_key": key,
            "is_enabled": value,
            "updated_by": user_id,
        }
        if location_id:
            row["location_id"] = location_id

        existing = supabase_admin.table("agent_settings").select("id").eq("business_id", business_id).eq("feature_key", key)
        existing = _apply_location_filter(existing, location_id)
        existing_result = existing.limit(1).execute()

        if existing_result.data:
            supabase_admin.table("agent_settings").update(
                {"is_enabled": value, "updated_by": user_id}
            ).eq("id", existing_result.data[0]["id"]).execute()
        else:
            supabase_admin.table("agent_settings").insert(row).execute()

    return {"success": True, "message": "Settings reset to defaults"}


# ── GET /settings/agent/state ─────────────────
# Global on/off toggle

@router.get("/agent/state", response_model=AgentStateResponse)
async def get_agent_state(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase_admin.table("agent_state")
        .select("*")
        .eq("business_id", business_id)
    )
    query = _apply_location_filter(query, location_id)
    result = query.limit(1).execute()

    if not result.data:
        return {"business_id": business_id, "location_id": location_id, "is_active": False, "toggled_at": None}

    return result.data[0]


# ── PUT /settings/agent/state ─────────────────

@router.put("/agent/state", response_model=AgentStateResponse)
async def toggle_agent_state(
    business_id: str,
    body: ToggleAgentStateRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    row = {
        "business_id": business_id,
        "is_active": body.is_active,
        "toggled_at": datetime.now(timezone.utc).isoformat(),
        "toggled_by": user_id,
    }
    if location_id:
        row["location_id"] = location_id

    existing = supabase_admin.table("agent_state").select("id").eq("business_id", business_id)
    existing = _apply_location_filter(existing, location_id)
    existing_result = existing.limit(1).execute()

    if existing_result.data:
        result = supabase_admin.table("agent_state").update(
            {"is_active": body.is_active, "toggled_at": row["toggled_at"], "toggled_by": user_id}
        ).eq("id", existing_result.data[0]["id"]).execute()
    else:
        result = supabase_admin.table("agent_state").insert(row).execute()

    return result.data[0]


# ── GET /settings/agent/schedule ──────────────

@router.get("/agent/schedule", response_model=AgentScheduleResponse)
async def get_agent_schedule(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase_admin.table("business_hours")
        .select("day_of_week, is_open, open_time, close_time")
        .eq("business_id", business_id)
    )
    query = _apply_location_filter(query, location_id)
    result = query.execute()

    return {
        "business_id": business_id,
        "location_id": location_id,
        "schedule": _serialize_schedule_rows(result.data or []),
    }


# ── PUT /settings/agent/schedule ──────────────

@router.put("/agent/schedule", response_model=AgentScheduleResponse)
async def update_agent_schedule(
    business_id: str,
    body: UpdateAgentScheduleRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    seen_days = set()
    for item in body.schedule:
        day = item.day_of_week.lower()
        if day not in DAY_ORDER:
            raise HTTPException(status_code=400, detail=f"Invalid day_of_week: {item.day_of_week}")
        if day in seen_days:
            raise HTTPException(status_code=400, detail=f"Duplicate day_of_week: {item.day_of_week}")
        seen_days.add(day)
        if item.is_open and (not item.open_time or not item.close_time):
            raise HTTPException(
                status_code=400,
                detail=f"Open days must include both open_time and close_time: {item.day_of_week}",
            )

        row = {
            "business_id": business_id,
            "day_of_week": day,
            "is_open": item.is_open,
            "open_time": item.open_time if item.is_open else None,
            "close_time": item.close_time if item.is_open else None,
        }
        if location_id:
            row["location_id"] = location_id

        existing = supabase_admin.table("business_hours").select("id").eq("business_id", business_id).eq("day_of_week", day)
        existing = _apply_location_filter(existing, location_id)
        existing_result = existing.limit(1).execute()

        if existing_result.data:
            supabase_admin.table("business_hours").update({
                "is_open": row["is_open"], "open_time": row["open_time"], "close_time": row["close_time"],
            }).eq("id", existing_result.data[0]["id"]).execute()
        else:
            supabase_admin.table("business_hours").insert(row).execute()

    read_query = (
        supabase_admin.table("business_hours")
        .select("day_of_week, is_open, open_time, close_time")
        .eq("business_id", business_id)
    )
    read_query = _apply_location_filter(read_query, location_id)
    result = read_query.execute()

    return {
        "business_id": business_id,
        "location_id": location_id,
        "schedule": _serialize_schedule_rows(result.data or []),
    }


# ── GET /settings/agent/audit-log ────────────
# Last 7 days of settings changes

@router.get("/agent/audit-log")
async def get_audit_log(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase_admin.table("settings_audit_log")
        .select("*")
        .eq("business_id", business_id)
        .order("changed_at", desc=True)
        .limit(50)
    )
    if location_id:
        query = query.eq("location_id", location_id)
    result = query.execute()

    return {"entries": result.data or []}


# ── GET /settings/communication ───────────────
# Call/email/SMS reminder + followup scripts

@router.get("/communication", response_model=CommunicationSettingsResponse)
async def get_communication_settings(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase_admin.table("communication_settings")
        .select("*")
        .eq("business_id", business_id)
    )
    query = _apply_location_filter(query, location_id)
    result = query.execute()

    return {
        "business_id": business_id,
        "settings": result.data or [],
    }


# ── PUT /settings/communication ───────────────
# Saves scripts from CustomerServiceSettings page

@router.put("/communication")
async def update_communication_settings(
    business_id: str,
    body: UpdateCommunicationSettingsRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    for item in body.settings:
        row = {
            "business_id": business_id,
            "channel": item.channel,
            "type": item.type,
            "is_enabled": item.is_enabled,
            "days_offset": item.days_offset,
            "script": item.script,
            "updated_by": user_id,
        }
        if location_id:
            row["location_id"] = location_id

        existing = supabase_admin.table("communication_settings").select("id").eq("business_id", business_id).eq("channel", item.channel).eq("type", item.type)
        existing = _apply_location_filter(existing, location_id)
        existing_result = existing.limit(1).execute()

        if existing_result.data:
            supabase_admin.table("communication_settings").update({
                "is_enabled": item.is_enabled, "days_offset": item.days_offset, "script": item.script, "updated_by": user_id,
            }).eq("id", existing_result.data[0]["id"]).execute()
        else:
            supabase_admin.table("communication_settings").insert(row).execute()

    return {"success": True, "updated": len(body.settings)}
