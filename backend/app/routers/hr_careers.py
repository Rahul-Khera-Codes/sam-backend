"""
Public HR careers pages.

Unauthenticated endpoints backing the public job post webpage and apply
flow (AIE-31). No auth dependency on any route here — candidates browsing
and applying to a job posting are not app users.
"""

import json
import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.hr import (
    HrJobApplicationSubmitResponse,
    HrJobPublicResponse,
    HrParsedResumeResponse,
)
from app.services.hr_document_embedding_service import extract_pdf_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/careers", tags=["hr-careers"])

APPLICATIONS_BUCKET = "hr-job-applications"
RESUME_PARSING_MODEL = "gpt-4o-mini"


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=45.0, max_retries=1)


def _validate_pdf_upload(file: UploadFile) -> None:
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        filename_lower = (file.filename or "").lower()
        if not filename_lower.endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Only PDF files are allowed")


def _fetch_job(job_id: str) -> dict:
    result = (
        supabase_admin.table("hr_job_postings")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="This job posting is not available.")
    return result.data[0]


def _fetch_job_accepting_applications(job_id: str) -> dict:
    job = _fetch_job(job_id)
    if job.get("status") != "active":
        raise HTTPException(status_code=409, detail="This job isn't accepting applications yet.")
    return job


@router.get("/jobs/{job_id}")
async def get_public_job(job_id: str) -> HrJobPublicResponse:
    job = _fetch_job(job_id)

    business = (
        supabase_admin.table("businesses")
        .select("name,logo_url")
        .eq("id", job["business_id"])
        .limit(1)
        .execute()
    ).data or [{}]
    business_row = business[0]

    return HrJobPublicResponse(
        id=job["id"],
        title=job.get("title") or "",
        is_accepting_applications=job.get("status") == "active",
        department=job.get("department") or "",
        location=job.get("location") or "",
        location_type=job.get("location_type") or "",
        employment_type=job.get("employment_type") or "",
        summary=job.get("summary") or "",
        responsibilities=job.get("responsibilities") or "",
        qualifications=job.get("qualifications") or "",
        benefits=job.get("benefits") or "",
        pay_min=job.get("pay_min") or "",
        pay_max=job.get("pay_max") or "",
        pay_period=job.get("pay_period") or "",
        business_name=business_row.get("name") or "",
        business_logo_url=business_row.get("logo_url"),
    )


@router.post("/jobs/{job_id}/parse-resume")
async def parse_resume(job_id: str, resume: UploadFile = File(...)) -> HrParsedResumeResponse:
    _fetch_job_accepting_applications(job_id)
    _validate_pdf_upload(resume)

    file_bytes = await resume.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded resume is empty")

    resume_text = extract_pdf_text(file_bytes)
    if not resume_text:
        return HrParsedResumeResponse()

    response = await _client().chat.completions.create(
        model=RESUME_PARSING_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract the candidate's contact information from this resume text. "
                    'Return JSON only, matching {"name": "", "email": "", "phone": "", "location": ""}. '
                    "Use an empty string for any field you cannot find. Do not guess."
                ),
            },
            {"role": "user", "content": resume_text[:12000]},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return HrParsedResumeResponse(
        name=str(payload.get("name") or ""),
        email=str(payload.get("email") or ""),
        phone=str(payload.get("phone") or ""),
        location=str(payload.get("location") or ""),
    )


@router.post("/jobs/{job_id}/apply")
async def submit_application(
    job_id: str,
    candidate_name: str = Form(...),
    candidate_email: str = Form(...),
    candidate_phone: str = Form(""),
    candidate_location: str = Form(""),
    resume: UploadFile = File(...),
    cover_letter: UploadFile | None = File(None),
) -> HrJobApplicationSubmitResponse:
    job = _fetch_job_accepting_applications(job_id)
    _validate_pdf_upload(resume)

    resume_bytes = await resume.read()
    if not resume_bytes:
        raise HTTPException(status_code=422, detail="Resume file is empty")

    application_id = str(uuid.uuid4())
    safe_resume_name = (resume.filename or "resume.pdf").replace(" ", "_")
    resume_storage_path = f"{job['business_id']}/{application_id}_resume_{safe_resume_name}"

    uploaded_paths = []
    try:
        supabase_admin.storage.from_(APPLICATIONS_BUCKET).upload(
            resume_storage_path,
            resume_bytes,
            {"content-type": "application/pdf"},
        )
        uploaded_paths.append(resume_storage_path)

        cover_letter_storage_path = None
        cover_letter_file_name = None
        if cover_letter is not None and cover_letter.filename:
            _validate_pdf_upload(cover_letter)
            cover_letter_bytes = await cover_letter.read()
            if cover_letter_bytes:
                safe_cover_name = cover_letter.filename.replace(" ", "_")
                cover_letter_storage_path = (
                    f"{job['business_id']}/{application_id}_cover_letter_{safe_cover_name}"
                )
                supabase_admin.storage.from_(APPLICATIONS_BUCKET).upload(
                    cover_letter_storage_path,
                    cover_letter_bytes,
                    {"content-type": "application/pdf"},
                )
                uploaded_paths.append(cover_letter_storage_path)
                cover_letter_file_name = cover_letter.filename
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Application file upload failed: %s", e)
        for path in uploaded_paths:
            try:
                supabase_admin.storage.from_(APPLICATIONS_BUCKET).remove([path])
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Failed to upload application files")

    row = {
        "id": application_id,
        "business_id": job["business_id"],
        "job_posting_id": job["id"],
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
        "candidate_phone": candidate_phone,
        "candidate_location": candidate_location,
        "resume_storage_path": resume_storage_path,
        "resume_file_name": resume.filename or safe_resume_name,
        "cover_letter_storage_path": cover_letter_storage_path,
        "cover_letter_file_name": cover_letter_file_name,
    }

    try:
        result = supabase_admin.table("hr_job_applications").insert(row).execute()
        if not result.data:
            raise Exception("Insert returned no data")
        inserted = result.data[0]
    except Exception as e:
        logger.error("DB insert failed after application upload: %s", e)
        for path in uploaded_paths:
            try:
                supabase_admin.storage.from_(APPLICATIONS_BUCKET).remove([path])
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Failed to save application")

    return HrJobApplicationSubmitResponse(
        id=inserted["id"],
        submitted_at=inserted["submitted_at"],
    )
