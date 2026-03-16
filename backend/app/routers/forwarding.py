from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user, get_user_id
from app.core.supabase import supabase, supabase_admin
from app.schemas.settings import (
    ForwardingContactResponse,
    CreateForwardingContactRequest,
    UpdateForwardingContactRequest,
    ForwardingRuleResponse,
    CreateForwardingRuleRequest,
)
from typing import List

router = APIRouter(prefix="/forwarding", tags=["forwarding"])


# ── CONTACTS ──────────────────────────────────

@router.get("/contacts", response_model=List[ForwardingContactResponse])
async def list_contacts(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("forwarding_contacts")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


@router.post("/contacts", response_model=ForwardingContactResponse)
async def create_contact(
    business_id: str,
    body: CreateForwardingContactRequest,
    user_id: str = Depends(get_user_id),
):
    result = supabase_admin.table("forwarding_contacts").insert({
        "business_id": business_id,
        "location_id": body.location_id,
        "name": body.name,
        "phone": body.phone,
        "department_tag": body.department_tag,
        "priority": body.priority,
        "is_active": True,
    }).execute()

    return result.data[0]


@router.put("/contacts/{contact_id}", response_model=ForwardingContactResponse)
async def update_contact(
    contact_id: str,
    body: UpdateForwardingContactRequest,
    current_user: dict = Depends(get_current_user),
):
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        supabase_admin.table("forwarding_contacts")
        .update(update_data)
        .eq("id", contact_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Contact not found")

    return result.data[0]


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: str,
    current_user: dict = Depends(get_current_user),
):
    supabase_admin.table("forwarding_contacts").delete().eq("id", contact_id).execute()
    return {"success": True}


@router.put("/contacts/{contact_id}/toggle")
async def toggle_contact(
    contact_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase_admin.table("forwarding_contacts")
        .update({"is_active": body.get("is_active")})
        .eq("id", contact_id)
        .execute()
    )
    return result.data[0]


@router.put("/contacts/bulk/toggle")
async def bulk_toggle_contacts(
    business_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    supabase_admin.table("forwarding_contacts").update(
        {"is_active": body.get("is_active")}
    ).eq("business_id", business_id).execute()

    return {"success": True}


# ── RULES ─────────────────────────────────────

@router.get("/rules", response_model=List[ForwardingRuleResponse])
async def list_rules(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("forwarding_rules")
        .select("*")
        .eq("business_id", business_id)
        .order("priority_order")
        .execute()
    )
    return result.data or []


@router.post("/rules", response_model=ForwardingRuleResponse)
async def create_rule(
    business_id: str,
    body: CreateForwardingRuleRequest,
    user_id: str = Depends(get_user_id),
):
    result = supabase_admin.table("forwarding_rules").insert({
        "business_id": business_id,
        "name": body.name,
        "condition_type": body.condition_type,
        "condition_value": body.condition_value or {},
        "action": body.action or {},
        "priority_order": body.priority_order,
        "is_active": True,
    }).execute()

    return result.data[0]


@router.put("/rules/{rule_id}", response_model=ForwardingRuleResponse)
async def update_rule(
    rule_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase_admin.table("forwarding_rules")
        .update(body)
        .eq("id", rule_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Rule not found")

    return result.data[0]


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    current_user: dict = Depends(get_current_user),
):
    supabase_admin.table("forwarding_rules").delete().eq("id", rule_id).execute()
    return {"success": True}
