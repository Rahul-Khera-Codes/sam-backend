"""
Locations Router — seed endpoint for newly created locations.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id
from app.core.supabase import supabase_admin
from app.services import location_seed_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/locations", tags=["locations"])


@router.post("/{location_id}/seed")
async def seed_location(
    location_id: str,
    user_id: str = Depends(get_user_id),
):
    """
    Seed a newly created location with business-wide default data.
    Call this immediately after creating a location.
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

    business_id = role_row.data[0]["business_id"]

    loc = (
        supabase_admin.table("locations")
        .select("id")
        .eq("id", location_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not loc.data:
        raise HTTPException(status_code=404, detail="Location not found")

    summary = await location_seed_service.seed_location_data(business_id, location_id)
    return {"seeded": True, "summary": summary}
