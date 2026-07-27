from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.hr_interviews import (
    HrHumanInterviewUpsertRequest,
    HrHumanInterviewEmailDraftRequest,
    HrHumanInterviewEmailDraftResponse,
    HrHumanInterviewResponse,
    HrInterviewDetailResponse,
    HrInterviewInviteRequest,
    HrInterviewInviteResponse,
    HrInterviewOutcomeResponse,
    HrInterviewPipelineResponse,
    HrInterviewPublicJoinResponse,
    HrInterviewRecordingResponse,
    HrInterviewSessionSummary,
    HrInterviewTranscriptTurnResponse,
)
from app.services.email_service import GMAIL_SEND_URL, _build_mime_message, get_token_row, get_valid_access_token

HUMAN_INTERVIEW_DRAFT_MODEL = "gpt-4o-mini"


class HrInterviewRuntimeError(ValueError):
    pass


class HrInterviewNotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _frontend_base_url() -> str:
    configured = os.getenv("FRONTEND_APP_URL") or os.getenv("VITE_APP_URL")
    if configured:
        return configured.rstrip("/")
    return settings.cors_origins_list[0].rstrip("/") if settings.cors_origins_list else "http://localhost:5173"


def _join_url(token: str, frontend_base_url: str | None = None) -> str:
    base_url = (frontend_base_url or "").strip().rstrip("/") or _frontend_base_url()
    return f"{base_url}/hr/interview/join/{token}"


