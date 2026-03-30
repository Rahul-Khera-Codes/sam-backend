"""
Phone Numbers Router
====================
Endpoints for searching, provisioning, and releasing Twilio phone numbers.
All endpoints require a valid JWT (authenticated business admin).
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import get_current_user, get_user_id
from app.core.supabase import supabase_admin
from app.services import phone_number_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/phone-numbers", tags=["phone-numbers"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProvisionRequest(BaseModel):
    phone_number: str           # E.164 e.g. "+14155550100"
    location_id: Optional[str] = None


# ── GET /phone-numbers/search ─────────────────────────────────────────────────

@router.get("/search")
async def search_numbers(
    area_code: Optional[str] = None,
    country: str = "US",
    limit: int = 10,
    current_user: dict = Depends(get_current_user),
):
    """
    Search available Twilio phone numbers to purchase.
    Query params: area_code (optional), country (default US), limit (default 10).
    """
    try:
        numbers = phone_number_service.search_available_numbers(
            area_code=area_code,
            country=country,
            limit=limit,
        )
        return {"numbers": numbers}
    except Exception as e:
        logger.error(f"[phone-numbers/search] {e}")
        raise HTTPException(status_code=502, detail=f"Twilio search failed: {str(e)}")


# ── POST /phone-numbers/provision ─────────────────────────────────────────────

@router.post("/provision", status_code=201)
async def provision_number(
    body: ProvisionRequest,
    current_user: dict = Depends(get_current_user),
    user_id: str = Depends(get_user_id),
):
    """
    Purchase a phone number and wire it to the business's LiveKit dispatch rule.
    Body: { phone_number: "+14155550100", location_id?: "uuid" }
    """
    # Resolve business_id + role from user_roles
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
        raise HTTPException(status_code=403, detail="Only admins can provision phone numbers")

    business_id = role_row.data[0]["business_id"]

    # Guard: one active number per location (or per business if no location)
    existing = phone_number_service.get_phone_numbers_for_business(business_id)
    for row in existing:
        if row.get("location_id") == body.location_id:
            raise HTTPException(
                status_code=409,
                detail=f"This business/location already has an active number: {row['phone_number']}",
            )

    try:
        row = await phone_number_service.provision_phone_number(
            business_id=business_id,
            location_id=body.location_id,
            phone_number=body.phone_number,
        )
        return row
    except Exception as e:
        logger.error(f"[phone-numbers/provision] {e}")
        raise HTTPException(status_code=502, detail=f"Provisioning failed: {str(e)}")


# ── GET /phone-numbers ────────────────────────────────────────────────────────

@router.get("")
async def list_numbers(
    current_user: dict = Depends(get_current_user),
    user_id: str = Depends(get_user_id),
):
    """Returns all active phone numbers for the caller's business."""
    role_row = (
        supabase_admin.table("user_roles")
        .select("business_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not role_row.data:
        raise HTTPException(status_code=403, detail="User has no role assigned")

    numbers = phone_number_service.get_phone_numbers_for_business(role_row.data[0]["business_id"])
    return {"numbers": numbers}


# ── DELETE /phone-numbers/{id} ────────────────────────────────────────────────

@router.delete("/{phone_number_id}")
async def release_number(
    phone_number_id: str,
    current_user: dict = Depends(get_current_user),
    user_id: str = Depends(get_user_id),
):
    """
    Release a phone number: deletes LiveKit dispatch rule + releases Twilio number.
    Soft-deletes the DB row (is_active=False).
    """
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
        raise HTTPException(status_code=403, detail="Only admins can release phone numbers")

    # Verify ownership
    row_check = (
        supabase_admin.table("business_phone_numbers")
        .select("id")
        .eq("id", phone_number_id)
        .eq("business_id", role_row.data[0]["business_id"])
        .execute()
    )
    if not row_check.data:
        raise HTTPException(status_code=404, detail="Phone number not found")

    try:
        updated = await phone_number_service.release_phone_number(phone_number_id)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[phone-numbers/release] {e}")
        raise HTTPException(status_code=502, detail=f"Release failed: {str(e)}")
