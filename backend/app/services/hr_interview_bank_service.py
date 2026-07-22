from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.supabase import supabase_admin
from app.schemas.hr_interviews import (
    HrInterviewBankDraftUpsertRequest,
    HrInterviewSettings,
)
from app.services.hr_interview_compliance_service import (
    POLICY_VERSION,
    enforce_questions,
    record_compliance_checks,
)


class InterviewBankNotFound(LookupError):
    pass


class InterviewBankValidationError(ValueError):
    pass


def get_native_job(*, business_id: str, job_id: str) -> dict[str, Any]:
    result = (
        supabase_admin.table("hr_job_postings")
        .select("*")
        .eq("id", job_id)
        .eq("business_id", business_id)
        .eq("source", "native")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise InterviewBankNotFound(
            "Interview banks currently require a saved native AI Employees job."
        )
    return result.data[0]


def _get_bank_row(*, business_id: str, job_id: str) -> dict[str, Any] | None:
    result = (
        supabase_admin.table("hr_interview_banks")
        .select("*")
        .eq("business_id", business_id)
        .eq("job_posting_id", job_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _default_questions(job: dict[str, Any]) -> list[dict[str, Any]]:
    title = job.get("title") or "this role"
    return [
        {
            "question_text": f"What interests you about the {title} role, and which experience best prepares you for it?",
            "category": "warm_up",
            "competency": "Role motivation",
            "order_index": 0,
            "enabled": True,
            "required": True,
            "ai_generated": False,
            "source": "platform_core",
            "expected_seconds": 120,
            "max_follow_ups": 1,
        },
        {
            "question_text": "Tell me about a recent project most relevant to this role. What was your contribution and the outcome?",
            "category": "behavioral",
            "competency": "Relevant experience",
            "order_index": 1,
            "enabled": True,
            "required": True,
            "ai_generated": False,
            "source": "platform_core",
            "expected_seconds": 180,
            "max_follow_ups": 2,
        },
        {
            "question_text": "Describe a difficult work problem you solved. How did you evaluate options and measure success?",
            "category": "situational",
            "competency": "Problem solving",
            "order_index": 2,
            "enabled": True,
            "required": True,
            "ai_generated": False,
            "source": "platform_core",
            "expected_seconds": 180,
            "max_follow_ups": 2,
        },
        {
            "question_text": "How do you collaborate when teammates disagree on the best approach?",
            "category": "culture",
            "competency": "Collaboration",
            "order_index": 3,
            "enabled": True,
            "required": False,
            "ai_generated": False,
            "source": "platform_core",
            "expected_seconds": 120,
            "max_follow_ups": 1,
        },
    ]


def _default_rubric() -> list[dict[str, Any]]:
    return [
        {
            "name": "Role-relevant capability",
            "description": "Demonstrates the skills and judgment required by the posting.",
            "weight": 40,
            "order_index": 0,
            "score_1_anchor": "Provides no relevant example or demonstrates major skill gaps.",
            "score_3_anchor": "Provides a relevant example with adequate execution.",
            "score_5_anchor": "Provides a highly relevant example with strong judgment and measurable impact.",
        },
        {
            "name": "Problem solving",
            "description": "Frames problems, evaluates options, and learns from outcomes.",
            "weight": 35,
            "order_index": 1,
            "score_1_anchor": "Approach is unclear or unsupported.",
            "score_3_anchor": "Uses a logical approach and explains key trade-offs.",
            "score_5_anchor": "Uses a rigorous approach, anticipates risks, and validates outcomes.",
        },
        {
            "name": "Communication & collaboration",
            "description": "Communicates clearly and works constructively with others.",
            "weight": 25,
            "order_index": 2,
            "score_1_anchor": "Communication is unclear or dismisses collaboration.",
            "score_3_anchor": "Communicates clearly and describes constructive teamwork.",
            "score_5_anchor": "Adapts communication, resolves conflict, and improves team outcomes.",
        },
    ]


def _active_version_number(bank_id: str, active_version_id: str | None) -> int | None:
    if not active_version_id:
        return None
    result = (
        supabase_admin.table("hr_interview_bank_versions")
        .select("version_number")
        .eq("id", active_version_id)
        .eq("bank_id", bank_id)
        .limit(1)
        .execute()
    )
    return int(result.data[0]["version_number"]) if result.data else None


def get_interview_bank(*, business_id: str, job_id: str) -> dict[str, Any]:
    job = get_native_job(business_id=business_id, job_id=job_id)
    bank = _get_bank_row(business_id=business_id, job_id=job_id)
    if not bank:
        return {
            "id": None,
            "business_id": business_id,
            "job_posting_id": job_id,
            "job_title": job.get("title") or "Untitled role",
            "settings": HrInterviewSettings().model_dump(),
            "opening_message": (
                f"Welcome. This structured interview for the {job.get('title') or 'role'} "
                "will focus on your relevant experience."
            ),
            "closing_message": "Thank you for your time. A recruiter will review the interview and follow up.",
            "questions": _default_questions(job),
            "rubric": _default_rubric(),
            "draft_revision": 0,
            "active_version_id": None,
            "active_version_number": None,
            "updated_at": None,
        }

    questions = (
        supabase_admin.table("hr_interview_questions")
        .select("*")
        .eq("business_id", business_id)
        .eq("bank_id", bank["id"])
        .order("order_index")
        .execute()
    ).data or []
    rubric = (
        supabase_admin.table("hr_interview_rubric_criteria")
        .select("*")
        .eq("business_id", business_id)
        .eq("bank_id", bank["id"])
        .order("order_index")
        .execute()
    ).data or []
    return {
        "id": bank["id"],
        "business_id": business_id,
        "job_posting_id": job_id,
        "job_title": job.get("title") or "Untitled role",
        "settings": bank.get("settings") or HrInterviewSettings().model_dump(),
        "opening_message": bank.get("opening_message") or "",
        "closing_message": bank.get("closing_message") or "",
        "questions": questions,
        "rubric": rubric,
        "draft_revision": bank.get("draft_revision") or 1,
        "active_version_id": bank.get("active_version_id"),
        "active_version_number": _active_version_number(
            bank["id"], bank.get("active_version_id")
        ),
        "updated_at": bank.get("updated_at"),
    }


async def save_interview_bank(
    *,
    job_id: str,
    user_id: str,
    request: HrInterviewBankDraftUpsertRequest,
) -> dict[str, Any]:
    get_native_job(business_id=request.business_id, job_id=job_id)
    normalized_questions = [
        {
            **question.model_dump(exclude_none=True),
            "order_index": index,
        }
        for index, question in enumerate(request.questions)
    ]
    rubric_policy_rows = [
        {
            "text": " ".join(
                part
                for part in (
                    criterion.name,
                    criterion.description,
                    criterion.score_1_anchor,
                    criterion.score_3_anchor,
                    criterion.score_5_anchor,
                )
                if part
            )
        }
        for criterion in request.rubric
    ]
    all_compliance_results = await enforce_questions(
        [item["question_text"] for item in normalized_questions]
        + [item["text"] for item in rubric_policy_rows]
    )
    compliance_results = all_compliance_results[: len(normalized_questions)]

    existing = _get_bank_row(business_id=request.business_id, job_id=job_id)
    bank_payload = {
        "business_id": request.business_id,
        "job_posting_id": job_id,
        "settings": request.settings.model_dump(),
        "opening_message": request.opening_message.strip(),
        "closing_message": request.closing_message.strip(),
        "updated_by": user_id,
    }
    if existing:
        bank_payload["draft_revision"] = int(existing.get("draft_revision") or 1) + 1
        updated = (
            supabase_admin.table("hr_interview_banks")
            .update(bank_payload)
            .eq("id", existing["id"])
            .eq("business_id", request.business_id)
            .select("*")
            .execute()
        )
        bank = updated.data[0]
    else:
        bank_payload["created_by"] = user_id
        bank_payload["draft_revision"] = 1
        created = (
            supabase_admin.table("hr_interview_banks")
            .insert(bank_payload)
            .select("*")
            .execute()
        )
        bank = created.data[0]

    supabase_admin.table("hr_interview_questions").delete().eq(
        "bank_id", bank["id"]
    ).eq("business_id", request.business_id).execute()
    question_rows = []
    for item in normalized_questions:
        item.pop("id", None)
        question_rows.append(
            {
                **item,
                "business_id": request.business_id,
                "bank_id": bank["id"],
                "compliance_status": "approved",
                "compliance_policy_version": POLICY_VERSION,
            }
        )
    inserted_questions = []
    if question_rows:
        inserted_questions = (
            supabase_admin.table("hr_interview_questions")
            .insert(question_rows)
            .select("*")
            .execute()
        ).data or []

    supabase_admin.table("hr_interview_rubric_criteria").delete().eq(
        "bank_id", bank["id"]
    ).eq("business_id", request.business_id).execute()
    rubric_rows = []
    for index, criterion in enumerate(request.rubric):
        payload = criterion.model_dump(exclude_none=True)
        payload.pop("id", None)
        rubric_rows.append(
            {
                **payload,
                "order_index": index,
                "business_id": request.business_id,
                "bank_id": bank["id"],
            }
        )
    if rubric_rows:
        supabase_admin.table("hr_interview_rubric_criteria").insert(rubric_rows).execute()

    record_compliance_checks(
        business_id=request.business_id,
        bank_id=bank["id"],
        question_rows=inserted_questions,
        results=compliance_results,
        source="manual",
    )
    record_compliance_checks(
        business_id=request.business_id,
        bank_id=bank["id"],
        question_rows=rubric_policy_rows,
        results=all_compliance_results[len(normalized_questions) :],
        source="manual",
    )
    return get_interview_bank(business_id=request.business_id, job_id=job_id)


async def publish_interview_bank(
    *,
    business_id: str,
    job_id: str,
    user_id: str,
) -> dict[str, Any]:
    bank_payload = get_interview_bank(business_id=business_id, job_id=job_id)
    if not bank_payload.get("id"):
        raise InterviewBankValidationError("Save the interview draft before publishing.")

    enabled_questions = [
        question for question in bank_payload["questions"] if question.get("enabled")
    ]
    if len(enabled_questions) < 3:
        raise InterviewBankValidationError(
            "Enable at least 3 compliant questions before publishing."
        )
    if not bank_payload["rubric"]:
        raise InterviewBankValidationError("Add at least 1 scoring criterion before publishing.")
    total_weight = sum(float(item.get("weight") or 0) for item in bank_payload["rubric"])
    if abs(total_weight - 100) > 0.01:
        raise InterviewBankValidationError(
            f"Scoring rubric weights must total 100; current total is {total_weight:g}."
        )

    rubric_policy_rows = [
        {
            "text": " ".join(
                str(item.get(field) or "")
                for field in (
                    "name",
                    "description",
                    "score_1_anchor",
                    "score_3_anchor",
                    "score_5_anchor",
                )
            ).strip()
        }
        for item in bank_payload["rubric"]
    ]
    all_compliance_results = await enforce_questions(
        [item["question_text"] for item in enabled_questions]
        + [item["text"] for item in rubric_policy_rows]
    )
    compliance_results = all_compliance_results[: len(enabled_questions)]
    record_compliance_checks(
        business_id=business_id,
        bank_id=bank_payload["id"],
        question_rows=enabled_questions,
        results=compliance_results,
        source="publish",
    )
    record_compliance_checks(
        business_id=business_id,
        bank_id=bank_payload["id"],
        question_rows=rubric_policy_rows,
        results=all_compliance_results[len(enabled_questions) :],
        source="publish",
    )

    previous = (
        supabase_admin.table("hr_interview_bank_versions")
        .select("version_number")
        .eq("business_id", business_id)
        .eq("bank_id", bank_payload["id"])
        .order("version_number", desc=True)
        .limit(1)
        .execute()
    )
    version_number = (
        int(previous.data[0]["version_number"]) + 1 if previous.data else 1
    )
    snapshot = {
        "settings": bank_payload["settings"].model_dump()
        if isinstance(bank_payload["settings"], HrInterviewSettings)
        else bank_payload["settings"],
        "opening_message": bank_payload["opening_message"],
        "closing_message": bank_payload["closing_message"],
        "questions": enabled_questions,
        "rubric": bank_payload["rubric"],
    }
    published_at = datetime.now(timezone.utc).isoformat()
    created = (
        supabase_admin.table("hr_interview_bank_versions")
        .insert(
            {
                "business_id": business_id,
                "job_posting_id": job_id,
                "bank_id": bank_payload["id"],
                "version_number": version_number,
                "snapshot": snapshot,
                "compliance_policy_version": POLICY_VERSION,
                "published_by": user_id,
                "published_at": published_at,
            }
        )
        .select("id,version_number,published_at")
        .execute()
    )
    version = created.data[0]
    (
        supabase_admin.table("hr_interview_banks")
        .update({"active_version_id": version["id"], "updated_by": user_id})
        .eq("id", bank_payload["id"])
        .eq("business_id", business_id)
        .execute()
    )
    return {
        "active_version_id": version["id"],
        "version_number": version["version_number"],
        "published_at": version["published_at"],
    }