def _get_any_gmail_token_row(business_id: str) -> dict[str, Any] | None:
    row = get_token_row(supabase_admin, business_id)
    if row:
        return row
    result = (
        supabase_admin.table("gmail_tokens")
        .select("*")
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


async def _resolve_gmail_sender_email(access_token: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code == 200:
            return response.json().get("email", "") or ""
    except Exception:
        return ""
    return ""


def _get_job(business_id: str, job_posting_id: str) -> dict[str, Any]:
    result = (
        supabase_admin.table("hr_job_postings")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", job_posting_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HrInterviewNotFound("Job posting not found.")
    return result.data[0]


def _get_active_version(business_id: str, job_posting_id: str) -> dict[str, Any]:
    bank = (
        supabase_admin.table("hr_interview_banks")
        .select("id,active_version_id")
        .eq("business_id", business_id)
        .eq("job_posting_id", job_posting_id)
        .limit(1)
        .execute()
    )
    if not bank.data or not bank.data[0].get("active_version_id"):
        raise HrInterviewRuntimeError("Publish an interview plan for this job before inviting candidates.")
    version_id = bank.data[0]["active_version_id"]
    version = (
        supabase_admin.table("hr_interview_bank_versions")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", version_id)
        .limit(1)
        .execute()
    )
    if not version.data:
        raise HrInterviewRuntimeError("The active interview plan version could not be loaded.")
    snapshot = version.data[0].get("snapshot") or {}
    questions = [item for item in (snapshot.get("questions") or []) if item.get("enabled", True)]
    if not questions:
        raise HrInterviewRuntimeError("The active interview plan has no enabled questions.")
    return version.data[0]


def _first_row(table: str, columns: str, *, session_id: str, business_id: str) -> dict[str, Any] | None:
    result = (
        supabase_admin.table(table)
        .select(columns)
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _has_rows(table: str, *, session_id: str, business_id: str) -> bool:
    return _first_row(table, "id", session_id=session_id, business_id=business_id) is not None


def _outcome_for(session_id: str, business_id: str) -> HrInterviewOutcomeResponse | None:
    row = _first_row(
        "hr_interview_outcomes",
        "*",
        session_id=session_id,
        business_id=business_id,
    )
    if not row:
        return None
    return HrInterviewOutcomeResponse(
        id=row["id"],
        model=row.get("model") or "",
        total_score=float(row.get("total_score") or 0),
        recommendation=row.get("recommendation") or "review",
        summary=row.get("summary") or "",
        strengths=row.get("strengths") or [],
        concerns=row.get("concerns") or [],
        criterion_scores=row.get("criterion_scores") or [],
        generated_at=row.get("generated_at"),
    )


def _summarize_session(row: dict[str, Any], job_title: str = "") -> HrInterviewSessionSummary:
    business_id = row["business_id"]
    session_id = row["id"]
    return HrInterviewSessionSummary(
        id=session_id,
        business_id=business_id,
        job_posting_id=row["job_posting_id"],
        job_title=job_title,
        interview_kind=row.get("interview_kind") or "ai_screen",
        status=row.get("status") or "draft",
        stage=row.get("stage") or "",
        candidate_name=row.get("candidate_name") or "",
        candidate_email=row.get("candidate_email") or "",
        candidate_phone=row.get("candidate_phone") or "",
        active_version_id=row.get("active_version_id"),
        active_version_number=row.get("active_version_number"),
        invited_at=row.get("invited_at"),
        opened_at=row.get("opened_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        reviewed_at=row.get("reviewed_at"),
        human_interview_provider=row.get("human_interview_provider"),
        human_interview_reference=row.get("human_interview_reference"),
        human_interview_scheduled_at=row.get("human_interview_scheduled_at"),
        recruiter_notes=row.get("recruiter_notes") or "",
        recruiter_score=float(row["recruiter_score"]) if row.get("recruiter_score") is not None else None,
        greenhouse_sync_status=row.get("greenhouse_sync_status") or "not_applicable",
        has_transcript=_has_rows("hr_interview_transcript_turns", session_id=session_id, business_id=business_id),
        has_recording=_has_rows("hr_interview_recordings", session_id=session_id, business_id=business_id),
        outcome=_outcome_for(session_id, business_id),
    )


def _job_titles_for(rows: list[dict[str, Any]], business_id: str) -> dict[str, str]:
    titles: dict[str, str] = {}
    for row in rows:
        job_id = row.get("job_posting_id")
        if not job_id or job_id in titles:
            continue
        try:
            titles[job_id] = _get_job(business_id, job_id).get("title") or "Untitled role"
        except HrInterviewNotFound:
            titles[job_id] = "Unknown role"
    return titles


async def _send_interview_invite_email(
    *,
    business_id: str,
    candidate_email: str,
    candidate_name: str,
    job_title: str,
    join_url: str,
) -> tuple[str, str]:
    token_row = _get_any_gmail_token_row(business_id)
    if not token_row:
        return "skipped", "No connected Gmail sender was found for this business."
    access_token = await get_valid_access_token(
        supabase_admin,
        business_id,
        settings.google_client_id,
        settings.google_client_secret,
        location_id=token_row.get("location_id"),
    )
    sender = token_row.get("google_email") or ""
    if access_token and not sender:
        sender = await _resolve_gmail_sender_email(access_token)
        if sender:
            try:
                supabase_admin.table("gmail_tokens").update({"google_email": sender}).eq("id", token_row["id"]).execute()
            except Exception:
                pass
    if not access_token or not sender:
        return "failed", "Connected Gmail sender was found, but its token could not be refreshed. Disconnect and reconnect Gmail from Business Settings."
    subject = f"AI screening interview for {job_title}"
    plain = (
        f"Hi {candidate_name},\n\n"
        f"You have been invited to complete an AI screening interview for {job_title}.\n\n"
        f"Start your interview here:\n{join_url}\n\n"
        "Please use a quiet place and allow microphone access. Your audio will be recorded for recruiter review.\n"
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.6;color:#0f172a">
      <h2>AI screening interview</h2>
      <p>Hi {candidate_name},</p>
      <p>You have been invited to complete an AI screening interview for <strong>{job_title}</strong>.</p>
      <p><a href="{join_url}" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none">Start interview</a></p>
      <p>Please use a quiet place and allow microphone access. Your audio will be recorded for recruiter review.</p>
    </div>
    """
    raw = _build_mime_message(sender, candidate_email, subject, html, plain)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
    if response.status_code not in (200, 201):
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        return "failed", f"Gmail API rejected the invite email ({response.status_code}): {detail}"
    return "sent", f"Invite email sent from {sender}."


async def _send_human_interview_email(
    *,
    business_id: str,
    candidate_email: str,
    subject: str,
    message: str,
) -> tuple[str, str]:
    token_row = _get_any_gmail_token_row(business_id)
    if not token_row:
        return "skipped", "No connected Gmail sender was found for this business."
    access_token = await get_valid_access_token(
        supabase_admin,
        business_id,
        settings.google_client_id,
        settings.google_client_secret,
        location_id=token_row.get("location_id"),
    )
    sender = token_row.get("google_email") or ""
    if access_token and not sender:
        sender = await _resolve_gmail_sender_email(access_token)
        if sender:
            try:
                supabase_admin.table("gmail_tokens").update({"google_email": sender}).eq("id", token_row["id"]).execute()
            except Exception:
                pass
    if not access_token or not sender:
        return "failed", "Connected Gmail sender was found, but its token could not be refreshed. Disconnect and reconnect Gmail from Business Settings."

    html = "<div style='font-family:Arial,sans-serif;line-height:1.6;color:#0f172a'>" + "".join(
        f"<p>{line}</p>" for line in message.splitlines() if line.strip()
    ) + "</div>"
    raw = _build_mime_message(sender, candidate_email, subject, html, message)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
    if response.status_code not in (200, 201):
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        return "failed", f"Gmail API rejected the human interview email ({response.status_code}): {detail}"
    return "sent", f"Human interview email sent from {sender}."


async def generate_human_interview_email_draft(
    request: HrHumanInterviewEmailDraftRequest,
) -> HrHumanInterviewEmailDraftResponse:
    job = _get_job(request.business_id, request.job_posting_id)
    prompt = {
        "job_title": job.get("title") or "the role",
        "candidate_name": request.candidate_name or "Candidate",
        "provider": request.provider or "the interview location / meeting details",
        "scheduled_at": request.scheduled_at or "",
        "guidance": request.guidance,
        "requirements": [
            "Draft a professional physical/human-led interview invitation email.",
            "Mention this is a human-led interview, not the AI screen.",
            "Keep the tone clear, warm, and concise.",
            "Include the job title, schedule if provided, and provider/location details if provided.",
            "Ask the candidate to reply if they need to reschedule.",
            "Return JSON only with subject and message.",
        ],
    }
    response = await AsyncOpenAI(api_key=settings.openai_api_key, timeout=30.0, max_retries=1).chat.completions.create(
        model=HUMAN_INTERVIEW_DRAFT_MODEL,
        temperature=0.35,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You draft recruiter interview invitation emails. Return JSON only."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return HrHumanInterviewEmailDraftResponse(
        subject=str(payload.get("subject") or f"Interview invitation for {job.get('title') or 'the role'}"),
        message=str(payload.get("message") or ""),
    )


async def create_ai_screen_invite(
    *,
    request: HrInterviewInviteRequest,
    user_id: str,
) -> HrInterviewInviteResponse:
    _get_job(request.business_id, request.job_posting_id)
    version = _get_active_version(request.business_id, request.job_posting_id)
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    now = _now()
    row = {
        "business_id": request.business_id,
        "job_posting_id": request.job_posting_id,
        "candidate_id": request.candidate_id,
        "application_id": request.application_id,
        "candidate_name": request.candidate_name.strip(),
        "candidate_email": request.candidate_email.strip(),
        "candidate_phone": request.candidate_phone.strip(),
        "interview_kind": "ai_screen",
        "status": "invited",
        "stage": "ai_screen",
        "active_version_id": version["id"],
        "active_version_number": version.get("version_number"),
        "invite_token_hash": _hash_token(token),
        "invite_expires_at": expires_at,
        "invited_by": user_id,
        "invited_at": now,
        "greenhouse_candidate_id": request.greenhouse_candidate_id,
        "greenhouse_application_id": request.greenhouse_application_id,
        "greenhouse_sync_status": "mocked",
    }
    created = (
        supabase_admin.table("hr_interview_sessions")
        .insert(row)
        .select("*")
        .execute()
    )
    session = created.data[0]
    job_title = _get_job(request.business_id, request.job_posting_id).get("title") or ""
    join_url = _join_url(token, request.frontend_base_url)
    email_status = "not_attempted"
    email_message = ""
    try:
        email_status, email_message = await _send_interview_invite_email(
            business_id=request.business_id,
            candidate_email=request.candidate_email.strip(),
            candidate_name=request.candidate_name.strip(),
            job_title=job_title or "the role",
            join_url=join_url,
        )
    except Exception as exc:
        email_status = "failed"
        email_message = f"Invite link was created, but email delivery failed: {exc}"
    return HrInterviewInviteResponse(
        session=_summarize_session(session, job_title),
        join_url=join_url,
        email_delivery_status=email_status,
        email_delivery_message=email_message,
    )


async def create_human_interview(request: HrHumanInterviewUpsertRequest) -> HrHumanInterviewResponse:
    job = _get_job(request.business_id, request.job_posting_id)
    row = {
        "business_id": request.business_id,
        "job_posting_id": request.job_posting_id,
        "candidate_name": request.candidate_name.strip(),
        "candidate_email": request.candidate_email.strip(),
        "candidate_phone": request.candidate_phone.strip(),
        "interview_kind": "human_external",
        "status": request.status,
        "stage": request.stage.strip() or "human_interview",
        "human_interview_provider": request.provider.strip(),
        "human_interview_reference": request.reference.strip(),
        "human_interview_scheduled_at": request.scheduled_at,
        "recruiter_notes": request.recruiter_notes.strip(),
        "recruiter_score": request.recruiter_score,
        "greenhouse_sync_status": "mocked",
    }
    created = supabase_admin.table("hr_interview_sessions").insert(row).select("*").execute()
    subject = f"Interview invitation for {job.get('title') or 'the role'}"
    email_status = "not_attempted"
    email_message = ""
    if request.candidate_email and request.recruiter_notes.strip():
        email_status, email_message = await _send_human_interview_email(
            business_id=request.business_id,
            candidate_email=request.candidate_email.strip(),
            subject=subject,
            message=request.recruiter_notes.strip(),
        )
    return HrHumanInterviewResponse(
        session=_summarize_session(created.data[0], job.get("title") or ""),
        email_delivery_status=email_status,
        email_delivery_message=email_message,
    )


def list_pipeline(business_id: str) -> HrInterviewPipelineResponse:
    result = (
        supabase_admin.table("hr_interview_sessions")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = result.data or []
    titles = _job_titles_for(rows, business_id)
    summaries = [_summarize_session(row, titles.get(row.get("job_posting_id"), "")) for row in rows]
    ai_screens = [item for item in summaries if item.interview_kind == "ai_screen"]
    human_interviews = [item for item in summaries if item.interview_kind == "human_external"]
    return HrInterviewPipelineResponse(
        ai_screens=ai_screens,
        human_interviews=human_interviews,
        totals={
            "ai_screens": len(ai_screens),
            "human_interviews": len(human_interviews),
            "completed": sum(1 for item in summaries if item.status in {"completed", "reviewed"}),
            "pending": sum(1 for item in summaries if item.status in {"draft", "invited", "opened", "in_progress"}),
        },
    )


def update_status(
    *,
    business_id: str,
    session_id: str,
    status: str,
    stage: str | None = None,
) -> HrInterviewSessionSummary:
    updates: dict[str, Any] = {"status": status}
    if stage:
        updates["stage"] = stage
    if status == "reviewed":
        updates["reviewed_at"] = _now()
    updated = (
        supabase_admin.table("hr_interview_sessions")
        .update(updates)
        .eq("business_id", business_id)
        .eq("id", session_id)
        .select("*")
        .execute()
    )
    if not updated.data:
        raise HrInterviewNotFound("Interview session not found.")
    job_title = _get_job(business_id, updated.data[0]["job_posting_id"]).get("title") or ""
    return _summarize_session(updated.data[0], job_title)


def update_notes(
    *,
    business_id: str,
    session_id: str,
    recruiter_notes: str,
    recruiter_score: float | None,
) -> HrInterviewSessionSummary:
    updated = (
        supabase_admin.table("hr_interview_sessions")
        .update({"recruiter_notes": recruiter_notes, "recruiter_score": recruiter_score})
        .eq("business_id", business_id)
        .eq("id", session_id)
        .select("*")
        .execute()
    )
    if not updated.data:
        raise HrInterviewNotFound("Interview session not found.")
    job_title = _get_job(business_id, updated.data[0]["job_posting_id"]).get("title") or ""
    return _summarize_session(updated.data[0], job_title)


def _signed_recording_url(bucket: str, path: str) -> str | None:
    try:
        result = supabase_admin.storage.from_(bucket).create_signed_url(path, 60 * 60)
        if isinstance(result, dict):
            return result.get("signedURL") or result.get("signed_url")
    except Exception:
        return None
    return None


def get_detail(*, business_id: str, session_id: str) -> HrInterviewDetailResponse:
    result = (
        supabase_admin.table("hr_interview_sessions")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HrInterviewNotFound("Interview session not found.")
    session = result.data[0]
    job_title = _get_job(business_id, session["job_posting_id"]).get("title") or ""
    transcript_rows = (
        supabase_admin.table("hr_interview_transcript_turns")
        .select("*")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .order("sequence_order")
        .execute()
    ).data or []
    recording_rows = (
        supabase_admin.table("hr_interview_recordings")
        .select("*")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    recordings = [
        HrInterviewRecordingResponse(
            id=row["id"],
            status=row.get("status") or "processing",
            storage_bucket=row.get("storage_bucket") or "hr-interview-recordings",
            storage_path=row.get("storage_path") or "",
            duration_seconds=row.get("duration_seconds") or 0,
            signed_url=_signed_recording_url(row.get("storage_bucket") or "hr-interview-recordings", row.get("storage_path") or ""),
            created_at=row.get("created_at"),
        )
        for row in recording_rows
    ]
    return HrInterviewDetailResponse(
        session=_summarize_session(session, job_title),
        transcript=[
            HrInterviewTranscriptTurnResponse(
                id=row["id"],
                speaker=row.get("speaker") or "system",
                text=row.get("text") or "",
                question_id=row.get("question_id"),
                question_order=row.get("question_order"),
                sequence_order=row.get("sequence_order") or 0,
                created_at=row.get("created_at"),
            )
            for row in transcript_rows
        ],
        recordings=recordings,
    )


def delete_recording(*, business_id: str, session_id: str, recording_id: str) -> bool:
    result = (
        supabase_admin.table("hr_interview_recordings")
        .select("*")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .eq("id", recording_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HrInterviewNotFound("Interview recording not found.")
    row = result.data[0]
    bucket = row.get("storage_bucket") or "hr-interview-recordings"
    path = row.get("storage_path") or ""
    if path:
        try:
            supabase_admin.storage.from_(bucket).remove([path])
        except Exception:
            # Keep deleting the metadata row so broken/orphaned storage entries
            # do not block recruiter cleanup.
            pass
    supabase_admin.table("hr_interview_recordings").delete().eq("id", recording_id).eq("business_id", business_id).execute()
    return True


def validate_public_join_token(token: str) -> HrInterviewPublicJoinResponse:
    row = _session_for_token(token)
    if row.get("status") == "invited":
        supabase_admin.table("hr_interview_sessions").update({
            "status": "opened",
            "opened_at": _now(),
        }).eq("id", row["id"]).execute()
        row["status"] = "opened"
    job = _get_job(row["business_id"], row["job_posting_id"])
    version = _get_active_version(row["business_id"], row["job_posting_id"])
    settings_payload = (version.get("snapshot") or {}).get("settings") or {}
    return HrInterviewPublicJoinResponse(
        session_id=row["id"],
        business_id=row["business_id"],
        job_title=job.get("title") or "Interview",
        candidate_name=row.get("candidate_name") or "Candidate",
        status=row.get("status") or "opened",
        expires_at=row.get("invite_expires_at"),
        interview_minutes=int(settings_payload.get("duration_minutes") or 45),
        avatar_available=True,
    )


def _session_for_token(token: str) -> dict[str, Any]:
    result = (
        supabase_admin.table("hr_interview_sessions")
        .select("*")
        .eq("invite_token_hash", _hash_token(token))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HrInterviewNotFound("Interview link is invalid.")
    row = result.data[0]
    expires_at = row.get("invite_expires_at")
    if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.now(timezone.utc):
        supabase_admin.table("hr_interview_sessions").update({"status": "expired"}).eq("id", row["id"]).execute()
        raise HrInterviewRuntimeError("Interview link has expired.")
    if row.get("status") in {"completed", "reviewed", "cancelled", "expired"}:
        raise HrInterviewRuntimeError("This interview link is no longer active.")
    return row


def prepare_live_session(token: str, *, room_name: str) -> dict[str, Any]:
    row = _session_for_token(token)
    updates = {
        "status": "in_progress",
        "started_at": row.get("started_at") or _now(),
        "livekit_room_name": room_name,
    }
    updated = (
        supabase_admin.table("hr_interview_sessions")
        .update(updates)
        .eq("id", row["id"])
        .select("*")
        .execute()
    )
    return updated.data[0] if updated.data else row
