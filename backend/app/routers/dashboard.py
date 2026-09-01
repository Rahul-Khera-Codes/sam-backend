import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from app.core.auth import require_business_access
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _apply_location_filter(query, location_id: Optional[str]):
    """Apply location_id filter: eq if provided, is null if not. Local copy of the
    convention duplicated across settings.py/gmail_integrations.py -- no shared
    util module exists yet for it."""
    if location_id:
        return query.eq("location_id", location_id)
    return query.is_("location_id", "null")


def _time_ago(iso_str: Optional[str]) -> str:
    if not iso_str:
        return ""
    try:
        created_at = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return ""
    diff = datetime.now(timezone.utc) - created_at
    minutes = int(diff.total_seconds() / 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


@router.get("/activity-feed")
async def get_activity_feed(
    business_id: str,
    location_id: Optional[str] = None,
    limit: int = 20,
    _: str = Depends(require_business_access()),
):
    """Merged, time-sorted feed across calls/appointments/payments/marketing/HR.

    Sequential fan-out queries (no asyncio.gather -- there's no precedent for it
    in this codebase, and 5 LIMIT-`limit` indexed queries is fast enough for a
    dashboard load; revisit only if this becomes a hot polled path).
    `marketing_scheduled_posts` and `hr_job_applications` have no location_id
    column, so `location_id` only narrows calls/appointments/payments -- those two
    sources are always business-wide regardless of the param.
    """
    items: list[dict] = []

    calls_query = (
        supabase_admin.table("calls")
        .select("id, caller_name, caller_phone, status, direction, created_at")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if location_id:
        calls_query = calls_query.eq("location_id", location_id)
    for call in calls_query.execute().data or []:
        caller = call.get("caller_name") or call.get("caller_phone") or "Unknown caller"
        status = call.get("status") or ""
        title_map = {
            "completed": f"Call answered — {caller}",
            "missed": f"Missed call — {caller}",
            "forwarded": f"Call forwarded — {caller}",
            "failed": f"Call failed — {caller}",
        }
        items.append({
            "type": "call",
            "title": title_map.get(status, f"Call — {caller}"),
            "description": f"{(call.get('direction') or 'inbound').capitalize()} call",
            "timestamp": call["created_at"],
            "time_ago": _time_ago(call["created_at"]),
            "module_tag": "Customer Service",
        })

    appts_query = (
        supabase_admin.table("appointments")
        .select("id, client_name, service, created_at")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if location_id:
        appts_query = appts_query.eq("location_id", location_id)
    for appt in appts_query.execute().data or []:
        if not appt.get("created_at"):
            continue
        items.append({
            "type": "appointment",
            "title": f"Appointment booked — {appt.get('client_name') or 'Client'}",
            "description": appt.get("service"),
            "timestamp": appt["created_at"],
            "time_ago": _time_ago(appt["created_at"]),
            "module_tag": "Calendar",
        })

    payments_query = (
        supabase_admin.table("appointment_payments")
        .select("id, appointment_id")
        .eq("business_id", business_id)
    )
    if location_id:
        payments_query = payments_query.eq("location_id", location_id)
    payments = payments_query.execute().data or []
    payments_by_id = {p["id"]: p for p in payments}
    payment_ids = list(payments_by_id.keys())

    if payment_ids:
        entries = (
            supabase_admin.table("appointment_payment_entries")
            .select("appointment_payment_id, amount, payment_type, paid_at")
            .eq("business_id", business_id)
            .in_("appointment_payment_id", payment_ids)
            .order("paid_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        appointment_ids = list({
            payments_by_id[e["appointment_payment_id"]]["appointment_id"]
            for e in entries
            if e.get("appointment_payment_id") in payments_by_id
        })
        appt_names: dict[str, str] = {}
        if appointment_ids:
            appt_rows = (
                supabase_admin.table("appointments")
                .select("id, client_name")
                .in_("id", appointment_ids)
                .execute()
                .data
                or []
            )
            appt_names = {a["id"]: a.get("client_name") or "Client" for a in appt_rows}
        for entry in entries:
            if not entry.get("paid_at"):
                continue
            payment = payments_by_id.get(entry["appointment_payment_id"])
            if not payment:
                continue
            client_name = appt_names.get(payment.get("appointment_id"), "Client")
            items.append({
                "type": "payment",
                "title": f"${float(entry.get('amount') or 0):.2f} collected — {client_name}",
                "description": (entry.get("payment_type") or "").replace("_", " ").title() or None,
                "timestamp": entry["paid_at"],
                "time_ago": _time_ago(entry["paid_at"]),
                "module_tag": "Payments",
            })

    # marketing_scheduled_posts and hr_job_applications have no location_id column
    # -- always business-wide, regardless of the location_id param above.
    posts = (
        supabase_admin.table("marketing_scheduled_posts")
        .select("id, caption, platforms, published_at, updated_at")
        .eq("business_id", business_id)
        .eq("status", "published")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    for post in posts:
        timestamp = post.get("published_at") or post.get("updated_at")
        if not timestamp:
            continue
        platforms = ", ".join(post.get("platforms") or []) or "social"
        items.append({
            "type": "marketing_post",
            "title": f"Post published — {platforms}",
            "description": (post.get("caption") or "")[:80] or None,
            "timestamp": timestamp,
            "time_ago": _time_ago(timestamp),
            "module_tag": "Marketing",
        })

    applications = (
        supabase_admin.table("hr_job_applications")
        .select("id, candidate_name, submitted_at")
        .eq("business_id", business_id)
        .order("submitted_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    for app_row in applications:
        items.append({
            "type": "candidate",
            "title": f"Candidate applied — {app_row.get('candidate_name') or 'Candidate'}",
            "description": None,
            "timestamp": app_row["submitted_at"],
            "time_ago": _time_ago(app_row["submitted_at"]),
            "module_tag": "HR",
        })

    items.sort(key=lambda i: i["timestamp"], reverse=True)
    return {"items": items[:limit]}


def _row_exists(
    table: str,
    business_id: str,
    apply_location: bool,
    location_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> bool:
    query = supabase_admin.table(table).select("id").eq("business_id", business_id)
    if extra:
        for key, value in extra.items():
            query = query.eq(key, value)
    if apply_location:
        query = _apply_location_filter(query, location_id)
    return bool(query.limit(1).execute().data)


@router.get("/setup-checklist")
async def get_setup_checklist(
    business_id: str,
    location_id: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    """Six independent existence checks, computed at read time -- nothing is
    stored for the checklist itself, since every underlying fact already lives in
    an existing table.

    `business_hours` is checked as a raw row-count, NOT via
    GET /settings/agent/schedule, which silently backfills a default schedule when
    no rows exist and so can't distinguish "configured" from "never touched".

    google_calendar_tokens, marketing_platform_integrations, and hr_job_postings
    have no location_id column -- those three checks are inherently business-wide
    regardless of the location_id param; only phone-number, business-hours, and
    knowledge-base checks are actually location-scoped.
    """
    phone_done = _row_exists(
        "business_phone_numbers", business_id, True, location_id, {"is_active": True}
    )
    hours_done = _row_exists("business_hours", business_id, True, location_id)
    kb_done = _row_exists("business_documents", business_id, True, location_id)
    calendar_done = _row_exists("google_calendar_tokens", business_id, False)
    instagram_done = _row_exists(
        "marketing_platform_integrations",
        business_id,
        False,
        extra={"provider": "instagram", "is_connected": True},
    )
    # Greenhouse was fully removed from the product -- this checklist item is
    # replaced by "publish your first job posting" against the native pipeline.
    job_posting_done = _row_exists(
        "hr_job_postings", business_id, False, extra={"status": "active"}
    )

    items = [
        {
            "id": "phone_number",
            "label": "Claim a phone number",
            "completed": phone_done,
            "action_label": "Claim",
            "action_href": "/dashboard/phone-numbers",
        },
        {
            "id": "business_hours",
            "label": "Set business hours",
            "completed": hours_done,
            "action_label": "Set hours",
            "action_href": "/dashboard/customer-service/scheduler",
        },
        {
            "id": "google_calendar",
            "label": "Connect Google Calendar",
            "completed": calendar_done,
            "action_label": "Connect",
            "action_href": "/dashboard/account-settings",
        },
        {
            "id": "instagram",
            "label": "Connect Instagram",
            "completed": instagram_done,
            "action_label": "Connect",
            "action_href": "/dashboard/marketing",
        },
        {
            "id": "knowledge_base",
            "label": "Finish knowledge base",
            "completed": kb_done,
            "action_label": "Upload",
            "action_href": "/dashboard/business-settings",
        },
        {
            "id": "job_posting",
            "label": "Publish your first job posting",
            "completed": job_posting_done,
            "action_label": "Post a job",
            "action_href": "/dashboard/hr",
        },
    ]
    completed_count = sum(1 for item in items if item["completed"])
    return {"items": items, "completed_count": completed_count, "total_count": len(items)}
