"""
Sales Employee router — Lead Researcher module.

POST /sales/lead-researcher/lookup   — kick off an async Apify scrape for a LinkedIn URL
POST /sales/lead-researcher/webhook  — Apify calls this when the run finishes; we enrich + save
GET  /sales/lead-researcher/lookup/{id} — poll for status/result
GET    /sales/lead-researcher/history  — past lookups for a business
PATCH  /sales/lead-researcher/lookup/{id}/save — toggle saved
DELETE /sales/lead-researcher/lookup/{id} — delete a finished lookup
"""
import base64
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.sales import (
    LeadCardResult,
    LeadLookupCreatedResponse,
    LeadLookupHistoryResponse,
    LeadLookupRequest,
    LeadLookupResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales/lead-researcher", tags=["sales"])

APIFY_ACTOR_ID = "data-slayer~linkedin-profile-scraper"

# Real runs complete in ~2-3 min (base scrape + email lookup, live-tested). If a
# lookup is still "running" well past that, Apify's webhook likely never
# arrived (network blip, actor timeout) — don't leave the frontend polling forever.
STALE_RUNNING_TIMEOUT = timedelta(minutes=10)

ENRICHMENT_PROMPT = """You turn a raw LinkedIn profile scrape into a sales lead card.
Given the profile JSON below, return a JSON object with these exact keys:
- job_role_insights: 1-2 sentences on what this person's role likely involves and what they'd care about professionally
- pain_points_and_sales_angles: 1-2 sentences on likely pain points and how to position an outreach angle
- personal_interests: 1 sentence on any personal interests inferable from the profile (skills, volunteering, etc.) — if nothing is inferable, say "Not enough data to infer."
- best_time_to_reach: a reasonable guess (e.g. "Weekday mornings, based on typical work hours for their timezone") — this is a heuristic, not a fact
- outreach_email_draft: a short, personalized cold outreach email draft (3-4 sentences) referencing something specific from their profile

Be honest about uncertainty — do not invent specific facts not supported by the profile data."""


def _mark_stale_if_needed(row: dict) -> dict:
    if row["status"] != "running":
        return row
    updated_at = datetime.fromisoformat(row["updated_at"])
    if datetime.now(timezone.utc) - updated_at < STALE_RUNNING_TIMEOUT:
        return row

    stale_update = (
        supabase_admin.table("lead_lookups")
        .update(
            {
                "status": "failed",
                "error_message": "Timed out waiting for Apify — the webhook never arrived.",
            }
        )
        .eq("id", row["id"])
        .execute()
    )
    logger.warning("Lead lookup %s marked failed after exceeding stale timeout.", row["id"])
    return stale_update.data[0]


def _row_to_response(row: dict) -> LeadLookupResponse:
    result = None
    if row.get("enriched_result_json"):
        result = LeadCardResult(**row["enriched_result_json"])
    return LeadLookupResponse(
        id=row["id"],
        business_id=row["business_id"],
        linkedin_url=row["linkedin_url"],
        status=row["status"],
        error_message=row.get("error_message"),
        is_saved=row["is_saved"],
        result=result,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _start_apify_run(linkedin_url: str) -> dict:
    webhook_url = f"{settings.apify_webhook_base_url.rstrip('/')}/sales/lead-researcher/webhook"
    webhooks = [
        {
            "eventTypes": [
                "ACTOR.RUN.SUCCEEDED",
                "ACTOR.RUN.FAILED",
                "ACTOR.RUN.ABORTED",
                "ACTOR.RUN.TIMED_OUT",
            ],
            "requestUrl": webhook_url,
            "headersTemplate": json.dumps({"X-Webhook-Secret": settings.apify_webhook_secret}),
        }
    ]
    webhooks_b64 = base64.b64encode(json.dumps(webhooks).encode()).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.apify.com/v2/actors/{APIFY_ACTOR_ID}/runs",
            params={"webhooks": webhooks_b64},
            headers={"Authorization": f"Bearer {settings.apify_api_token}"},
            json={"linkedin_urls": [linkedin_url], "extract_email": True},
        )
        resp.raise_for_status()
        return resp.json()["data"]


@router.post("/lookup", response_model=LeadLookupCreatedResponse)
async def create_lead_lookup(
    body: LeadLookupRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)

    if not settings.apify_api_token:
        raise HTTPException(status_code=503, detail="Apify is not configured yet.")
    if not settings.apify_webhook_base_url:
        raise HTTPException(status_code=503, detail="Apify webhook base URL is not configured yet.")

    # Avoid starting a second paid Apify run for a lookup that's already in flight
    # (e.g. a double-click or an accidental duplicate request for the same URL).
    in_flight = (
        supabase_admin.table("lead_lookups")
        .select("id,status")
        .eq("business_id", body.business_id)
        .eq("linkedin_url", body.linkedin_url)
        .in_("status", ["pending", "running"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if in_flight.data:
        existing = in_flight.data[0]
        logger.info(
            "Lead lookup already in flight for this business+URL, reusing: id=%s status=%s",
            existing["id"], existing["status"],
        )
        return LeadLookupCreatedResponse(id=existing["id"], status=existing["status"])

    insert_row = (
        supabase_admin.table("lead_lookups")
        .insert(
            {
                "business_id": body.business_id,
                "user_id": user_id,
                "linkedin_url": body.linkedin_url,
                "status": "pending",
            }
        )
        .execute()
    )
    row = insert_row.data[0]

    try:
        run = await _start_apify_run(body.linkedin_url)
    except httpx.HTTPError as e:
        supabase_admin.table("lead_lookups").update(
            {"status": "failed", "error_message": f"Failed to start Apify run: {e}"}
        ).eq("id", row["id"]).execute()
        raise HTTPException(status_code=502, detail=f"Failed to start LinkedIn lookup: {e}")

    supabase_admin.table("lead_lookups").update(
        {"status": "running", "apify_run_id": run["id"]}
    ).eq("id", row["id"]).execute()

    logger.info("Lead lookup started: id=%s apify_run_id=%s", row["id"], run["id"])

    return LeadLookupCreatedResponse(id=row["id"], status="running")


class ApifyWebhookPayload(BaseModel):
    eventType: str
    resource: dict


@router.post("/webhook")
async def apify_webhook(
    payload: ApifyWebhookPayload,
    x_webhook_secret: str = Header(..., alias="X-Webhook-Secret"),
):
    if not settings.apify_webhook_secret or not secrets.compare_digest(
        x_webhook_secret, settings.apify_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook secret.")

    run_id = payload.resource.get("id")
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run id in webhook payload.")

    existing = (
        supabase_admin.table("lead_lookups").select("*").eq("apify_run_id", run_id).limit(1).execute()
    )
    if not existing.data:
        logger.warning("Apify webhook for unknown run_id=%s — ignoring.", run_id)
        return {"ok": True}
    row = existing.data[0]

    if payload.eventType != "ACTOR.RUN.SUCCEEDED":
        supabase_admin.table("lead_lookups").update(
            {"status": "failed", "error_message": f"Apify run ended with event: {payload.eventType}"}
        ).eq("id", row["id"]).execute()
        return {"ok": True}

    dataset_id = payload.resource.get("defaultDatasetId")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                headers={"Authorization": f"Bearer {settings.apify_api_token}"},
            )
            resp.raise_for_status()
            items = resp.json()
    except Exception as e:
        logger.error("Failed to fetch Apify dataset %s for lookup %s: %s", dataset_id, row["id"], e)
        supabase_admin.table("lead_lookups").update(
            {"status": "failed", "error_message": f"Failed to fetch Apify results: {e}"}
        ).eq("id", row["id"]).execute()
        return {"ok": True}

    if not items:
        supabase_admin.table("lead_lookups").update(
            {"status": "failed", "error_message": "Apify run finished but returned no profile data."}
        ).eq("id", row["id"]).execute()
        return {"ok": True}

    raw = items[0]

    try:
        enriched = await _enrich_lead(raw)
    except Exception as e:
        logger.error("Lead enrichment failed for lookup %s: %s", row["id"], e)
        supabase_admin.table("lead_lookups").update(
            {
                "status": "failed",
                "raw_scrape_json": raw,
                "error_message": f"AI enrichment failed: {e}",
            }
        ).eq("id", row["id"]).execute()
        return {"ok": True}

    supabase_admin.table("lead_lookups").update(
        {
            "status": "completed",
            "raw_scrape_json": raw,
            "enriched_result_json": enriched.model_dump(),
        }
    ).eq("id", row["id"]).execute()

    return {"ok": True}


async def _enrich_lead(raw: dict) -> LeadCardResult:
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": ENRICHMENT_PROMPT},
            {"role": "user", "content": json.dumps(raw)},
        ],
        temperature=0.3,
    )
    generated = json.loads(response.choices[0].message.content)

    return LeadCardResult(
        full_name=raw.get("full_name"),
        job_title=raw.get("job_title") or raw.get("raw_job_title"),
        company_name=raw.get("current_company_name"),
        predicted_email=raw.get("email") or None,
        email_confidence=raw.get("millionverifier_result") or None,
        job_role_insights=generated.get("job_role_insights"),
        pain_points_and_sales_angles=generated.get("pain_points_and_sales_angles"),
        personal_interests=generated.get("personal_interests"),
        best_time_to_reach=generated.get("best_time_to_reach"),
        outreach_email_draft=generated.get("outreach_email_draft"),
    )


@router.get("/lookup/{lookup_id}", response_model=LeadLookupResponse)
async def get_lead_lookup(
    lookup_id: str,
    user_id: str = Depends(get_user_id),
):
    row_result = supabase_admin.table("lead_lookups").select("*").eq("id", lookup_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Lookup not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])
    row = _mark_stale_if_needed(row)
    return _row_to_response(row)


@router.get("/history", response_model=LeadLookupHistoryResponse)
async def get_lead_lookup_history(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    rows = (
        supabase_admin.table("lead_lookups")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows.data = [_mark_stale_if_needed(r) for r in rows.data]
    return LeadLookupHistoryResponse(lookups=[_row_to_response(r) for r in rows.data])


class SaveLeadLookupRequest(BaseModel):
    is_saved: bool


@router.delete("/lookup/{lookup_id}", status_code=204)
async def delete_lead_lookup(
    lookup_id: str,
    user_id: str = Depends(get_user_id),
):
    row_result = supabase_admin.table("lead_lookups").select("*").eq("id", lookup_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Lookup not found.")
    row = _mark_stale_if_needed(row_result.data[0])
    verify_business_access(user_id, row["business_id"])

    if row["status"] in {"pending", "running"}:
        raise HTTPException(
            status_code=409,
            detail="This lookup is still running and cannot be deleted yet.",
        )

    supabase_admin.table("lead_lookups").delete().eq("id", lookup_id).execute()


@router.patch("/lookup/{lookup_id}/save", response_model=LeadLookupResponse)
async def save_lead_lookup(
    lookup_id: str,
    body: SaveLeadLookupRequest,
    user_id: str = Depends(get_user_id),
):
    row_result = supabase_admin.table("lead_lookups").select("*").eq("id", lookup_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Lookup not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])

    updated = (
        supabase_admin.table("lead_lookups")
        .update({"is_saved": body.is_saved})
        .eq("id", lookup_id)
        .execute()
    )
    return _row_to_response(updated.data[0])
