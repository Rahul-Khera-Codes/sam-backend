from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user, get_user_id
from app.core.supabase import supabase_admin
from app.schemas.settings import (
    AgentSettingsResponse,
    UpdateAgentSettingsRequest,
    AgentStateResponse,
    ToggleAgentStateRequest,
    CommunicationSettingsResponse,
    UpdateCommunicationSettingsRequest,
)
from datetime import datetime, timezone

router = APIRouter(prefix="/settings", tags=["settings"])


# ── GET /settings/agent ───────────────────────
# Returns all 10 feature flag toggles

@router.get("/agent")
async def get_agent_settings(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase_admin.table("agent_settings")
        .select("*")
        .eq("business_id", business_id)
        .order("feature_key")
        .execute()
    )

    return {
        "business_id": business_id,
        "settings": result.data or [],
    }


# ── PUT /settings/agent ───────────────────────
# Saves feature flag changes + writes audit log

@router.put("/agent")
async def update_agent_settings(
    business_id: str,
    body: UpdateAgentSettingsRequest,
    user_id: str = Depends(get_user_id),
):
    # Get current values first for audit log
    current = (
        supabase_admin.table("agent_settings")
        .select("feature_key, is_enabled")
        .eq("business_id", business_id)
        .execute()
    )
    current_map = {s["feature_key"]: s["is_enabled"] for s in (current.data or [])}

    audit_entries = []
    for setting in body.settings:
        # Upsert the setting
        supabase_admin.table("agent_settings").upsert({
            "business_id": business_id,
            "feature_key": setting.feature_key,
            "is_enabled": setting.is_enabled,
            "config_value": setting.config_value or {},
            "updated_by": user_id,
        }, on_conflict="business_id,feature_key").execute()

        # Build audit log entry if value changed
        old_val = current_map.get(setting.feature_key)
        if old_val != setting.is_enabled:
            audit_entries.append({
                "business_id": business_id,
                "feature_key": setting.feature_key,
                "old_value": old_val,
                "new_value": setting.is_enabled,
                "changed_by": user_id,
            })

    # Write audit entries
    if audit_entries:
        supabase_admin.table("settings_audit_log").insert(audit_entries).execute()

    return {"success": True, "updated": len(body.settings)}


# ── POST /settings/agent/reset ────────────────
# Resets all feature flags to defaults

@router.post("/agent/reset")
async def reset_agent_settings(
    business_id: str,
    user_id: str = Depends(get_user_id),
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
        supabase_admin.table("agent_settings").upsert({
            "business_id": business_id,
            "feature_key": key,
            "is_enabled": value,
            "updated_by": user_id,
        }, on_conflict="business_id,feature_key").execute()

    return {"success": True, "message": "Settings reset to defaults"}


# ── GET /settings/agent/state ─────────────────
# Global on/off toggle

@router.get("/agent/state", response_model=AgentStateResponse)
async def get_agent_state(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase_admin.table("agent_state")
        .select("*")
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        # Auto-create if missing
        insert = supabase_admin.table("agent_state").upsert({
            "business_id": business_id,
            "is_active": True,
        }, on_conflict="business_id").execute()
        return insert.data[0]

    return result.data[0]


# ── PUT /settings/agent/state ─────────────────

@router.put("/agent/state", response_model=AgentStateResponse)
async def toggle_agent_state(
    business_id: str,
    body: ToggleAgentStateRequest,
    user_id: str = Depends(get_user_id),
):
    result = supabase_admin.table("agent_state").upsert({
        "business_id": business_id,
        "is_active": body.is_active,
        "toggled_at": datetime.now(timezone.utc).isoformat(),
        "toggled_by": user_id,
    }, on_conflict="business_id").execute()

    return result.data[0]


# ── GET /settings/agent/audit-log ────────────
# Last 7 days of settings changes

@router.get("/agent/audit-log")
async def get_audit_log(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase_admin.table("settings_audit_log")
        .select("*")
        .eq("business_id", business_id)
        .order("changed_at", desc=True)
        .limit(50)
        .execute()
    )

    return {"entries": result.data or []}


# ── GET /settings/communication ───────────────
# Call/email/SMS reminder + followup scripts

@router.get("/communication", response_model=CommunicationSettingsResponse)
async def get_communication_settings(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase_admin.table("communication_settings")
        .select("*")
        .eq("business_id", business_id)
        .execute()
    )

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
    user_id: str = Depends(get_user_id),
):
    for item in body.settings:
        supabase_admin.table("communication_settings").upsert({
            "business_id": business_id,
            "channel": item.channel,
            "type": item.type,
            "is_enabled": item.is_enabled,
            "days_offset": item.days_offset,
            "script": item.script,
            "updated_by": user_id,
        }, on_conflict="business_id,channel,type").execute()

    return {"success": True, "updated": len(body.settings)}
