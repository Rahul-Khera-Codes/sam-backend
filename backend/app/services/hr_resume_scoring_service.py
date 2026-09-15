from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.services.hr_document_embedding_service import extract_pdf_text

logger = logging.getLogger(__name__)

RESUME_SCORING_MODEL = "gpt-4o-mini"
APPLICATIONS_BUCKET = "hr-job-applications"


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=45.0, max_retries=1)


def _clamp_criterion(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement": str(item.get("requirement") or "")[:300],
        "met": bool(item.get("met")),
        "evidence": str(item.get("evidence") or "")[:500],
    }


async def generate_and_store_resume_score(
    *,
    business_id: str,
    application_id: str,
) -> dict[str, Any] | None:
    """Score a candidate's resume against the job's stated requirements.

    Best-effort: any failure here (missing resume, unreadable PDF, LLM error) is
    swallowed by the caller (this is invoked from a BackgroundTasks hook after
    application submission) so it never blocks the candidate's apply flow.
    """
    application_result = (
        supabase_admin.table("hr_job_applications")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", application_id)
        .limit(1)
        .execute()
    )
    if not application_result.data:
        return None
    application = application_result.data[0]

    resume_path = application.get("resume_storage_path")
    if not resume_path:
        return None

    job_result = (
        supabase_admin.table("hr_job_postings")
        .select("title,summary,responsibilities,qualifications,requirements_skills,required_experience,seniority")
        .eq("business_id", business_id)
        .eq("id", application["job_posting_id"])
        .limit(1)
        .execute()
    )
    if not job_result.data:
        return None
    job = job_result.data[0]

    try:
        resume_bytes = supabase_admin.storage.from_(APPLICATIONS_BUCKET).download(resume_path)
    except Exception as exc:
        logger.warning("Failed to download resume for scoring (application %s): %s", application_id, exc)
        return None

    resume_text = extract_pdf_text(resume_bytes)
    if not resume_text:
        return None

    request = {
        "job": {
            "title": job.get("title") or "",
            "summary": job.get("summary") or "",
            "responsibilities": job.get("responsibilities") or "",
            "qualifications": job.get("qualifications") or "",
            "requirements_skills": job.get("requirements_skills") or "",
            "required_experience": job.get("required_experience") or "",
            "seniority": job.get("seniority") or "",
        },
        "resume_text": resume_text[:12000],
        "requirements": [
            "Score only how well the resume matches this job's stated requirements and qualifications.",
            "Use evidence from the resume text. Do not infer protected characteristics.",
            "The score is advisory only and requires human review.",
            "Do not auto-reject or present the recommendation as final.",
            "criterion_scores should list the job's key requirements/qualifications, whether the resume "
            "demonstrates each one (met: true/false), and brief evidence for that judgment.",
        ],
        "response_schema": {
            "total_score": 0,
            "summary": "",
            "strengths": [],
            "concerns": [],
            "criterion_scores": [
                {"requirement": "", "met": True, "evidence": ""},
            ],
            "candidate_current_title": "",
            "candidate_current_company": "",
            "candidate_years_experience": 0,
        },
    }
    request["requirements"].append(
        "candidate_current_title/candidate_current_company: the candidate's most recent job "
        "title and employer, read directly from the resume's work history. Empty string if the "
        "resume has no work history (e.g. a student/new grad)."
    )
    request["requirements"].append(
        "candidate_years_experience: total years of professional work experience, estimated from "
        "the resume's work history date ranges. 0 if none."
    )
    response = await _client().chat.completions.create(
        model=RESUME_SCORING_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You screen job applicant resumes against a job's stated requirements. "
                    "Return JSON only. All scoring is advisory and human-reviewed."
                ),
            },
            {"role": "user", "content": json.dumps(request)},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    raw_criterion_scores = payload.get("criterion_scores")
    criterion_scores = (
        [_clamp_criterion(item) for item in raw_criterion_scores if isinstance(item, dict)]
        if isinstance(raw_criterion_scores, list)
        else []
    )
    try:
        years_experience = float(payload.get("candidate_years_experience") or 0)
    except (TypeError, ValueError):
        years_experience = 0.0
    row = {
        "business_id": business_id,
        "application_id": application_id,
        "model": RESUME_SCORING_MODEL,
        "total_score": max(0, min(100, float(payload.get("total_score") or 0))),
        "summary": str(payload.get("summary") or ""),
        "strengths": payload.get("strengths") if isinstance(payload.get("strengths"), list) else [],
        "concerns": payload.get("concerns") if isinstance(payload.get("concerns"), list) else [],
        "criterion_scores": criterion_scores,
        "current_title": str(payload.get("candidate_current_title") or "")[:200],
        "current_company": str(payload.get("candidate_current_company") or "")[:200],
        "years_experience": max(0, min(80, years_experience)),
    }
    existing = (
        supabase_admin.table("hr_application_resume_scores")
        .select("id")
        .eq("business_id", business_id)
        .eq("application_id", application_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        saved = (
            supabase_admin.table("hr_application_resume_scores")
            .update(row)
            .eq("id", existing.data[0]["id"])
            .select("*")
            .execute()
        )
    else:
        saved = supabase_admin.table("hr_application_resume_scores").insert(row).select("*").execute()
    return saved.data[0] if saved.data else row


async def score_application_resume_safe(*, business_id: str, application_id: str) -> None:
    """BackgroundTasks entrypoint: never raise, scoring failures must not surface to the candidate."""
    try:
        await generate_and_store_resume_score(business_id=business_id, application_id=application_id)
    except Exception as exc:
        logger.warning("Resume scoring failed for application %s: %s", application_id, exc)
