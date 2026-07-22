from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_user_id, verify_business_access
from app.schemas.hr_interviews import (
    HrInterviewAiSuggestRequest,
    HrInterviewAiSuggestResponse,
    HrInterviewBankDraftUpsertRequest,
    HrInterviewBankResponse,
    HrInterviewPreviewRequest,
    HrInterviewPreviewResponse,
    HrInterviewPublishRequest,
    HrInterviewPublishResponse,
)
from app.services.hr_interview_bank_service import (
    InterviewBankNotFound,
    InterviewBankValidationError,
    get_interview_bank,
    get_native_job,
    publish_interview_bank,
    save_interview_bank,
)
from app.services.hr_interview_compliance_service import (
    InterviewComplianceError,
    InterviewComplianceUnavailable,
    record_compliance_checks,
)
from app.services.hr_interview_generation_service import (
    generate_interview_preview,
    generate_interview_suggestions,
)


router = APIRouter(prefix="/hr", tags=["hr-interviews"])
logger = logging.getLogger(__name__)


def _require_interview_admin(user_id: str, business_id: str) -> None:
    role = verify_business_access(user_id, business_id)
    if role not in ("super_admin", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only business administrators can edit or publish interview plans.",
        )


def _raise_domain_error(exc: Exception) -> None:
    if isinstance(exc, InterviewBankNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, InterviewComplianceError):
        detail = str(exc)
        if exc.categories:
            detail += f" Blocked categories: {', '.join(exc.categories)}."
        raise HTTPException(status_code=422, detail=detail) from exc
    if isinstance(exc, InterviewComplianceUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, InterviewBankValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/interview-bank")
async def read_interview_bank(
    job_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
) -> HrInterviewBankResponse:
    verify_business_access(user_id, business_id)
    try:
        return HrInterviewBankResponse(
            **get_interview_bank(business_id=business_id, job_id=job_id)
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise


@router.put("/jobs/{job_id}/interview-bank")
async def update_interview_bank(
    job_id: str,
    body: HrInterviewBankDraftUpsertRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewBankResponse:
    _require_interview_admin(user_id, body.business_id)
    try:
        payload = await save_interview_bank(job_id=job_id, user_id=user_id, request=body)
        return HrInterviewBankResponse(**payload)
    except Exception as exc:
        logger.warning("Interview draft save failed for job %s: %s", job_id, exc)
        _raise_domain_error(exc)
        raise


@router.post("/jobs/{job_id}/interview-bank/ai-suggest")
async def suggest_interview_content(
    job_id: str,
    body: HrInterviewAiSuggestRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewAiSuggestResponse:
    _require_interview_admin(user_id, body.business_id)
    try:
        job = get_native_job(business_id=body.business_id, job_id=job_id)
        bank = get_interview_bank(business_id=body.business_id, job_id=job_id)
        result = await generate_interview_suggestions(
            job=job,
            count=body.count,
            guidance=body.guidance,
            existing_questions=bank["questions"],
            existing_rubric=bank["rubric"],
        )
        compliance_results = result.pop("_compliance_results")
        record_compliance_checks(
            business_id=body.business_id,
            bank_id=bank.get("id"),
            question_rows=[question.model_dump() for question in result["questions"]],
            results=compliance_results,
            source="ai_generation",
        )
        return HrInterviewAiSuggestResponse(**result)
    except Exception as exc:
        logger.warning("Interview AI suggestion failed for job %s: %s", job_id, exc)
        _raise_domain_error(exc)
        raise HTTPException(
            status_code=502,
            detail="AI interview suggestions are unavailable right now.",
        ) from exc


@router.post("/jobs/{job_id}/interview-bank/preview")
async def preview_interview(
    job_id: str,
    body: HrInterviewPreviewRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewPreviewResponse:
    verify_business_access(user_id, body.business_id)
    try:
        job = get_native_job(business_id=body.business_id, job_id=job_id)
        bank = get_interview_bank(business_id=body.business_id, job_id=job_id)
        result = await generate_interview_preview(
            job=job,
            settings_payload=bank["settings"].model_dump()
            if hasattr(bank["settings"], "model_dump")
            else bank["settings"],
            opening_message=bank["opening_message"],
            questions=bank["questions"],
        )
        compliance_results = result.pop("_compliance_results")
        interviewer_turns = [
            {"text": turn["text"]}
            for turn in result["turns"]
            if turn["speaker"] == "interviewer"
        ]
        record_compliance_checks(
            business_id=body.business_id,
            bank_id=bank.get("id"),
            question_rows=interviewer_turns,
            results=compliance_results,
            source="preview",
        )
        return HrInterviewPreviewResponse(**result)
    except Exception as exc:
        logger.warning("Interview preview failed for job %s: %s", job_id, exc)
        _raise_domain_error(exc)
        raise HTTPException(
            status_code=502,
            detail="The safe interview preview is unavailable right now.",
        ) from exc


@router.post("/jobs/{job_id}/interview-bank/publish")
async def publish_interview_plan(
    job_id: str,
    body: HrInterviewPublishRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewPublishResponse:
    _require_interview_admin(user_id, body.business_id)
    try:
        return HrInterviewPublishResponse(
            **(
                await publish_interview_bank(
                    business_id=body.business_id,
                    job_id=job_id,
                    user_id=user_id,
                )
            )
        )
    except Exception as exc:
        logger.warning("Interview publish failed for job %s: %s", job_id, exc)
        _raise_domain_error(exc)
        raise
