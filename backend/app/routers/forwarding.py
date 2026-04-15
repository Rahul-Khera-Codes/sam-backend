from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user, get_user_id, require_business_access, verify_business_access
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
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase.table("forwarding_contacts")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=False)
    )
    if location_id:
        query = query.eq("location_id", location_id)
    result = query.execute()
    return result.data or []


@router.post("/contacts", response_model=ForwardingContactResponse)
async def create_contact(
    business_id: str,
    body: CreateForwardingContactRequest,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    result = supabase_admin.table("forwarding_contacts").insert({
        "business_id": business_id,
        "location_id": body.location_id,
        "name": body.name,
        "phone": body.phone,
        "department_tag": body.department_tag,
        "priority": body.priority,
        "forwarding_rule": body.forwarding_rule,
        "is_active": True,
    }).execute()

    return result.data[0]


def _verify_contact_access(contact_id: str, user_id: str) -> None:
    """Verify the authenticated user has access to the contact's business."""
    row = (
        supabase_admin.table("forwarding_contacts")
        .select("business_id").eq("id", contact_id).limit(1).execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Contact not found")
    verify_business_access(user_id, row.data[0]["business_id"])


def _verify_rule_access(rule_id: str, user_id: str) -> None:
    row = (
        supabase_admin.table("forwarding_rules")
        .select("business_id").eq("id", rule_id).limit(1).execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Rule not found")
    verify_business_access(user_id, row.data[0]["business_id"])


@router.put("/contacts/{contact_id}", response_model=ForwardingContactResponse)
async def update_contact(
    contact_id: str,
    body: UpdateForwardingContactRequest,
    user_id: str = Depends(get_user_id),
):
    _verify_contact_access(contact_id, user_id)

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
    user_id: str = Depends(get_user_id),
):
    _verify_contact_access(contact_id, user_id)
    supabase_admin.table("forwarding_contacts").delete().eq("id", contact_id).execute()
    return {"success": True}


@router.put("/contacts/bulk/toggle")
async def bulk_toggle_contacts(
    business_id: str,
    body: dict,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = supabase_admin.table("forwarding_contacts").update(
        {"is_active": body.get("is_active")}
    ).eq("business_id", business_id)
    if location_id:
        query = query.eq("location_id", location_id)
    query.execute()

    return {"success": True}


@router.put("/contacts/{contact_id}/toggle")
async def toggle_contact(
    contact_id: str,
    body: dict,
    user_id: str = Depends(get_user_id),
):
    _verify_contact_access(contact_id, user_id)
    result = (
        supabase_admin.table("forwarding_contacts")
        .update({"is_active": body.get("is_active")})
        .eq("id", contact_id)
        .execute()
    )
    return result.data[0]


# ── RULES ─────────────────────────────────────

@router.get("/rules", response_model=List[ForwardingRuleResponse])
async def list_rules(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    query = (
        supabase.table("forwarding_rules")
        .select("*")
        .eq("business_id", business_id)
        .order("priority_order")
    )
    if location_id:
        query = query.eq("location_id", location_id)
    result = query.execute()
    return result.data or []


@router.post("/rules", response_model=ForwardingRuleResponse)
async def create_rule(
    business_id: str,
    body: CreateForwardingRuleRequest,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    result = supabase_admin.table("forwarding_rules").insert({
        "business_id": business_id,
        "location_id": body.location_id,
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
    user_id: str = Depends(get_user_id),
):
    _verify_rule_access(rule_id, user_id)
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
    user_id: str = Depends(get_user_id),
):
    _verify_rule_access(rule_id, user_id)
    supabase_admin.table("forwarding_rules").delete().eq("id", rule_id).execute()
    return {"success": True}
