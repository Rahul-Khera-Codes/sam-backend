from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.hr_interviews import HrInterviewReportResponse, HrInterviewReportStats

logger = logging.getLogger(__name__)

REPORT_MODEL = "gpt-4o-mini"

_PENDING_STATUSES = {"draft", "invited", "opened", "in_progress"}
_COMPLETED_STATUSES = {"completed", "reviewed"}


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=45.0, max_retries=1)


async def generate_interview_report(*, business_id: str, days: int) -> HrInterviewReportResponse:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sessions = (
        supabase_admin.table("hr_interview_sessions")
        .select("id,candidate_name,status,created_at")
        .eq("business_id", business_id)
        .gte("created_at", since)
        .execute()
    ).data or []

    session_ids = [row["id"] for row in sessions]
    outcomes_by_session: dict[str, dict[str, Any]] = {}
    if session_ids:
        outcome_rows = (
            supabase_admin.table("hr_interview_outcomes")
            .select("session_id,total_score,recommendation")
            .in_("session_id", session_ids)
            .execute()
        ).data or []
        outcomes_by_session = {row["session_id"]: row for row in outcome_rows}

    completed = [row for row in sessions if row.get("status") in _COMPLETED_STATUSES]
    pending = [row for row in sessions if row.get("status") in _PENDING_STATUSES]
    scores = [
        float(outcomes_by_session[row["id"]]["total_score"])
        for row in completed
        if row["id"] in outcomes_by_session
    ]
    average_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    recommendation_counts: dict[str, int] = {}
    for row in completed:
        outcome = outcomes_by_session.get(row["id"])
        if not outcome:
            continue
        recommendation = outcome.get("recommendation") or "review"
        recommendation_counts[recommendation] = recommendation_counts.get(recommendation, 0) + 1

    ranked = sorted(
        (
            {"name": row.get("candidate_name") or "", "score": float(outcomes_by_session[row["id"]]["total_score"])}
            for row in completed
            if row["id"] in outcomes_by_session
        ),
        key=lambda item: item["score"],
        reverse=True,
    )

    stats = HrInterviewReportStats(
        window_days=days,
        total_interviews=len(sessions),
        completed=len(completed),
        pending=len(pending),
        average_score=average_score,
        recommendation_counts=recommendation_counts,
        top_candidates=ranked[:5],
    )
    generated_at = datetime.now(timezone.utc).isoformat()

    if not sessions:
        return HrInterviewReportResponse(
            model=REPORT_MODEL,
            generated_at=generated_at,
            stats=stats,
            narrative="No interview activity in this window yet.",
        )

    response = await _client().chat.completions.create(
        model=REPORT_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You write a short recruiting-pipeline summary for a hiring manager, grounded "
                    "strictly in the provided statistics. Use ONLY the numbers and names given — "
                    "never invent counts, candidates, or scores not present in the data. "
                    'Return JSON only, matching {"narrative": "..."}. 3-5 sentences, plain language, '
                    "no markdown."
                ),
            },
            {"role": "user", "content": json.dumps(stats.model_dump())},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return HrInterviewReportResponse(
        model=REPORT_MODEL,
        generated_at=generated_at,
        stats=stats,
        narrative=str(payload.get("narrative") or ""),
    )
