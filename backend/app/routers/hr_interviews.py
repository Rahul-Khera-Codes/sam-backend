from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.schemas.hr_interviews import (
    HrHumanInterviewUpsertRequest,
    HrHumanInterviewEmailDraftRequest,
    HrHumanInterviewEmailDraftResponse,
    HrHumanInterviewResponse,
    HrInterviewAiSuggestRequest,
    HrInterviewAiSuggestResponse,
    HrInterviewBankDraftUpsertRequest,
    HrInterviewBankResponse,
    HrInterviewCandidateSessionRequest,
    HrInterviewDetailResponse,
    HrInterviewInviteRequest,
    HrInterviewInviteResponse,
    HrInterviewLiveSessionResponse,
    HrInterviewNotesUpdateRequest,
    HrInterviewPipelineResponse,
    HrInterviewPreviewRequest,
    HrInterviewPreviewResponse,
    HrInterviewPublicJoinResponse,
    HrInterviewRecordingDeleteResponse,
    HrInterviewPublishRequest,
    HrInterviewPublishResponse,
    HrInterviewSessionSummary,
    HrInterviewStatusUpdateRequest,
)
from app.services import livekit_service
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
from app.services.hr_interview_runtime_service import (
    HrInterviewNotFound,
    HrInterviewRuntimeError,
    create_ai_screen_invite,
    create_human_interview,
    delete_recording,
    get_detail,
    generate_human_interview_email_draft,
    list_pipeline,
    prepare_live_session,
    update_notes,
    update_status,
    validate_public_join_token,
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
    if isinstance(exc, HrInterviewNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, HrInterviewRuntimeError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/interviews/pipeline")
async def read_interview_pipeline(
    business_id: str,
    user_id: str = Depends(get_user_id),
) -> HrInterviewPipelineResponse:
    verify_business_access(user_id, business_id)
    try:
        return list_pipeline(business_id)
    except Exception as exc:
        logger.warning("Interview pipeline load failed for business %s: %s", business_id, exc)
        _raise_domain_error(exc)
        raise


@router.post("/interviews/invite")
async def invite_ai_screen_candidate(
    body: HrInterviewInviteRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewInviteResponse:
    _require_interview_admin(user_id, body.business_id)
    try:
        # The returned join URL is shown in the UI immediately; email delivery can
        # be attached to this same endpoint once a tenant sender is selected.
        return await create_ai_screen_invite(request=body, user_id=user_id)
    except Exception as exc:
        logger.warning("Interview invite failed for business %s: %s", body.business_id, exc)
        _raise_domain_error(exc)
        raise HTTPException(status_code=502, detail="Interview invite could not be created.") from exc


@router.post("/interviews/human")
async def create_human_interview_tracking(
    body: HrHumanInterviewUpsertRequest,
    user_id: str = Depends(get_user_id),
) -> HrHumanInterviewResponse:
    verify_business_access(user_id, body.business_id)
    try:
        return await create_human_interview(body)
    except Exception as exc:
        logger.warning("Human interview tracking failed for business %s: %s", body.business_id, exc)
        _raise_domain_error(exc)
        raise HTTPException(status_code=502, detail="Human interview tracking could not be saved.") from exc


@router.post("/interviews/human/email-draft")
async def suggest_human_interview_email(
    body: HrHumanInterviewEmailDraftRequest,
    user_id: str = Depends(get_user_id),
) -> HrHumanInterviewEmailDraftResponse:
    verify_business_access(user_id, body.business_id)
    try:
        return await generate_human_interview_email_draft(body)
    except Exception as exc:
        logger.warning("Human interview email draft failed for business %s: %s", body.business_id, exc)
        raise HTTPException(status_code=502, detail="Could not generate interview email draft.") from exc


@router.put("/interviews/{session_id}/status")
async def update_interview_session_status(
    session_id: str,
    body: HrInterviewStatusUpdateRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewSessionSummary:
    verify_business_access(user_id, body.business_id)
    try:
        return update_status(
            business_id=body.business_id,
            session_id=session_id,
            status=body.status,
            stage=body.stage,
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise


@router.put("/interviews/{session_id}/notes")
async def update_interview_session_notes(
    session_id: str,
    body: HrInterviewNotesUpdateRequest,
    user_id: str = Depends(get_user_id),
) -> HrInterviewSessionSummary:
    verify_business_access(user_id, body.business_id)
    try:
        return update_notes(
            business_id=body.business_id,
            session_id=session_id,
            recruiter_notes=body.recruiter_notes,
            recruiter_score=body.recruiter_score,
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise


@router.get("/interviews/{session_id}")
async def read_interview_detail(
    session_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
) -> HrInterviewDetailResponse:
    verify_business_access(user_id, business_id)
    try:
        return get_detail(business_id=business_id, session_id=session_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise


@router.delete("/interviews/{session_id}/recordings/{recording_id}")
async def delete_interview_recording(
    session_id: str,
    recording_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
) -> HrInterviewRecordingDeleteResponse:
    verify_business_access(user_id, business_id)
    try:
        return HrInterviewRecordingDeleteResponse(
            deleted=delete_recording(
                business_id=business_id,
                session_id=session_id,
                recording_id=recording_id,
            )
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise


@router.get("/interviews/join/{token}")
async def read_public_interview_join(token: str) -> HrInterviewPublicJoinResponse:
    try:
        return validate_public_join_token(token)
    except Exception as exc:
        _raise_domain_error(exc)
        raise


@router.post("/interviews/join/{token}/session")
async def create_public_interview_live_session(
    token: str,
    body: HrInterviewCandidateSessionRequest,
) -> HrInterviewLiveSessionResponse:
    try:
        join_info = validate_public_join_token(token)
        room_name = f"hr-interview-{join_info.session_id[:8]}-{uuid.uuid4().hex[:8]}"
        await livekit_service.create_room(room_name)
        session_row = prepare_live_session(token, room_name=room_name)
        participant_identity = f"candidate-{join_info.session_id[:12]}"
        user_token = livekit_service.generate_user_token(
            room_name,
            participant_identity,
            metadata={
                "session_type": "hr_interview",
                "business_id": join_info.business_id,
                "session_id": join_info.session_id,
                "candidate_name": join_info.candidate_name,
            },
        )
        metadata = {
            "session_type": "hr_interview",
            "business_id": join_info.business_id,
            "session_id": join_info.session_id,
            "avatar_enabled": body.avatar_enabled,
            "avatar_id": os.getenv("EMILY_AVATAR_ID", "073b60a9-89a8-45aa-8902-c358f64d2852"),
        }
        await livekit_service.create_hr_interviewer_agent_dispatch(room_name, metadata=metadata)
        return HrInterviewLiveSessionResponse(
            session_id=session_row["id"],
            room_name=room_name,
            token=user_token,
            livekit_url=settings.livekit_url,
            avatar_enabled=body.avatar_enabled,
        )
    except Exception as exc:
        logger.warning("Public interview session creation failed: %s", exc)
        _raise_domain_error(exc)
        raise HTTPException(status_code=502, detail="Interview session could not be started.") from exc


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
