"""
Sales Employee router — Market Agent module.

POST /sales/market-agent/refresh                    — kick off a new market-intelligence refresh
GET  /sales/market-agent/cards                       — latest completed card per analyst type (the feed)
GET  /sales/market-agent/runs/{run_id}                — poll a specific refresh run's status
PATCH /sales/market-agent/cards/{card_id}/bookmark    — toggle bookmark on a card
POST /sales/market-agent/custom-analysts              — add a custom analyst
GET  /sales/market-agent/custom-analysts              — list custom analysts for a business
PATCH /sales/market-agent/custom-analysts/{id}        — edit a custom analyst

Exa's /search is synchronous (unlike Apify) — no webhook infra needed here.
Each analyst call is awaited concurrently via asyncio.gather.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from openai import AsyncOpenAI

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.routers.analytics import get_summary as get_analytics_summary
from app.schemas.market_agent import (
    AddCustomAnalystRequest,
    BookmarkCardRequest,
    CustomAnalystListResponse,
    CustomAnalystResponse,
    MarketAnalysisCardListResponse,
    MarketAnalysisCardResponse,
    MarketAnalysisRunResponse,
    RefreshCreatedResponse,
    SourceCitation,
    UpdateCustomAnalystRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales/market-agent", tags=["sales"])

# Exa's own worst case (deep-reasoning) is ~40s; give real margin before
# calling a run stuck. Much shorter than Competitor Agent's 15 min since
# Exa is synchronous, not an async actor-run platform like Apify.
STALE_RUNNING_TIMEOUT = timedelta(minutes=5)

CARD_SYNTHESIS_SCHEMA = {
    "type": "object",
    "required": ["headline", "insight", "confidence", "timeframe"],
    "properties": {
        "headline": {"type": "string", "description": "A short, specific headline for this insight"},
        "insight": {"type": "string", "description": "1-2 sentence explanation grounded in the sources"},
        "confidence": {"type": "string", "description": "high, medium, or low"},
        "timeframe": {"type": "string", "description": "e.g. 'Next 6-12 months', 'Happening now'"},
    },
}

# The 6 Exa-backed built-in analysts. Business Intelligence (7th) is handled
# separately — it reads this business's own data, not the web.
BUILT_IN_ANALYSTS = [
    {
        "type": "trend",
        "name": "Trend Analyst",
        "query_template": "recent, concrete growth patterns and trend shifts in the {industry} industry",
    },
    {
        "type": "futurist",
        "name": "Futurist",
        "query_template": "credible predictions for the next 1-3 years in the {industry} industry",
    },
    {
        "type": "cultural",
        "name": "Cultural Analyst",
        "query_template": "social or cultural shifts affecting how people buy in the {industry} industry",
    },
    {
        "type": "market_research",
        "name": "Market Research Analyst",
        "query_template": "market and competitive landscape analysis for the {industry} industry",
    },
    {
        "type": "consumer_insights",
        "name": "Consumer Insights Analyst",
        "query_template": "buyer behavior and preference trends in the {industry} industry",
    },
    {
        "type": "innovation_strategist",
        "name": "Innovation Strategist",
        "query_template": "early signals of new technology or ideas worth watching in the {industry} industry",
    },
]

SYNTHESIS_PROMPT = """You write a short "What's Changing" summary for a business owner, given several
market-analysis card headlines/insights. Return a JSON object with one key, "summary" — 2-3 sentences
covering the most notable points across all the cards given. Be concise and concrete, do not just restate
every card."""

BI_PROMPT = """You're a business analyst. Given this business's own recent call-volume analytics summary
(JSON), write one notable insight about it. Return a JSON object with exactly these keys:
- headline: a short, specific headline
- insight: 1-2 sentences explaining the pattern
- confidence: high, medium, or low
- timeframe: e.g. "Last 7 days"
If the data shows nothing notable, say so honestly rather than inventing significance."""

BI_PROMPT_USED = "Analyze this business's own recent 7-day call-volume analytics and write one notable insight."


def _sources_from_grounding(grounding: list[dict]) -> list[SourceCitation]:
    seen = set()
    sources = []
    for entry in grounding or []:
        for citation in entry.get("citations", []):
            url = citation.get("url")
            if url and url not in seen:
                seen.add(url)
                sources.append(SourceCitation(url=url, title=citation.get("title")))
    return sources


def _card_row_to_response(row: dict) -> MarketAnalysisCardResponse:
    sources = [SourceCitation(**s) for s in (row.get("sources_json") or [])]
    return MarketAnalysisCardResponse(
        id=row["id"],
        run_id=row["run_id"],
        business_id=row["business_id"],
        analyst_type=row["analyst_type"],
        analyst_name=row["analyst_name"],
        custom_analyst_id=row.get("custom_analyst_id"),
        headline=row.get("headline"),
        insight=row.get("insight"),
        confidence=row.get("confidence"),
        timeframe_or_impact=row.get("timeframe_or_impact"),
        prompt_used=row.get("prompt_used"),
        sources=sources,
        is_bookmarked=row["is_bookmarked"],
        status=row["status"],
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_industry_context(business_id: str, fallback_type: str | None) -> str:
    """Every analyst query embeds this as "...in the {industry} industry" (both
    the Exa query text and the system prompt), so it needs to stay a short
    noun phrase, not a full sentence. Prefer the business's own Branding
    "target niche" (already written as a specific market segment) over the
    generic businesses.type field. Falls back to businesses.type for any
    business that hasn't filled in Branding yet, so this never regresses
    behavior for existing businesses."""
    branding = (
        supabase_admin.table("business_branding")
        .select("target_niche")
        .eq("business_id", business_id)
        .limit(1)
        .execute()
        .data
    )
    target_niche = branding[0].get("target_niche") if branding else None
    if target_niche and target_niche.strip():
        return target_niche.strip()

    return fallback_type or "their industry"


def _build_exa_system_prompt(business_name: str, industry: str) -> str:
    return (
        f"You're researching for {business_name}, a business in the {industry} industry. "
        "Prefer official/authoritative sources and recent reporting. Keep the output grounded — "
        "do not invent specifics not present in the sources."
    )


async def _run_exa_analyst(business_name: str, industry: str, analyst_type: str, analyst_name: str, query: str) -> dict:
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": settings.exa_api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "type": "auto",
                "numResults": 5,
                "systemPrompt": _build_exa_system_prompt(business_name, industry),
                "outputSchema": CARD_SYNTHESIS_SCHEMA,
                "contents": {"highlights": True},
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _generate_card_for_analyst(
    run_id: str,
    business_id: str,
    business_name: str,
    industry: str,
    analyst_type: str,
    analyst_name: str,
    query: str,
    custom_analyst_id: str | None = None,
) -> None:
    card_row = (
        supabase_admin.table("market_analysis_cards")
        .insert(
            {
                "run_id": run_id,
                "business_id": business_id,
                "analyst_type": analyst_type,
                "analyst_name": analyst_name,
                "custom_analyst_id": custom_analyst_id,
                "prompt_used": query,
                "status": "running",
            }
        )
        .execute()
        .data[0]
    )
    try:
        result = await _run_exa_analyst(business_name, industry, analyst_type, analyst_name, query)
        content = result.get("output", {}).get("content", {})
        sources = _sources_from_grounding(result.get("output", {}).get("grounding", []))
        supabase_admin.table("market_analysis_cards").update(
            {
                "status": "completed",
                "headline": content.get("headline"),
                "insight": content.get("insight"),
                "confidence": content.get("confidence"),
                "timeframe_or_impact": content.get("timeframe"),
                "sources_json": [s.model_dump() for s in sources],
            }
        ).eq("id", card_row["id"]).execute()
    except Exception as e:
        logger.error("Market Agent analyst %s failed for run %s: %s", analyst_type, run_id, e)
        supabase_admin.table("market_analysis_cards").update(
            {"status": "failed", "error_message": str(e)}
        ).eq("id", card_row["id"]).execute()


async def _generate_business_intelligence_card(run_id: str, business_id: str) -> None:
    card_row = (
        supabase_admin.table("market_analysis_cards")
        .insert(
            {
                "run_id": run_id,
                "business_id": business_id,
                "analyst_type": "business_intelligence",
                "analyst_name": "Business Intelligence Analyst",
                "prompt_used": BI_PROMPT_USED,
                "status": "running",
            }
        )
        .execute()
        .data[0]
    )
    try:
        summary = await get_analytics_summary(business_id=business_id, period="7d")
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": BI_PROMPT},
                {"role": "user", "content": json.dumps(summary)},
            ],
            temperature=0.3,
        )
        content = json.loads(response.choices[0].message.content)
        supabase_admin.table("market_analysis_cards").update(
            {
                "status": "completed",
                "headline": content.get("headline"),
                "insight": content.get("insight"),
                "confidence": content.get("confidence"),
                "timeframe_or_impact": content.get("timeframe"),
                "sources_json": [],
            }
        ).eq("id", card_row["id"]).execute()
    except Exception as e:
        logger.error("Market Agent business-intelligence card failed for run %s: %s", run_id, e)
        supabase_admin.table("market_analysis_cards").update(
            {"status": "failed", "error_message": str(e)}
        ).eq("id", card_row["id"]).execute()


async def run_market_agent_refresh(business_id: str, triggered_by: str = "manual") -> str:
    """Core refresh logic — called by the router AND the scheduled job.
    Dedupe lives here (not just in the router) so the scheduled job is
    protected too, e.g. if a slow run is still active when the next
    scheduled tick fires."""
    in_flight = (
        supabase_admin.table("market_analysis_runs")
        .select("id,status")
        .eq("business_id", business_id)
        .in_("status", ["pending", "running", "synthesizing"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if in_flight.data:
        return in_flight.data[0]["id"]

    biz = (
        supabase_admin.table("businesses")
        .select("id,name,type")
        .eq("id", business_id)
        .limit(1)
        .execute()
        .data[0]
    )
    business_name = biz.get("name") or "the business"
    industry = _build_industry_context(business_id, biz.get("type"))

    custom_analysts = (
        supabase_admin.table("market_custom_analysts")
        .select("*")
        .eq("business_id", business_id)
        .execute()
        .data
    )

    run_row = (
        supabase_admin.table("market_analysis_runs")
        .insert({"business_id": business_id, "status": "running", "triggered_by": triggered_by})
        .execute()
        .data[0]
    )
    run_id = run_row["id"]

    tasks = [
        _generate_card_for_analyst(
            run_id, business_id, business_name, industry, a["type"], a["name"], a["query_template"].format(industry=industry)
        )
        for a in BUILT_IN_ANALYSTS
    ]
    tasks += [
        _generate_card_for_analyst(
            run_id,
            business_id,
            business_name,
            industry,
            "custom",
            ca["name"],
            ca["prompt_description"],
            custom_analyst_id=ca["id"],
        )
        for ca in custom_analysts
    ]
    tasks.append(_generate_business_intelligence_card(run_id, business_id))

    await asyncio.gather(*tasks, return_exceptions=True)

    cards = (
        supabase_admin.table("market_analysis_cards").select("*").eq("run_id", run_id).execute().data
    )
    completed_cards = [c for c in cards if c["status"] == "completed"]

    if not completed_cards:
        supabase_admin.table("market_analysis_runs").update(
            {"status": "failed", "error_message": "No analyst produced usable data."}
        ).eq("id", run_id).execute()
        return run_id

    try:
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        [{"headline": c["headline"], "insight": c["insight"]} for c in completed_cards]
                    ),
                },
            ],
            temperature=0.3,
        )
        summary = json.loads(response.choices[0].message.content).get("summary")
        supabase_admin.table("market_analysis_runs").update(
            {"status": "completed", "whats_changing_summary": summary}
        ).eq("id", run_id).execute()
    except Exception as e:
        logger.error("Market Agent 'what's changing' synthesis failed for run %s: %s", run_id, e)
        supabase_admin.table("market_analysis_runs").update(
            {"status": "completed", "error_message": f"Summary synthesis failed: {e}"}
        ).eq("id", run_id).execute()

    return run_id


@router.post("/refresh", response_model=RefreshCreatedResponse)
async def trigger_refresh(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    if not settings.exa_api_key:
        raise HTTPException(status_code=503, detail="Exa.ai is not configured yet.")

    run_id = await run_market_agent_refresh(business_id, triggered_by="manual")
    final = supabase_admin.table("market_analysis_runs").select("status").eq("id", run_id).limit(1).execute().data[0]
    return RefreshCreatedResponse(id=run_id, status=final["status"])


def _mark_run_stale_if_needed(row: dict) -> dict:
    if row["status"] not in ("running", "synthesizing"):
        return row
    updated_at = datetime.fromisoformat(row["updated_at"])
    if datetime.now(timezone.utc) - updated_at < STALE_RUNNING_TIMEOUT:
        return row
    stale_update = (
        supabase_admin.table("market_analysis_runs")
        .update({"status": "failed", "error_message": "Timed out waiting for Exa."})
        .eq("id", row["id"])
        .execute()
    )
    return stale_update.data[0]


@router.get("/runs/{run_id}", response_model=MarketAnalysisRunResponse)
async def get_run(
    run_id: str,
    user_id: str = Depends(get_user_id),
):
    row_result = supabase_admin.table("market_analysis_runs").select("*").eq("id", run_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Run not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])
    row = _mark_run_stale_if_needed(row)

    cards = supabase_admin.table("market_analysis_cards").select("*").eq("run_id", run_id).execute().data
    return MarketAnalysisRunResponse(
        id=row["id"],
        business_id=row["business_id"],
        status=row["status"],
        triggered_by=row["triggered_by"],
        whats_changing_summary=row.get("whats_changing_summary"),
        error_message=row.get("error_message"),
        cards=[_card_row_to_response(c) for c in cards],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/cards", response_model=MarketAnalysisCardListResponse)
async def get_latest_cards(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    """Latest completed card per analyst type — the main feed view."""
    verify_business_access(user_id, business_id)
    rows = (
        supabase_admin.table("market_analysis_cards")
        .select("*")
        .eq("business_id", business_id)
        .eq("status", "completed")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    latest_by_analyst: dict[str, dict] = {}
    for row in rows:
        key = row["analyst_type"] + (row["analyst_name"] if row["analyst_type"] == "custom" else "")
        if key not in latest_by_analyst:
            latest_by_analyst[key] = row

    return MarketAnalysisCardListResponse(cards=[_card_row_to_response(r) for r in latest_by_analyst.values()])


@router.patch("/cards/{card_id}/bookmark", response_model=MarketAnalysisCardResponse)
async def bookmark_card(
    card_id: str,
    body: BookmarkCardRequest,
    user_id: str = Depends(get_user_id),
):
    row_result = supabase_admin.table("market_analysis_cards").select("*").eq("id", card_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Card not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])

    updated = (
        supabase_admin.table("market_analysis_cards")
        .update({"is_bookmarked": body.is_bookmarked})
        .eq("id", card_id)
        .execute()
    )
    return _card_row_to_response(updated.data[0])


@router.post("/custom-analysts", response_model=CustomAnalystResponse)
async def add_custom_analyst(
    body: AddCustomAnalystRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    row = (
        supabase_admin.table("market_custom_analysts")
        .insert(
            {
                "business_id": body.business_id,
                "name": body.name,
                "prompt_description": body.prompt_description,
            }
        )
        .execute()
        .data[0]
    )
    return CustomAnalystResponse(**row)


@router.get("/custom-analysts", response_model=CustomAnalystListResponse)
async def list_custom_analysts(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    rows = (
        supabase_admin.table("market_custom_analysts")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return CustomAnalystListResponse(custom_analysts=[CustomAnalystResponse(**r) for r in rows])


@router.patch("/custom-analysts/{analyst_id}", response_model=CustomAnalystResponse)
async def update_custom_analyst(
    analyst_id: str,
    body: UpdateCustomAnalystRequest,
    user_id: str = Depends(get_user_id),
):
    row_result = supabase_admin.table("market_custom_analysts").select("*").eq("id", analyst_id).limit(1).execute()
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Custom analyst not found.")
    row = row_result.data[0]
    verify_business_access(user_id, row["business_id"])

    updated = (
        supabase_admin.table("market_custom_analysts")
        .update(
            {
                "name": body.name,
                "prompt_description": body.prompt_description,
            }
        )
        .eq("id", analyst_id)
        .execute()
    )
    return CustomAnalystResponse(**updated.data[0])
