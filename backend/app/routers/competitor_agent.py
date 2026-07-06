"""
Sales Employee router — Competitor Agent module.

POST /sales/competitor-agent/competitors              — add a competitor by website URL, discover their social links
GET  /sales/competitor-agent/competitors               — list tracked competitors for a business
POST /sales/competitor-agent/competitors/{id}/report   — kick off a fan-out report (LinkedIn/Facebook/Instagram via Apify, YouTube via YouTube Data API)
POST /sales/competitor-agent/webhook                   — Apify calls this when a platform run finishes
GET  /sales/competitor-agent/competitors/{id}/reports/{report_id} — poll a report's status/result
GET  /sales/competitor-agent/competitors/{id}/reports  — list past reports for a competitor
"""
import base64
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.competitor_agent import (
    AddCompetitorRequest,
    CompetitorListResponse,
    CompetitorReportListResponse,
    CompetitorReportResponse,
    CompetitorReportResult,
    CompetitorResponse,
    PlatformActivity,
    ReportCreatedResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales/competitor-agent", tags=["sales"])

JINA_BASE = "https://r.jina.ai/"
PAGE_TIMEOUT = 30.0

PLATFORM_ACTORS = {
    "linkedin": "data-slayer~linkedin-company-scraper",
    "facebook": "apify~facebook-posts-scraper",
    "instagram": "apidojo~instagram-scraper",
}

# Up to 3 Apify runs can be in flight per report (vs. Lead Researcher's single
# run), so give more room before treating it as stuck.
STALE_RUNNING_TIMEOUT = timedelta(minutes=15)

DISCOVERY_PROMPT = """You're given the scraped homepage content of a company's website.
Extract exactly these 5 keys as a JSON object:
- company_name: the company's name, if identifiable, else null
- linkedin_url: their LinkedIn company page URL, if linked anywhere in the content, else null
- facebook_url: their Facebook page URL, if linked, else null
- instagram_url: their Instagram profile URL, if linked, else null
- youtube_url: their YouTube channel URL, if linked, else null

Only include URLs that actually appear in the content — do not guess or invent URLs."""

SYNTHESIS_PROMPT = """You're a sales analyst summarizing a competitor's recent activity from raw scraped data
across their LinkedIn, Facebook, Instagram, and/or YouTube presence. You'll be given a JSON array, one entry
per platform that had data, each with a "platform" key and a "raw_data" key.

Return a JSON object with exactly these keys:
- overview: 2-3 sentences summarizing the competitor's overall recent activity and positioning
- platforms: an array, one entry per platform you were given data for, each with these keys:
  - platform: the platform name (e.g. "linkedin")
  - summary: 1-2 sentences on what's notable from this platform's data
  - pricing_signals: anything suggesting a pricing change or offer, else "Nothing found."
  - feature_launches: anything suggesting a new feature/product launch, else "Nothing found."
  - general_activity: general posting/activity level and tone

Be honest about uncertainty — do not invent specifics not supported by the raw data. If a platform's raw
data is sparse, say so rather than filling in plausible-sounding details."""


def _competitor_row_to_response(row: dict) -> CompetitorResponse:
    return CompetitorResponse(
        id=row["id"],
        business_id=row["business_id"],
        name=row.get("name"),
        website_url=row["website_url"],
        linkedin_url=row.get("linkedin_url"),
        facebook_url=row.get("facebook_url"),
        instagram_url=row.get("instagram_url"),
        youtube_url=row.get("youtube_url"),
        discovery_status=row["discovery_status"],
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _report_row_to_response(row: dict) -> CompetitorReportResponse:
    result = None
    if row.get("report_json"):
        result = CompetitorReportResult(**row["report_json"])
    return CompetitorReportResponse(
        id=row["id"],
        competitor_id=row["competitor_id"],
        business_id=row["business_id"],
        status=row["status"],
        error_message=row.get("error_message"),
        result=result,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _mark_report_stale_if_needed(row: dict) -> dict:
    if row["status"] not in ("running", "synthesizing"):
        return row
    updated_at = datetime.fromisoformat(row["updated_at"])
    if datetime.now(timezone.utc) - updated_at < STALE_RUNNING_TIMEOUT:
        return row

    stale_update = (
        supabase_admin.table("competitor_reports")
        .update(
            {
                "status": "failed",
                "error_message": "Timed out waiting for one or more platform scrapes.",
            }
        )
        .eq("id", row["id"])
        .execute()
    )
    logger.warning("Competitor report %s marked failed after exceeding stale timeout.", row["id"])
    return stale_update.data[0]


async def _fetch_via_jina(url: str, client: httpx.AsyncClient) -> str:
    """Fetch a URL via Jina AI Reader — never fetch a user-supplied URL directly (SSRF safety),
    matching the existing convention in knowledge_base.py."""
    r = await client.get(
        f"{JINA_BASE}{url}",
        headers={"Accept": "text/plain", "User-Agent": "Mozilla/5.0"},
        timeout=PAGE_TIMEOUT,
    )
    if r.status_code != 200 or len(r.text) < 50:
        raise RuntimeError(f"Could not read website content (status {r.status_code}).")
    return r.text


async def _discover_social_links(website_url: str) -> dict:
    async with httpx.AsyncClient() as client:
        content = await _fetch_via_jina(website_url, client)

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": DISCOVERY_PROMPT},
            {"role": "user", "content": content[:20_000]},
        ],
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def _platform_actor_input(platform: str, url: str) -> dict:
    if platform == "linkedin":
        return {"linkedin_url": url}
    if platform == "facebook":
        return {"startUrls": [{"url": url}], "resultsLimit": 20}
    if platform == "instagram":
        return {"startUrls": [url], "maxItems": 20}
    raise ValueError(f"Unknown platform: {platform}")


async def _start_platform_apify_run(platform: str, url: str) -> dict:
    actor_id = PLATFORM_ACTORS[platform]
    webhook_url = f"{settings.apify_webhook_base_url.rstrip('/')}/sales/competitor-agent/webhook"
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
            f"https://api.apify.com/v2/actors/{actor_id}/runs",
            params={"webhooks": webhooks_b64},
            headers={"Authorization": f"Bearer {settings.apify_api_token}"},
            json=_platform_actor_input(platform, url),
        )
        resp.raise_for_status()
        return resp.json()["data"]


def _parse_youtube_channel_ref(youtube_url: str) -> dict:
    """Supports the two current common YouTube URL forms: /@handle and /channel/UC...
    Older /c/CustomName and /user/Username forms aren't handled — fails clearly rather than guessing."""
    path = urlparse(youtube_url).path.strip("/")
    if path.startswith("@"):
        return {"forHandle": path}
    if path.startswith("channel/"):
        return {"id": path.split("/", 1)[1]}
    raise ValueError(f"Unsupported YouTube URL format: {youtube_url}")


async def _fetch_youtube_channel_activity(youtube_url: str) -> dict:
    if not settings.youtube_api_key:
        raise RuntimeError("YouTube API key is not configured.")

    channel_ref = _parse_youtube_channel_ref(youtube_url)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "contentDetails,snippet", "key": settings.youtube_api_key, **channel_ref},
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            raise RuntimeError(f"No YouTube channel found for {youtube_url}.")
        channel = items[0]
        uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]

        resp2 = await client.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": 10,
                "key": settings.youtube_api_key,
            },
        )
        resp2.raise_for_status()
        videos = resp2.json().get("items", [])

    return {
        "channel_title": channel["snippet"]["title"],
        "recent_videos": [
            {"title": v["snippet"]["title"], "published_at": v["snippet"]["publishedAt"]} for v in videos
        ],
    }


