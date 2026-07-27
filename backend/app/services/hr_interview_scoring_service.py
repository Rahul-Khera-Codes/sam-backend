from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin


INTERVIEW_SCORING_MODEL = "gpt-4o-mini"


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=45.0, max_retries=1)


def _normalize_recommendation(value: str) -> str:
    normalized = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return normalized if normalized in {"strong_hire", "hire", "review", "no_hire"} else "review"


async def generate_and_store_interview_outcome(
    *,
    business_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    session_result = (
        supabase_admin.table("hr_interview_sessions")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    if not session_result.data:
        return None
    session = session_result.data[0]
    version_id = session.get("active_version_id")
    if not version_id:
        return None

    version_result = (
        supabase_admin.table("hr_interview_bank_versions")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", version_id)
        .limit(1)
        .execute()
    )
    if not version_result.data:
        return None
    snapshot = version_result.data[0].get("snapshot") or {}
    transcript_rows = (
        supabase_admin.table("hr_interview_transcript_turns")
        .select("speaker,text,question_id,question_order,sequence_order")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .order("sequence_order")
        .execute()
    ).data or []
    if not transcript_rows:
        return None

    request = {
        "candidate": {
            "name": session.get("candidate_name") or "",
        },
        "rubric": snapshot.get("rubric") or [],
        "questions": snapshot.get("questions") or [],
        "transcript": transcript_rows,
        "requirements": [
            "Score only against the provided rubric.",
            "Use evidence from the transcript.",
            "Do not infer protected characteristics.",
            "The recommendation is advisory only and requires human review.",
            "Do not auto-hire, auto-reject, or present the recommendation as final.",
        ],
        "response_schema": {
            "total_score": 0,
            "recommendation": "review",
            "summary": "",
            "strengths": [],
            "concerns": [],
            "criterion_scores": [
                {
                    "name": "",
                    "score": 0,
                    "weight": 0,
                    "evidence": "",
                }
            ],
        },
    }
    response = await _client().chat.completions.create(
        model=INTERVIEW_SCORING_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You create structured employment interview assessment packets. "
                    "Return JSON only. All hiring recommendations are advisory and human-reviewed."
                ),
            },
            {"role": "user", "content": json.dumps(request)},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    row = {
        "business_id": business_id,
        "session_id": session_id,
        "model": INTERVIEW_SCORING_MODEL,
        "total_score": max(0, min(100, float(payload.get("total_score") or 0))),
        "recommendation": _normalize_recommendation(str(payload.get("recommendation") or "")),
        "summary": str(payload.get("summary") or ""),
        "strengths": payload.get("strengths") if isinstance(payload.get("strengths"), list) else [],
        "concerns": payload.get("concerns") if isinstance(payload.get("concerns"), list) else [],
        "criterion_scores": payload.get("criterion_scores") if isinstance(payload.get("criterion_scores"), list) else [],
    }
    existing = (
        supabase_admin.table("hr_interview_outcomes")
        .select("id")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        saved = (
            supabase_admin.table("hr_interview_outcomes")
            .update(row)
            .eq("id", existing.data[0]["id"])
            .select("*")
            .execute()
        )
    else:
        saved = supabase_admin.table("hr_interview_outcomes").insert(row).select("*").execute()
    return saved.data[0] if saved.data else row
