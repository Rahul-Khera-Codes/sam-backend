"""
Business Branding router.

GET   /business/branding   — fetch a business's branding data (empty defaults if none saved yet)
PATCH /business/branding   — upsert branding fields

Feeds Market Agent's industry/business context (mission + target_niche) —
see docs/superpowers/specs/2026-07-10-business-branding-section.md.
"""
from fastapi import APIRouter, Depends, Query

from app.core.auth import get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.schemas.business_branding import BusinessBrandingResponse, UpdateBusinessBrandingRequest

router = APIRouter(prefix="/business/branding", tags=["business-branding"])


@router.get("", response_model=BusinessBrandingResponse)
async def get_business_branding(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    result = (
        supabase_admin.table("business_branding")
        .select("*")
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if result.data:
        return BusinessBrandingResponse(**result.data[0])
    return BusinessBrandingResponse(business_id=business_id)


@router.patch("", response_model=BusinessBrandingResponse)
async def update_business_branding(
    body: UpdateBusinessBrandingRequest,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    row = {"business_id": business_id, **updates}

    result = (
        supabase_admin.table("business_branding")
        .upsert(row, on_conflict="business_id")
        .execute()
    )
    return BusinessBrandingResponse(**result.data[0])
