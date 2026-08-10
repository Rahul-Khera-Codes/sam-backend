"""Mission Control Super Admin endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.auth import require_platform_super_admin
from app.core.supabase import supabase_admin
from app.routers.command_center_mock import _companies, _mission_dashboard

router = APIRouter(prefix="/mission-control", tags=["mission-control"])


class StartImpersonationRequest(BaseModel):
    target_business_id: str
    reason: str | None = None


class EndImpersonationRequest(BaseModel):
    session_id: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request_metadata(request: Request) -> dict[str, Any]:
    user_agent = request.headers.get("user-agent", "")
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else None)
    return {
        "ip_address": client_ip,
        "browser": user_agent[:500],
        "metadata": {
            "path": str(request.url.path),
            "method": request.method,
        },
    }


def _write_audit(
    *,
    actor_user_id: str,
    action: str,
    request: Request,
    target_business_id: str | None = None,
    impersonation_session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    request_meta = _request_metadata(request)
    audit_metadata = {**request_meta["metadata"], **(metadata or {})}
    supabase_admin.table("platform_audit_logs").insert(
        {
            "actor_user_id": actor_user_id,
            "action": action,
            "target_business_id": target_business_id,
            "impersonation_session_id": impersonation_session_id,
            "ip_address": request_meta["ip_address"],
            "browser": request_meta["browser"],
            "metadata": audit_metadata,
        }
    ).execute()


def _business_by_id(business_id: str) -> dict[str, Any]:
    response = (
        supabase_admin.table("businesses")
        .select("id,name,type,phone,email,address,website,country,created_at,is_deleted,stripe_subscription_status,subscription_period_end")
        .eq("id", business_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Target company not found")
    business = response.data[0]
    if business.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Cannot impersonate a deactivated company")
    return business


def _company_from_business(row: dict[str, Any], index: int) -> dict[str, Any]:
    status = "Active" if not row.get("is_deleted") else "Cancelled"
    plan = ["Starter", "Growth", "Scale", "Enterprise"][index % 4]
    return {
        "id": row["id"],
        "name": row.get("name") or "Unnamed Company",
        "owner": "Account Owner",
        "email": row.get("email") or "admin@example.com",
        "phone": row.get("phone") or "+1 555 000 0000",
        "industry": row.get("type") or "General",
        "country": row.get("country") or "US",
        "province": "N/A",
        "accountStatus": status,
        "subscriptionStatus": "Paid" if row.get("stripe_subscription_status") in {"active", "trialing"} else "Trial",
        "plan": plan,
        "renewalDate": (row.get("subscription_period_end") or _now().date().isoformat())[:10],
        "createdDate": (row.get("created_at") or _now().isoformat())[:10],
        "lastLogin": _now().date().isoformat(),
        "activeUsers": 4 + (index % 8) * 3,
        "voiceMinutes": 420 + index * 137,
        "apiCalls": 8500 + index * 1940,
        "storageUsedGb": round(12 + index * 2.8, 1),
        "aiEmployees": ["Voice", "Marketing", "Sales", "HR", "Executive"][: 1 + (index % 5)],
        "healthScore": max(42, min(98, 94 - (index % 8) * 6)),
        "mrr": [299, 599, 1299, 2499][index % 4],
    }


def _list_real_companies() -> list[dict[str, Any]]:
    response = (
        supabase_admin.table("businesses")
        .select("id,name,type,phone,email,address,website,country,created_at,is_deleted,stripe_subscription_status,subscription_period_end")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = [row for row in (response.data or []) if not row.get("is_deleted")]
    return [_company_from_business(row, index) for index, row in enumerate(rows)]


def _session_response(row: dict[str, Any], business: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "actorUserId": row["actor_user_id"],
        "targetBusinessId": row["target_business_id"],
        "targetBusinessName": business.get("name") or "Unnamed Company",
        "status": row["status"],
        "startedAt": row["started_at"],
        "expiresAt": row["expires_at"],
        "endedAt": row.get("ended_at"),
        "reason": row.get("reason"),
    }


@router.get("/dashboard")
async def get_mission_control_dashboard(actor_user_id: str = Depends(require_platform_super_admin)):
    return _mission_dashboard()


@router.get("/companies")
async def get_mission_control_companies(actor_user_id: str = Depends(require_platform_super_admin)):
    companies = _list_real_companies()
    return companies or _companies()


@router.post("/impersonation/start")
async def start_impersonation(
    request: Request,
    body: StartImpersonationRequest,
    actor_user_id: str = Depends(require_platform_super_admin),
):
    business = _business_by_id(body.target_business_id)
    expires_at = _now() + timedelta(hours=2)

    existing = (
        supabase_admin.table("impersonation_sessions")
        .update({"status": "ended", "ended_at": _now().isoformat(), "updated_at": _now().isoformat()})
        .eq("actor_user_id", actor_user_id)
        .eq("status", "active")
        .execute()
    )

    response = (
        supabase_admin.table("impersonation_sessions")
        .insert(
            {
                "actor_user_id": actor_user_id,
                "target_business_id": body.target_business_id,
                "reason": body.reason,
                "expires_at": expires_at.isoformat(),
                "metadata": {"replaced_active_sessions": len(existing.data or [])},
            }
        )
        .execute()
    )
    session = response.data[0]
    _write_audit(
        actor_user_id=actor_user_id,
        action="impersonation_started",
        request=request,
        target_business_id=body.target_business_id,
        impersonation_session_id=session["id"],
        metadata={"target_business_name": business.get("name"), "reason": body.reason},
    )
    return _session_response(session, business)


@router.get("/impersonation/current")
async def get_current_impersonation(actor_user_id: str = Depends(require_platform_super_admin)):
    response = (
        supabase_admin.table("impersonation_sessions")
        .select("*")
        .eq("actor_user_id", actor_user_id)
        .eq("status", "active")
        .gt("expires_at", _now().isoformat())
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return {"session": None}
    session = response.data[0]
    business = _business_by_id(session["target_business_id"])
    return {"session": _session_response(session, business)}


@router.post("/impersonation/end")
async def end_impersonation(
    request: Request,
    body: EndImpersonationRequest,
    actor_user_id: str = Depends(require_platform_super_admin),
):
    existing = (
        supabase_admin.table("impersonation_sessions")
        .select("*")
        .eq("id", body.session_id)
        .eq("actor_user_id", actor_user_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Active impersonation session not found")

    session = existing.data[0]
    updated = (
        supabase_admin.table("impersonation_sessions")
        .update({"status": "ended", "ended_at": _now().isoformat(), "updated_at": _now().isoformat()})
        .eq("id", body.session_id)
        .execute()
    )
    business = _business_by_id(session["target_business_id"])
    _write_audit(
        actor_user_id=actor_user_id,
        action="impersonation_ended",
        request=request,
        target_business_id=session["target_business_id"],
        impersonation_session_id=body.session_id,
        metadata={"target_business_name": business.get("name")},
    )
    return _session_response(updated.data[0], business)


@router.get("/audit-logs")
async def get_mission_control_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    actor_user_id: str = Depends(require_platform_super_admin),
):
    response = (
        supabase_admin.table("platform_audit_logs")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"items": response.data or []}
