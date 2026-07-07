"""
Sales Employee router — Report Scheduler module.

CRUD for report_schedules, plus:
GET  /sales/report-scheduler/schedules/{id}/preview    — build (don't send) the digest HTML
POST /sales/report-scheduler/schedules/{id}/send-test   — send a real test email to the requester

No external API calls — this module just aggregates data already produced by
Lead Researcher, Competitor Agent, and Market Agent. The actual scheduled
sending happens in a scheduler_service.py sweep job, not here.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user, get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.report_scheduler import (
    CreateScheduleRequest,
    PreviewResponse,
    ScheduleListResponse,
    ScheduleResponse,
    SendTestResponse,
    UpdateScheduleRequest,
)
from app.services import email_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales/report-scheduler", tags=["sales"])


def _schedule_row_to_response(row: dict) -> ScheduleResponse:
    return ScheduleResponse(
        id=row["id"],
        business_id=row["business_id"],
        name=row["name"],
        frequency=row["frequency"],
        recipients=row.get("recipients") or [],
        include_lead_researcher=row["include_lead_researcher"],
        include_competitor_agent=row["include_competitor_agent"],
        include_market_agent=row["include_market_agent"],
        is_active=row["is_active"],
        last_sent_at=row.get("last_sent_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def build_digest_data(schedule: dict) -> dict:
    """Gathers the data for a digest based on a schedule's included modules.
    Shared by preview, send-test, and the scheduled sweep job."""
    business_id = schedule["business_id"]
    last_sent_at = schedule.get("last_sent_at")

    lead_researcher_items = []
    if schedule["include_lead_researcher"]:
        query = (
            supabase_admin.table("lead_lookups")
            .select("enriched_result_json")
            .eq("business_id", business_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
        )
        if last_sent_at:
            query = query.gte("created_at", last_sent_at)
        else:
            query = query.limit(5)
        rows = query.execute().data
        lead_researcher_items = [r["enriched_result_json"] for r in rows if r.get("enriched_result_json")]

    competitor_agent_items = []
    if schedule["include_competitor_agent"]:
        competitors = (
            supabase_admin.table("competitors").select("id,name").eq("business_id", business_id).execute().data
        )
        for comp in competitors:
            latest = (
                supabase_admin.table("competitor_reports")
                .select("report_json,created_at")
                .eq("competitor_id", comp["id"])
                .eq("status", "completed")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
            if latest and latest[0].get("report_json"):
                competitor_agent_items.append(
                    {
                        "competitor_name": comp.get("name") or "Competitor",
                        "overview": latest[0]["report_json"].get("overview"),
                    }
                )

    market_agent_summary = None
    market_agent_items = []
    if schedule["include_market_agent"]:
        latest_run = (
            supabase_admin.table("market_analysis_runs")
            .select("id,whats_changing_summary")
            .eq("business_id", business_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if latest_run:
            market_agent_summary = latest_run[0].get("whats_changing_summary")
            cards = (
                supabase_admin.table("market_analysis_cards")
                .select("analyst_name,headline")
                .eq("run_id", latest_run[0]["id"])
                .eq("status", "completed")
                .execute()
                .data
            )
            market_agent_items = cards

    return {
        "lead_researcher_items": lead_researcher_items,
        "competitor_agent_items": competitor_agent_items,
        "market_agent_summary": market_agent_summary,
        "market_agent_items": market_agent_items,
    }


async def send_digest(schedule: dict, recipients: list[str]) -> bool:
    """Builds and sends the digest to the given recipients. Used by both
    send-test (one recipient, the requester) and the scheduled sweep (all
    configured recipients)."""
    biz = (
        supabase_admin.table("businesses").select("name").eq("id", schedule["business_id"]).limit(1).execute().data
    )
    business_name = biz[0]["name"] if biz else "Your business"

    data = build_digest_data(schedule)
    subject, html_body = email_service.build_sales_digest_email(
        business_name=business_name,
        lead_researcher_items=data["lead_researcher_items"],
        competitor_agent_items=data["competitor_agent_items"],
        market_agent_summary=data["market_agent_summary"],
        market_agent_items=data["market_agent_items"],
    )

    access_token = await email_service.get_valid_access_token(
        supabase_admin, schedule["business_id"], settings.google_client_id, settings.google_client_secret
    )
    if not access_token:
        logger.info("Gmail not connected for business %s — cannot send digest", schedule["business_id"])
        return False

    token_row = email_service.get_token_row(supabase_admin, schedule["business_id"])
    sender = token_row["google_email"] if token_row else "noreply@example.com"

    sent_any = False
    for recipient in recipients:
        try:
            sent = await email_service.send_email(
                access_token=access_token,
                sender=f"{business_name} <{sender}>",
                to=recipient,
                subject=subject,
                html_body=html_body,
            )
            sent_any = sent_any or sent
        except Exception as e:
            logger.error("Digest send failed for %s: %s", recipient, e)
    return sent_any


@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    body: CreateScheduleRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    if body.frequency not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="frequency must be daily, weekly, or monthly.")

    row = (
        supabase_admin.table("report_schedules")
        .insert(
            {
                "business_id": body.business_id,
                "name": body.name,
                "frequency": body.frequency,
                "recipients": body.recipients,
                "include_lead_researcher": body.include_lead_researcher,
                "include_competitor_agent": body.include_competitor_agent,
                "include_market_agent": body.include_market_agent,
                "is_active": body.is_active,
            }
        )
        .execute()
        .data[0]
    )
    return _schedule_row_to_response(row)


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_schedules(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    rows = (
        supabase_admin.table("report_schedules")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return ScheduleListResponse(schedules=[_schedule_row_to_response(r) for r in rows])


async def _get_schedule_or_404(schedule_id: str, user_id: str) -> dict:
    row_result = supabase_admin.table("report_schedules").select("*").eq("id", schedule_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])
    return row


@router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    body: UpdateScheduleRequest,
    user_id: str = Depends(get_user_id),
):
    await _get_schedule_or_404(schedule_id, user_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "frequency" in updates and updates["frequency"] not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="frequency must be daily, weekly, or monthly.")
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updated = supabase_admin.table("report_schedules").update(updates).eq("id", schedule_id).execute()
    return _schedule_row_to_response(updated.data[0])


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user_id: str = Depends(get_user_id),
):
    await _get_schedule_or_404(schedule_id, user_id)
    supabase_admin.table("report_schedules").delete().eq("id", schedule_id).execute()
    return {"ok": True}


@router.get("/schedules/{schedule_id}/preview", response_model=PreviewResponse)
async def preview_schedule(
    schedule_id: str,
    user_id: str = Depends(get_user_id),
):
    schedule = await _get_schedule_or_404(schedule_id, user_id)
    biz = supabase_admin.table("businesses").select("name").eq("id", schedule["business_id"]).limit(1).execute().data
    business_name = biz[0]["name"] if biz else "Your business"

    data = build_digest_data(schedule)
    subject, html_body = email_service.build_sales_digest_email(
        business_name=business_name,
        lead_researcher_items=data["lead_researcher_items"],
        competitor_agent_items=data["competitor_agent_items"],
        market_agent_summary=data["market_agent_summary"],
        market_agent_items=data["market_agent_items"],
    )
    return PreviewResponse(subject=subject, html_body=html_body)


@router.post("/schedules/{schedule_id}/send-test", response_model=SendTestResponse)
async def send_test_email(
    schedule_id: str,
    user_id: str = Depends(get_user_id),
    current_user: dict = Depends(get_current_user),
):
    schedule = await _get_schedule_or_404(schedule_id, user_id)
    test_recipient = current_user.get("email")
    if not test_recipient:
        raise HTTPException(status_code=400, detail="Could not determine your email from your login.")

    sent = await send_digest(schedule, [test_recipient])
    if not sent:
        return SendTestResponse(sent=False, detail="Gmail is not connected for this business, or the send failed.")
    return SendTestResponse(sent=True, detail=f"Test email sent to {test_recipient}.")
