"""
Sales Employee router — Lead Researcher module.

POST /sales/lead-researcher/lookup   — kick off an async Apify scrape for a LinkedIn URL
POST /sales/lead-researcher/webhook  — Apify calls this when the run finishes; we enrich + save
GET  /sales/lead-researcher/lookup/{id} — poll for status/result
GET  /sales/lead-researcher/history  — past lookups for a business
PATCH /sales/lead-researcher/lookup/{id}/save — toggle saved
"""
import base64
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
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

ENRICHMENT_PROMPT = """You turn a raw LinkedIn profile scrape into a sales lead card.
Given the profile JSON below, return a JSON object with these exact keys:
- job_role_insights: 1-2 sentences on what this person's role likely involves and what they'd care about professionally
- pain_points_and_sales_angles: 1-2 sentences on likely pain points and how to position an outreach angle
- personal_interests: 1 sentence on any personal interests inferable from the profile (skills, volunteering, etc.) — if nothing is inferable, say "Not enough data to infer."
- best_time_to_reach: a reasonable guess (e.g. "Weekday mornings, based on typical work hours for their timezone") — this is a heuristic, not a fact
- outreach_email_draft: a short, personalized cold outreach email draft (3-4 sentences) referencing something specific from their profile

Be honest about uncertainty — do not invent specific facts not supported by the profile data."""


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
    webhook_url = (
        f"{settings.apify_webhook_base_url.rstrip('/')}/sales/lead-researcher/webhook"
        f"?secret={settings.apify_webhook_secret}"
    )
    webhooks = [
        {
            "eventTypes": [
                "ACTOR.RUN.SUCCEEDED",
                "ACTOR.RUN.FAILED",
                "ACTOR.RUN.ABORTED",
                "ACTOR.RUN.TIMED_OUT",
            ],
            "requestUrl": webhook_url,
        }
    ]
    webhooks_b64 = base64.b64encode(json.dumps(webhooks).encode()).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.apify.com/v2/actors/{APIFY_ACTOR_ID}/runs",
            params={"token": settings.apify_api_token, "webhooks": webhooks_b64},
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
    secret: str = Query(...),
):
    if not settings.apify_webhook_secret or secret != settings.apify_webhook_secret:
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
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
            params={"token": settings.apify_api_token},
        )
        resp.raise_for_status()
        items = resp.json()

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
    return LeadLookupHistoryResponse(lookups=[_row_to_response(r) for r in rows.data])


class SaveLeadLookupRequest(BaseModel):
    is_saved: bool


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
