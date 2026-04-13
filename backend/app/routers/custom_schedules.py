"""
Custom Schedules API — admin/super_admin only.

CRUD for agent custom schedules per (business_id, location_id).
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id, get_current_user
from app.core.supabase import supabase_admin
from app.schemas.custom_schedules import (
    CreateCustomScheduleRequest,
    UpdateCustomScheduleRequest,
    CustomScheduleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom-schedules", tags=["custom-schedules"])


def _require_admin(user_id: str) -> str:
    """Verify user is admin/super_admin and return their business_id."""
    role_row = (
        supabase_admin.table("user_roles")
        .select("business_id, role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not role_row.data:
        raise HTTPException(status_code=403, detail="User has no role assigned")
    if role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can manage custom schedules")
    return role_row.data[0]["business_id"]


def _verify_location(business_id: str, location_id: str) -> None:
    result = (
        supabase_admin.table("locations")
        .select("id")
        .eq("id", location_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Location not found for this business")


# ── GET /custom-schedules ─────────────────────────────────────────────────────

@router.get("", response_model=List[CustomScheduleResponse])
async def list_custom_schedules(
    location_id: str,
    current_user: dict = Depends(get_current_user),
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)
    _verify_location(business_id, location_id)

    result = (
        supabase_admin.table("custom_schedules")
        .select("*")
        .eq("business_id", business_id)
        .eq("location_id", location_id)
        .order("priority", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


# ── POST /custom-schedules ────────────────────────────────────────────────────

@router.post("", response_model=CustomScheduleResponse, status_code=201)
async def create_custom_schedule(
    body: CreateCustomScheduleRequest,
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)
    _verify_location(business_id, body.location_id)

    row = body.model_dump()
    row["business_id"] = business_id
    row["created_by"] = user_id
    if row["start_date"]:
        row["start_date"] = row["start_date"].isoformat()
    if row["end_date"]:
        row["end_date"] = row["end_date"].isoformat()

    result = supabase_admin.table("custom_schedules").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create custom schedule")
    return result.data[0]


# ── PATCH /custom-schedules/{id} ──────────────────────────────────────────────

@router.patch("/{schedule_id}", response_model=CustomScheduleResponse)
async def update_custom_schedule(
    schedule_id: str,
    body: UpdateCustomScheduleRequest,
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)

    # Verify row exists and belongs to this business
    existing = (
        supabase_admin.table("custom_schedules")
        .select("id, business_id")
        .eq("id", schedule_id)
        .limit(1)
        .execute()
    )
    if not existing.data or existing.data[0]["business_id"] != business_id:
        raise HTTPException(status_code=404, detail="Custom schedule not found")

    updates = body.model_dump(exclude_unset=True)
    if "start_date" in updates and updates["start_date"]:
        updates["start_date"] = updates["start_date"].isoformat()
    if "end_date" in updates and updates["end_date"]:
        updates["end_date"] = updates["end_date"].isoformat()

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        supabase_admin.table("custom_schedules")
        .update(updates)
        .eq("id", schedule_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update custom schedule")
    return result.data[0]


# ── DELETE /custom-schedules/{id} ─────────────────────────────────────────────

@router.delete("/{schedule_id}")
async def delete_custom_schedule(
    schedule_id: str,
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)

    existing = (
        supabase_admin.table("custom_schedules")
        .select("id, business_id")
        .eq("id", schedule_id)
        .limit(1)
        .execute()
    )
    if not existing.data or existing.data[0]["business_id"] != business_id:
        raise HTTPException(status_code=404, detail="Custom schedule not found")

    supabase_admin.table("custom_schedules").delete().eq("id", schedule_id).execute()
    return {"deleted": True}