async def _synthesize_report(runs: list[dict]) -> CompetitorReportResult:
    usable = [r for r in runs if r["status"] == "completed" and r.get("raw_data_json")]
    if not usable:
        raise RuntimeError("No platform produced usable data.")

    payload = [{"platform": r["platform"], "raw_data": r["raw_data_json"]} for r in usable]

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYNTHESIS_PROMPT},
            {"role": "user", "content": json.dumps(payload)[:40_000]},
        ],
        temperature=0.3,
    )
    generated = json.loads(response.choices[0].message.content)
    return CompetitorReportResult(
        overview=generated.get("overview"),
        platforms=[PlatformActivity(**p) for p in generated.get("platforms", [])],
    )


def _try_claim_synthesis(report_id: str) -> bool:
    """Atomic claim so two near-simultaneous webhooks can't both trigger synthesis."""
    updated = (
        supabase_admin.table("competitor_reports")
        .update({"status": "synthesizing"})
        .eq("id", report_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    return bool(updated.data)


async def _maybe_finalize_report(report_id: str) -> None:
    runs = (
        supabase_admin.table("competitor_report_platform_runs")
        .select("*")
        .eq("report_id", report_id)
        .execute()
        .data
    )
    if any(r["status"] == "running" for r in runs):
        return  # still waiting on at least one platform

    if not _try_claim_synthesis(report_id):
        return  # already finalized, or another concurrent call just claimed it

    if all(r["status"] == "skipped" for r in runs) or not any(r["status"] == "completed" for r in runs):
        supabase_admin.table("competitor_reports").update(
            {"status": "failed", "error_message": "No platform data was available to build a report from."}
        ).eq("id", report_id).execute()
        return

    try:
        result = await _synthesize_report(runs)
    except Exception as e:
        logger.error("Competitor report synthesis failed for %s: %s", report_id, e)
        supabase_admin.table("competitor_reports").update(
            {"status": "failed", "error_message": f"AI synthesis failed: {e}"}
        ).eq("id", report_id).execute()
        return

    supabase_admin.table("competitor_reports").update(
        {"status": "completed", "report_json": result.model_dump()}
    ).eq("id", report_id).execute()


@router.post("/competitors", response_model=CompetitorResponse)
async def add_competitor(
    body: AddCompetitorRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)

    insert_row = (
        supabase_admin.table("competitors")
        .insert({"business_id": body.business_id, "website_url": body.website_url, "discovery_status": "pending"})
        .execute()
    )
    row = insert_row.data[0]

    try:
        discovered = await _discover_social_links(body.website_url)
    except Exception as e:
        logger.warning("Social link discovery failed for competitor %s: %s", row["id"], e)
        updated = (
            supabase_admin.table("competitors")
            .update({"discovery_status": "failed", "error_message": str(e)})
            .eq("id", row["id"])
            .execute()
        )
        return _competitor_row_to_response(updated.data[0])

    updated = (
        supabase_admin.table("competitors")
        .update(
            {
                "name": discovered.get("company_name"),
                "linkedin_url": discovered.get("linkedin_url"),
                "facebook_url": discovered.get("facebook_url"),
                "instagram_url": discovered.get("instagram_url"),
                "youtube_url": discovered.get("youtube_url"),
                "discovery_status": "completed",
            }
        )
        .eq("id", row["id"])
        .execute()
    )
    return _competitor_row_to_response(updated.data[0])


@router.get("/competitors", response_model=CompetitorListResponse)
async def list_competitors(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    rows = (
        supabase_admin.table("competitors")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .execute()
    )
    return CompetitorListResponse(competitors=[_competitor_row_to_response(r) for r in rows.data])


@router.post("/competitors/{competitor_id}/report", response_model=ReportCreatedResponse)
async def generate_competitor_report(
    competitor_id: str,
    user_id: str = Depends(get_user_id),
):
    comp_result = supabase_admin.table("competitors").select("*").eq("id", competitor_id).limit(1).execute()
    if not comp_result.data:
        raise HTTPException(status_code=404, detail="Competitor not found.")
    competitor = comp_result.data[0]
    verify_business_access(user_id, competitor["business_id"])

    if not settings.apify_api_token or not settings.apify_webhook_base_url:
        raise HTTPException(status_code=503, detail="Apify is not configured yet.")

    in_flight = (
        supabase_admin.table("competitor_reports")
        .select("id,status")
        .eq("competitor_id", competitor_id)
        .in_("status", ["pending", "running", "synthesizing"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if in_flight.data:
        existing = in_flight.data[0]
        return ReportCreatedResponse(id=existing["id"], status=existing["status"])

    report_row = (
        supabase_admin.table("competitor_reports")
        .insert({"competitor_id": competitor_id, "business_id": competitor["business_id"], "status": "running"})
        .execute()
        .data[0]
    )
    report_id = report_row["id"]

    apify_platforms = [
        (p, competitor.get(f"{p}_url")) for p in ("linkedin", "facebook", "instagram") if competitor.get(f"{p}_url")
    ]
    youtube_url = competitor.get("youtube_url")

    if not apify_platforms and not youtube_url:
        supabase_admin.table("competitor_reports").update(
            {"status": "failed", "error_message": "This competitor has no discovered social platforms to report on."}
        ).eq("id", report_id).execute()
        return ReportCreatedResponse(id=report_id, status="failed")

    for platform, url in apify_platforms:
        run_row = (
            supabase_admin.table("competitor_report_platform_runs")
            .insert({"report_id": report_id, "business_id": competitor["business_id"], "platform": platform, "status": "running"})
            .execute()
            .data[0]
        )
        try:
            run = await _start_platform_apify_run(platform, url)
            supabase_admin.table("competitor_report_platform_runs").update(
                {"apify_run_id": run["id"]}
            ).eq("id", run_row["id"]).execute()
        except httpx.HTTPError as e:
            supabase_admin.table("competitor_report_platform_runs").update(
                {"status": "failed", "error_message": f"Failed to start Apify run: {e}"}
            ).eq("id", run_row["id"]).execute()

    if youtube_url:
        run_row = (
            supabase_admin.table("competitor_report_platform_runs")
            .insert({"report_id": report_id, "business_id": competitor["business_id"], "platform": "youtube", "status": "running"})
            .execute()
            .data[0]
        )
        try:
            activity = await _fetch_youtube_channel_activity(youtube_url)
            supabase_admin.table("competitor_report_platform_runs").update(
                {"status": "completed", "raw_data_json": activity}
            ).eq("id", run_row["id"]).execute()
        except Exception as e:
            supabase_admin.table("competitor_report_platform_runs").update(
                {"status": "failed", "error_message": str(e)}
            ).eq("id", run_row["id"]).execute()

    await _maybe_finalize_report(report_id)

    final = supabase_admin.table("competitor_reports").select("status").eq("id", report_id).limit(1).execute().data[0]
    return ReportCreatedResponse(id=report_id, status=final["status"])


class ApifyWebhookPayload(BaseModel):
    eventType: str
    resource: dict


@router.post("/webhook")
async def competitor_apify_webhook(
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
        supabase_admin.table("competitor_report_platform_runs")
        .select("*")
        .eq("apify_run_id", run_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        logger.warning("Competitor Agent webhook for unknown run_id=%s — ignoring.", run_id)
        return {"ok": True}
    run_row = existing.data[0]

    if payload.eventType != "ACTOR.RUN.SUCCEEDED":
        supabase_admin.table("competitor_report_platform_runs").update(
            {"status": "failed", "error_message": f"Apify run ended with event: {payload.eventType}"}
        ).eq("id", run_row["id"]).execute()
    else:
        dataset_id = payload.resource.get("defaultDatasetId")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                headers={"Authorization": f"Bearer {settings.apify_api_token}"},
            )
            resp.raise_for_status()
            items = resp.json()

        if not items:
            supabase_admin.table("competitor_report_platform_runs").update(
                {"status": "failed", "error_message": "Apify run finished but returned no data."}
            ).eq("id", run_row["id"]).execute()
        else:
            supabase_admin.table("competitor_report_platform_runs").update(
                {"status": "completed", "raw_data_json": items}
            ).eq("id", run_row["id"]).execute()

    await _maybe_finalize_report(run_row["report_id"])
    return {"ok": True}


@router.get("/competitors/{competitor_id}/reports/{report_id}", response_model=CompetitorReportResponse)
async def get_competitor_report(
    competitor_id: str,
    report_id: str,
    user_id: str = Depends(get_user_id),
):
    row_result = (
        supabase_admin.table("competitor_reports")
        .select("*")
        .eq("id", report_id)
        .eq("competitor_id", competitor_id)
        .limit(1)
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Report not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])
    row = _mark_report_stale_if_needed(row)
    return _report_row_to_response(row)


@router.get("/competitors/{competitor_id}/reports", response_model=CompetitorReportListResponse)
async def list_competitor_reports(
    competitor_id: str,
    user_id: str = Depends(get_user_id),
):
    comp_result = supabase_admin.table("competitors").select("business_id").eq("id", competitor_id).limit(1).execute()
    if not comp_result.data:
        raise HTTPException(status_code=404, detail="Competitor not found.")
    verify_business_access(user_id, comp_result.data[0]["business_id"])

    rows = (
        supabase_admin.table("competitor_reports")
        .select("*")
        .eq("competitor_id", competitor_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows.data = [_mark_report_stale_if_needed(r) for r in rows.data]
    return CompetitorReportListResponse(reports=[_report_row_to_response(r) for r in rows.data])
