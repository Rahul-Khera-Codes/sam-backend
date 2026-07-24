from __future__ import annotations

from datetime import datetime, timezone
import uuid
import os

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_user_id, require_business_access, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.documents import OnboardingChatRequest, OnboardingChatResponse
from app.schemas.hr import (
    HrDashboardPostingResponse,
    HrDraftAssistRequest,
    HrDraftAssistResponse,
    HrJobPostingResponse,
    HrJobsResponse,
    HrJobPostingUpsertRequest,
)
from app.services.hr_drafting_service import generate_hr_draft_assistance
from app.services.hr_onboarding_chat_service import answer_onboarding_question
from app.services.greenhouse_service import GreenhouseError, fetch_jobs, normalize_greenhouse_job
from app.services import livekit_service

router = APIRouter(prefix="/hr", tags=["hr"])
logger = logging.getLogger(__name__)


class HrWorkspaceJobPayload(BaseModel):
    dashboard: dict
    job_postings: dict


class HrOnboardingVoiceSessionRequest(BaseModel):
    business_id: str
    avatar_enabled: bool = False


class HrOnboardingVoiceSessionResponse(BaseModel):
    room_name: str
    token: str
    livekit_url: str
    avatar_available: bool


@router.get("/mock-workspace")
async def get_hr_mock_workspace(
    business_id: str,
    _: str = Depends(require_business_access()),
):
    return {
        "dashboard": {
            "stats": [
                {
                    "title": "Total Applicants",
                    "value": "1,248",
                    "change": "+8%",
                    "tint": "bg-blue-50 text-blue-600",
                    "icon": "users",
                },
                {
                    "title": "Pending Review",
                    "value": "84",
                    "change": "+12%",
                    "tint": "bg-amber-50 text-amber-600",
                    "icon": "briefcase",
                },
                {
                    "title": "Active Interviews",
                    "value": "32",
                    "change": "+6%",
                    "tint": "bg-emerald-50 text-emerald-600",
                    "icon": "calendar",
                },
            ],
            "funnel_stages": [
                {"label": "Applicants", "value": 1248, "width": "100%", "tone": "bg-blue-500"},
                {"label": "AI Screened", "value": 480, "width": "72%", "tone": "bg-blue-400"},
                {"label": "Interviewed", "value": 120, "width": "40%", "tone": "bg-sky-400"},
                {"label": "Hired", "value": 16, "width": "12%", "tone": "bg-cyan-300"},
            ],
            "active_job_postings": [
                {
                    "role": "Senior Frontend Developer",
                    "team": "Engineering",
                    "applicants": 142,
                    "linkedin": "Active",
                    "indeed": "Active",
                    "aiStatus": "Screening",
                },
                {
                    "role": "Product Designer",
                    "team": "Design",
                    "applicants": 89,
                    "linkedin": "Active",
                    "indeed": "Paused",
                    "aiStatus": "Waiting Review",
                },
                {
                    "role": "Marketing Manager",
                    "team": "Marketing",
                    "applicants": 215,
                    "linkedin": "Active",
                    "indeed": "Active",
                    "aiStatus": "Scheduling",
                },
            ],
        },
        "job_postings": {
            "stat_cards": [
                {"label": "Total Postings", "value": "18", "iconClassName": "bg-blue-50 text-blue-600"},
                {"label": "Active", "value": "11", "iconClassName": "bg-emerald-50 text-emerald-600"},
                {"label": "Draft", "value": "4", "iconClassName": "bg-amber-50 text-amber-600"},
                {"label": "Closed", "value": "3", "iconClassName": "bg-slate-100 text-slate-500"},
            ],
            "postings": [
                {
                    "id": "job-1",
                    "title": "Senior Product Designer",
                    "employmentType": "Hybrid - Full time",
                    "department": "Design",
                    "location": "Remote",
                    "postedOn": "Jun 1, 2024",
                    "platforms": ["Li", "In"],
                    "applicants": 47,
                    "applicantBarClassName": "bg-blue-500",
                    "status": "Active",
                },
                {
                    "id": "job-2",
                    "title": "Frontend Engineer",
                    "employmentType": "Hybrid - Full time",
                    "department": "Engineering",
                    "location": "Hybrid - NYC",
                    "postedOn": "May 20, 2024",
                    "platforms": ["Li", "In"],
                    "applicants": 31,
                    "applicantBarClassName": "bg-blue-500",
                    "status": "Active",
                },
                {
                    "id": "job-3",
                    "title": "HR Generalist",
                    "employmentType": "On-site - Full time",
                    "department": "Human Resources",
                    "location": "On-site - LA",
                    "postedOn": "May 20, 2024",
                    "platforms": ["Li", "In"],
                    "applicants": 23,
                    "applicantBarClassName": "bg-blue-500",
                    "status": "Active",
                },
                {
                    "id": "job-4",
                    "title": "Customer Support Rep",
                    "employmentType": "Remote - Part time",
                    "department": "Customer Service",
                    "location": "Remote",
                    "postedOn": "Jun 3, 2024",
                    "platforms": ["Li"],
                    "applicants": 58,
                    "applicantBarClassName": "bg-emerald-500",
                    "status": "Active",
                },
                {
                    "id": "job-5",
                    "title": "Marketing Manager",
                    "employmentType": "Hybrid - Full time",
                    "department": "Marketing",
                    "location": "Hybrid - Chicago",
                    "postedOn": "May 15, 2024",
                    "platforms": ["Li", "In"],
                    "applicants": 14,
                    "applicantBarClassName": "bg-blue-500",
                    "status": "Draft",
                },
                {
                    "id": "job-6",
                    "title": "Sales Development Rep",
                    "employmentType": "On-site - Full time",
                    "department": "Sales",
                    "location": "On-site - Austin",
                    "postedOn": "Apr 30, 2024",
                    "platforms": ["Li"],
                    "applicants": 39,
                    "applicantBarClassName": "bg-blue-500",
                    "status": "Active",
                },
                {
                    "id": "job-7",
                    "title": "Executive Assistant",
                    "employmentType": "On-site - Full time",
                    "department": "Executive",
                    "location": "On-site - NYC",
                    "postedOn": "Apr 27, 2024",
                    "platforms": ["Li", "In"],
                    "applicants": 26,
                    "applicantBarClassName": "bg-blue-500",
                    "status": "Draft",
                },
                {
                    "id": "job-8",
                    "title": "Data Analyst",
                    "employmentType": "Remote - Full time",
                    "department": "Engineering",
                    "location": "Remote",
                    "postedOn": "Mar 18, 2024",
                    "platforms": ["In"],
                    "applicants": 0,
                    "applicantBarClassName": "bg-slate-300",
                    "status": "Closed",
                },
            ],
            "talent_candidates": [
                {
                    "id": "candidate-1",
                    "name": "Elena Rodriguez",
                    "role": "Lead Product Designer",
                    "company": "FinTech Corp",
                    "meta": "6 yrs exp  •  Figma  •  Design Systems",
                    "tags": ["Figma", "UX Strategy"],
                    "match": "91% Match",
                    "matchClassName": "bg-emerald-50 text-emerald-700 border-emerald-200",
                },
                {
                    "id": "candidate-2",
                    "name": "Marcus Chen",
                    "role": "Senior UX Designer",
                    "company": "CreativeHub",
                    "meta": "5 yrs exp  •  UX  •  Startup Prototyping",
                    "tags": ["Product", "Strategy"],
                    "match": "92% Match",
                    "matchClassName": "bg-emerald-50 text-emerald-700 border-emerald-200",
                },
                {
                    "id": "candidate-3",
                    "name": "Sarah Jenkins",
                    "role": "Product Designer",
                    "company": "StartupX",
                    "meta": "4 yrs exp  •  Figma  •  UI Design",
                    "tags": ["Research", "UI"],
                    "match": "85% Match",
                    "matchClassName": "bg-amber-50 text-amber-700 border-amber-200",
                },
            ],
            "interview_questions": [
                {
                    "id": "question-1",
                    "category": "AI Suggested",
                    "prompt": "Walk me through your background and what excites you most about the Senior Product Designer role here.",
                    "meta": "2 follow-ups  •  12 sec  •  Warm-up",
                    "enabled": True,
                    "aiSuggested": True,
                },
                {
                    "id": "question-2",
                    "category": "Core Skill",
                    "prompt": "Tell me about a specific design system project you led, the scope, challenges you faced, and how you measured success.",
                    "meta": "1 follow-up  •  18 sec  •  Systems",
                    "enabled": True,
                },
                {
                    "id": "question-3",
                    "category": "Behavioral",
                    "prompt": "Describe a time when engineering constraints pushed back on a design decision you believed was critical for user experience. How did you handle it?",
                    "meta": "3 follow-ups  •  24 sec  •  Tradeoffs",
                    "enabled": True,
                },
                {
                    "id": "question-4",
                    "category": "AI Suggested",
                    "prompt": "How do you approach mentoring junior designers? Give a specific example of coaching you helped drive significant growth.",
                    "meta": "2 follow-ups  •  16 sec  •  Leadership",
                    "enabled": True,
                    "aiSuggested": True,
                },
                {
                    "id": "question-5",
                    "category": "Removed",
                    "prompt": "Walk me through your most recent end-to-end mobile redesign and how you validated the final experience before launch.",
                    "meta": "Archived  •  Too long for first round",
                    "enabled": False,
                    "archived": True,
                },
                {
                    "id": "question-6",
                    "category": "Culture",
                    "prompt": "What does your ideal design team culture look like, and how do you actively contribute to building it?",
                    "meta": "4 follow-ups  •  20 sec  •  Values",
                    "enabled": True,
                },
            ],
        },
        "candidates": {
            "list": [
                {
                    "id": "elena",
                    "name": "Elena Rodriguez",
                    "role": "Lead Product Designer",
                    "company": "FinTech Corp",
                    "location": "SF",
                    "aiScore": 96,
                    "aiLabel": "Exceptional",
                    "aiTone": "text-emerald-600 border-emerald-300",
                    "summary": "Strong match for leadership criteria. Extensive experience in building design systems from scratch. Passion for dee...",
                    "status": "Shortlisted",
                    "statusClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                },
                {
                    "id": "marcus",
                    "name": "Marcus Chen",
                    "role": "Senior UX Designer",
                    "company": "CreativeHub",
                    "location": "NY",
                    "aiScore": 91,
                    "aiLabel": "Strong",
                    "aiTone": "text-emerald-600 border-emerald-300",
                    "summary": "Solid background in B2B SaaS platforms. Excellent prototyping skills and user research methodology. Lacks direct lea...",
                    "status": "New",
                    "statusClassName": "border-blue-200 bg-blue-50 text-blue-700",
                },
                {
                    "id": "sarah",
                    "name": "Sarah Jenkins",
                    "role": "Product Designer",
                    "company": "StartupX",
                    "location": "Remote",
                    "aiScore": 85,
                    "aiLabel": "Match",
                    "aiTone": "text-amber-600 border-amber-300",
                    "summary": "Meets basic requirements for UI design and Figma proficiency. However, falls short on the required 5+ years of...",
                    "status": "New",
                    "statusClassName": "border-blue-200 bg-blue-50 text-blue-700",
                },
                {
                    "id": "david",
                    "name": "David Kim",
                    "role": "Frontend Developer",
                    "company": "TechSolutions",
                    "location": "Seattle",
                    "aiScore": 32,
                    "aiLabel": "Low Match",
                    "aiTone": "text-rose-600 border-rose-300",
                    "summary": "Applicant's background is primarily in frontend engineering. No design portfolio included. Fails most product desig...",
                    "status": "Rejected",
                    "statusClassName": "border-slate-200 bg-slate-100 text-slate-600",
                },
            ]
        },
        "interviews": {
            "rows": [
                {
                    "name": "Elena Rodriguez",
                    "role": "Senior Product Designer",
                    "score": 96,
                    "status": "Interview Done",
                    "statusClassName": "border-blue-200 bg-blue-50 text-blue-700",
                    "date": "Oct 24, 2024",
                    "recommendation": "Strong Hire",
                    "recClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                },
                {
                    "name": "Marcus Chen",
                    "role": "Frontend Engineer",
                    "score": 91,
                    "status": "Interview Done",
                    "statusClassName": "border-blue-200 bg-blue-50 text-blue-700",
                    "date": "Oct 23, 2024",
                    "recommendation": "Borderline",
                    "recClassName": "border-amber-200 bg-amber-50 text-amber-700",
                },
                {
                    "name": "Priya Sharma",
                    "role": "UX Researcher",
                    "score": 88,
                    "status": "Shortlisted",
                    "statusClassName": "border-violet-200 bg-violet-50 text-violet-700",
                    "date": "Oct 22, 2024",
                    "recommendation": "Strong Hire",
                    "recClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                },
                {
                    "name": "James Okonkwo",
                    "role": "Data Analyst",
                    "score": 42,
                    "status": "Drafting",
                    "statusClassName": "border-slate-200 bg-slate-100 text-slate-600",
                    "date": "Oct 21, 2024",
                    "recommendation": "No Hire",
                    "recClassName": "border-rose-200 bg-rose-50 text-rose-700",
                },
                {
                    "name": "Sofia Kimani",
                    "role": "HR Business Partner",
                    "score": 79,
                    "status": "Interview Done",
                    "statusClassName": "border-blue-200 bg-blue-50 text-blue-700",
                    "date": "Oct 20, 2024",
                    "recommendation": "Hire",
                    "recClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                },
                {
                    "name": "Daniel Park",
                    "role": "Backend Engineer",
                    "score": 71,
                    "status": "Pending",
                    "statusClassName": "border-slate-200 bg-slate-100 text-slate-600",
                    "date": "Oct 19, 2024",
                    "recommendation": "Borderline",
                    "recClassName": "border-amber-200 bg-amber-50 text-amber-700",
                },
            ]
        },
        "onboarding": {
            "documents": [
                {
                    "name": "Employee Code of Conduct 2024",
                    "category": "Policy",
                    "tags": ["Workplace", "Culture"],
                    "status": "Reviewed",
                    "statusClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                    "date": "Jun 15, 2024",
                    "owner": "Sarah M.",
                    "size": "5.2 MB",
                },
                {
                    "name": "New Hire Onboarding Checklist",
                    "category": "Onboarding",
                    "tags": ["Checklist", "Tasks"],
                    "status": "Published",
                    "statusClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                    "date": "Jun 3, 2024",
                    "owner": "James J.",
                    "size": "2.4 MB",
                },
                {
                    "name": "Health & Benefits Overview",
                    "category": "Benefits",
                    "tags": ["Benefits", "Guide"],
                    "status": "Reviewed",
                    "statusClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                    "date": "May 29, 2024",
                    "owner": "Sarah M.",
                    "size": "1.8 MB",
                },
                {
                    "name": "Workplace Safety Guidelines",
                    "category": "Compliance",
                    "tags": ["Safety", "Mandatory"],
                    "status": "In Review",
                    "statusClassName": "border-amber-200 bg-amber-50 text-amber-700",
                    "date": "May 20, 2024",
                    "owner": "Mike L.",
                    "size": "3.7 MB",
                },
                {
                    "name": "Anti-Harassment Policy",
                    "category": "Policy",
                    "tags": ["Policy", "HR"],
                    "status": "Reviewed",
                    "statusClassName": "border-emerald-200 bg-emerald-50 text-emerald-700",
                    "date": "May 13, 2024",
                    "owner": "Sarah M.",
                    "size": "1.9 MB",
                },
            ],
            "quick_prompts": [
                "What is the vacation policy?",
                "How do I set up my benefits?",
                "Summarize section 5",
            ],
        },
    }


def _get_greenhouse_connection(business_id: str) -> dict | None:
    result = (
        supabase_admin.table("greenhouse_connections")
        .select(
            "id,business_id,board_token,board_url,board_name,is_connected,"
            "last_sync_at,last_sync_status,last_sync_error,last_job_count"
        )
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _status_label(status: str) -> str:
    return {
        "draft": "Draft",
        "active": "Active",
        "closed": "Closed",
    }.get(status, "Draft")


def _native_job_to_response(row: dict) -> dict:
    status = _status_label(row.get("status") or "draft")
    sync_state = row.get("sync_state") or "native_only"
    return {
        "id": row["id"],
        "source": "native",
        "status": status,
        "sync_state": sync_state,
        "title": row.get("title") or "",
        "department": row.get("department") or "",
        "location": row.get("location") or "",
        "location_type": row.get("location_type") or "",
        "employment_type": row.get("employment_type") or "",
        "job_type": row.get("job_type") or "",
        "shift": row.get("shift") or "",
        "schedule": row.get("schedule") or "",
        "summary": row.get("summary") or "",
        "perks": row.get("perks") or "",
        "responsibilities": row.get("responsibilities") or "",
        "qualifications": row.get("qualifications") or "",
        "requirements_skills": row.get("requirements_skills") or "",
        "comments": row.get("comments") or "",
        "pay_min": row.get("pay_min") or "",
        "pay_max": row.get("pay_max") or "",
        "pay_period": row.get("pay_period") or "",
        "benefits": row.get("benefits") or "",
        "required_experience": row.get("required_experience") or "",
        "seniority": row.get("seniority") or "",
        "posted_on": row.get("posted_at") or row.get("updated_at") or row.get("created_at") or "",
        "absolute_url": "",
        "language": row.get("language") or "en",
        "content_html": row.get("content_html") or "",
        "platforms": ["Native"],
        "applicants": 0,
        "applicant_bar_class_name": "bg-blue-500" if status == "Active" else "bg-slate-300",
        "publish_in_linkedin": bool(row.get("publish_in_linkedin")),
        "publish_in_indeed": bool(row.get("publish_in_indeed")),
        "greenhouse_managed_distribution": bool(row.get("greenhouse_managed_distribution")),
        "linkedin_status": "Pending" if row.get("publish_in_linkedin") else "Off",
        "indeed_status": "Pending" if row.get("publish_in_indeed") else "Off",
        "ai_status": "Drafting" if status == "Draft" else "Ready",
        "greenhouse_job_id": row.get("greenhouse_job_id"),
        "greenhouse_internal_job_id": row.get("greenhouse_internal_job_id"),
        "greenhouse_board_token_snapshot": row.get("greenhouse_board_token_snapshot"),
        "metadata": None,
        "source_payload": row.get("source_payload") or {},
    }


def _workspace_view_from_jobs(jobs: list[dict], *, greenhouse_connected: bool) -> HrWorkspaceJobPayload:
    active_count = sum(1 for job in jobs if job["status"] == "Active")
    draft_count = sum(1 for job in jobs if job["status"] == "Draft")
    closed_count = sum(1 for job in jobs if job["status"] == "Closed")

    dashboard_postings = [
        HrDashboardPostingResponse(
            role=job["title"],
            team=job["department"] or "Unassigned",
            applicants=job.get("applicants", 0),
            linkedin=job["linkedin_status"] if greenhouse_connected and job["source"] == "greenhouse" else ("Active" if job.get("publish_in_linkedin") else "Off"),
            indeed=job["indeed_status"] if greenhouse_connected and job["source"] == "greenhouse" else ("Active" if job.get("publish_in_indeed") else "Off"),
            aiStatus=job.get("ai_status") or "Ready",
        ).model_dump()
        for job in jobs
        if job["status"] == "Active"
    ][:5]

    stat_cards = [
        {"label": "Total Postings", "value": str(len(jobs)), "iconClassName": "bg-blue-50 text-blue-600"},
        {"label": "Active", "value": str(active_count), "iconClassName": "bg-emerald-50 text-emerald-600"},
        {"label": "Draft", "value": str(draft_count), "iconClassName": "bg-amber-50 text-amber-600"},
        {"label": "Closed", "value": str(closed_count), "iconClassName": "bg-slate-100 text-slate-500"},
    ]

    postings = [
        {
            "id": job["id"],
            "title": job["title"],
            "employmentType": job["employment_type"] or "Not specified",
            "department": job["department"] or "Unassigned",
            "location": job["location"] or "Remote",
            "postedOn": (job["posted_on"] or "")[:10] if job["posted_on"] else "",
            "platforms": job.get("platforms") or [],
            "applicants": job.get("applicants", 0),
            "applicantBarClassName": job.get("applicant_bar_class_name", "bg-blue-500"),
            "status": job["status"],
            "source": job["source"],
            "syncState": job["sync_state"],
        }
        for job in jobs
    ]

    return HrWorkspaceJobPayload(
        dashboard={"active_job_postings": dashboard_postings},
        job_postings={"stat_cards": stat_cards, "postings": postings},
    )


async def _load_greenhouse_jobs(connection: dict) -> list[dict]:
    payload = await fetch_jobs(connection["board_token"], content=True)
    return [
        normalize_greenhouse_job(job, board_token=connection["board_token"])
        for job in payload.get("jobs", [])
    ]


def _load_native_jobs(business_id: str) -> list[dict]:
    rows = (
        supabase_admin.table("hr_job_postings")
        .select("*")
        .eq("business_id", business_id)
        .eq("source", "native")
        .order("updated_at", desc=True)
        .execute()
    )
    return [_native_job_to_response(row) for row in (rows.data or [])]


async def _get_hr_jobs_payload(business_id: str) -> HrJobsResponse:
    connection = _get_greenhouse_connection(business_id)
    native_jobs = _load_native_jobs(business_id)
    native_draft_count = sum(1 for job in native_jobs if job["status"] == "Draft")

    if not connection or not connection.get("is_connected"):
        return HrJobsResponse(
            source_of_truth="native",
            greenhouse_connected=False,
            jobs=[HrJobPostingResponse.model_validate(job) for job in native_jobs],
            native_draft_count=native_draft_count,
        )

    try:
        greenhouse_jobs = await _load_greenhouse_jobs(connection)
        combined_jobs = greenhouse_jobs + [job for job in native_jobs if job["status"] == "Draft"]
        greenhouse_status = {
            "connected": True,
            "board_url": connection.get("board_url"),
            "board_name": connection.get("board_name"),
            "last_sync_at": connection.get("last_sync_at"),
            "last_sync_status": connection.get("last_sync_status"),
            "last_sync_error": connection.get("last_sync_error"),
            "last_job_count": connection.get("last_job_count") or len(greenhouse_jobs),
        }
    except GreenhouseError as exc:
        combined_jobs = [job for job in native_jobs if job["status"] == "Draft"]
        greenhouse_status = {
            "connected": True,
            "board_url": connection.get("board_url"),
            "board_name": connection.get("board_name"),
            "last_sync_at": connection.get("last_sync_at"),
            "last_sync_status": "error",
            "last_sync_error": str(exc),
            "last_job_count": connection.get("last_job_count") or 0,
        }

    return HrJobsResponse(
        source_of_truth="greenhouse",
        greenhouse_connected=True,
        greenhouse_status=greenhouse_status,
        jobs=[HrJobPostingResponse.model_validate(job) for job in combined_jobs],
        native_draft_count=native_draft_count,
    )


@router.get("/jobs")
async def list_hr_jobs(
    business_id: str,
    _: str = Depends(require_business_access()),
) -> HrJobsResponse:
    return await _get_hr_jobs_payload(business_id)


@router.get("/jobs/workspace")
async def get_hr_jobs_workspace(
    business_id: str,
    _: str = Depends(require_business_access()),
):
    payload = await _get_hr_jobs_payload(business_id)
    jobs = [job.model_dump() for job in payload.jobs]
    workspace_jobs = _workspace_view_from_jobs(jobs, greenhouse_connected=payload.greenhouse_connected)
    return {
        "source_of_truth": payload.source_of_truth,
        "greenhouse_connected": payload.greenhouse_connected,
        "greenhouse_status": payload.greenhouse_status.model_dump() if payload.greenhouse_status else None,
        "native_draft_count": payload.native_draft_count,
        **workspace_jobs.model_dump(),
    }


@router.post("/jobs/ai-assist")
async def assist_hr_job_draft(
    body: HrDraftAssistRequest,
    user_id: str = Depends(get_user_id),
) -> HrDraftAssistResponse:
    verify_business_access(user_id, body.business_id)
    if body.mode == "field_action" and not body.target_field:
        raise HTTPException(status_code=400, detail="target_field is required for field actions.")
    if body.mode == "field_action" and not body.action:
        raise HTTPException(status_code=400, detail="action is required for field actions.")

    try:
        result = await generate_hr_draft_assistance(body)
    except Exception as exc:
        logger.error("Ava drafting failed for business %s: %s", body.business_id, exc)
        raise HTTPException(status_code=502, detail="Ava could not generate draft content right now.") from exc
    return HrDraftAssistResponse(**result)


@router.post("/onboarding/chat", response_model=OnboardingChatResponse)
async def chat_with_hr_onboarding_agent(
    body: OnboardingChatRequest,
    user_id: str = Depends(get_user_id),
) -> OnboardingChatResponse:
    verify_business_access(user_id, body.business_id)
    try:
        return await answer_onboarding_question(
            business_id=body.business_id,
            question=body.question.strip(),
            document_id=body.document_id,
        )
    except Exception as exc:
        logger.error("HR onboarding chat failed for business %s: %s", body.business_id, exc)
        raise HTTPException(status_code=502, detail="The HR onboarding assistant is unavailable right now.") from exc


@router.post("/onboarding/session", response_model=HrOnboardingVoiceSessionResponse)
async def create_hr_onboarding_voice_session(
    body: HrOnboardingVoiceSessionRequest,
    user_id: str = Depends(get_user_id),
) -> HrOnboardingVoiceSessionResponse:
    verify_business_access(user_id, body.business_id)

    business = (
        supabase_admin.table("businesses")
        .select("id")
        .eq("id", body.business_id)
        .limit(1)
        .execute()
    )
    if not business.data:
        raise HTTPException(status_code=404, detail="Business not found.")

    room_name = f"hr-onboarding-{body.business_id[:8]}-{uuid.uuid4().hex[:8]}"
    await livekit_service.create_room(room_name)

    token = livekit_service.generate_user_token(
        room_name,
        f"hr-user-{user_id[:12]}",
        metadata={
            "session_type": "hr_onboarding",
            "business_id": body.business_id,
            "user_id": user_id,
        },
    )

    await livekit_service.create_hr_onboarding_agent_dispatch(
        room_name,
        metadata={
            "session_type": "hr_onboarding",
            "business_id": body.business_id,
            "user_id": user_id,
            "avatar_enabled": body.avatar_enabled,
        },
    )

    logger.info(
        "HR onboarding voice session created: room=%s business=%s avatar_enabled=%s",
        room_name,
        body.business_id,
        body.avatar_enabled,
    )

    avatar_available = bool(os.environ.get("JOHN_AVATAR_ID", "Albert_public_1"))

    return HrOnboardingVoiceSessionResponse(
        room_name=room_name,
        token=token,
        livekit_url=settings.livekit_url,
        avatar_available=avatar_available,
    )


@router.get("/jobs/{job_id}")
async def get_hr_job(
    job_id: str,
    business_id: str,
    _: str = Depends(require_business_access()),
) -> HrJobPostingResponse:
    payload = await _get_hr_jobs_payload(business_id)
    for job in payload.jobs:
        if job.id == job_id:
            return job
    raise HTTPException(status_code=404, detail="HR job posting not found.")


@router.post("/jobs")
async def create_hr_job(
    body: HrJobPostingUpsertRequest,
    user_id: str = Depends(get_user_id),
) -> HrJobPostingResponse:
    verify_business_access(user_id, body.business_id)
    connection = _get_greenhouse_connection(body.business_id)
    is_greenhouse_connected = bool(connection and connection.get("is_connected"))

    status = body.status
    sync_state = "native_only"
    if is_greenhouse_connected:
        status = "draft"
        sync_state = "pending_greenhouse_sync"

    row = {
        "business_id": body.business_id,
        "source": "native",
        "status": status,
        "sync_state": sync_state,
        "title": body.title,
        "department": body.department,
        "location": body.location,
        "location_type": body.location_type,
        "employment_type": body.employment_type,
        "job_type": body.job_type,
        "shift": body.shift,
        "schedule": body.schedule,
        "summary": body.summary,
        "perks": body.perks,
        "responsibilities": body.responsibilities,
        "qualifications": body.qualifications,
        "requirements_skills": body.requirements_skills,
        "comments": body.comments,
        "pay_min": body.pay_min,
        "pay_max": body.pay_max,
        "pay_period": body.pay_period,
        "benefits": body.benefits,
        "required_experience": body.required_experience,
        "seniority": body.seniority,
        "publish_in_linkedin": body.publish_in_linkedin,
        "publish_in_indeed": body.publish_in_indeed,
        "greenhouse_managed_distribution": False,
        "posted_at": datetime.now(timezone.utc).isoformat() if status == "active" else None,
    }
    created = (
        supabase_admin.table("hr_job_postings")
        .insert(row)
        .select("*")
        .execute()
    )
    created_row = created.data[0] if created.data else None
    if not created_row:
        raise HTTPException(status_code=500, detail="Failed to create HR job posting.")
    return HrJobPostingResponse.model_validate(_native_job_to_response(created_row))


@router.put("/jobs/{job_id}")
async def update_hr_job(
    job_id: str,
    body: HrJobPostingUpsertRequest,
    user_id: str = Depends(get_user_id),
) -> HrJobPostingResponse:
    verify_business_access(user_id, body.business_id)
    existing = (
        supabase_admin.table("hr_job_postings")
        .select("*")
        .eq("id", job_id)
        .eq("business_id", body.business_id)
        .eq("source", "native")
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Native HR job posting not found.")

    connection = _get_greenhouse_connection(body.business_id)
    is_greenhouse_connected = bool(connection and connection.get("is_connected"))

    status = body.status
    sync_state = existing.data[0].get("sync_state") or "native_only"
    if is_greenhouse_connected:
        status = "draft"
        sync_state = "pending_greenhouse_sync"
    elif status == "active":
        sync_state = "native_only"

    updates = {
        "status": status,
        "sync_state": sync_state,
        "title": body.title,
        "department": body.department,
        "location": body.location,
        "location_type": body.location_type,
        "employment_type": body.employment_type,
        "job_type": body.job_type,
        "shift": body.shift,
        "schedule": body.schedule,
        "summary": body.summary,
        "perks": body.perks,
        "responsibilities": body.responsibilities,
        "qualifications": body.qualifications,
        "requirements_skills": body.requirements_skills,
        "comments": body.comments,
        "pay_min": body.pay_min,
        "pay_max": body.pay_max,
        "pay_period": body.pay_period,
        "benefits": body.benefits,
        "required_experience": body.required_experience,
        "seniority": body.seniority,
        "publish_in_linkedin": body.publish_in_linkedin,
        "publish_in_indeed": body.publish_in_indeed,
        "posted_at": datetime.now(timezone.utc).isoformat() if status == "active" else existing.data[0].get("posted_at"),
    }
    updated = (
        supabase_admin.table("hr_job_postings")
        .update(updates)
        .eq("id", job_id)
        .eq("business_id", body.business_id)
        .eq("source", "native")
        .select("*")
        .execute()
    )
    updated_row = updated.data[0] if updated.data else None
    if not updated_row:
        raise HTTPException(status_code=500, detail="Failed to update HR job posting.")
    return HrJobPostingResponse.model_validate(_native_job_to_response(updated_row))


@router.delete("/jobs/{job_id}")
async def delete_hr_job(
    job_id: str,
    business_id: str,
    _: str = Depends(require_business_access()),
):
    existing = (
        supabase_admin.table("hr_job_postings")
        .select("id,status,source")
        .eq("id", job_id)
        .eq("business_id", business_id)
        .eq("source", "native")
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Native HR job posting not found.")

    row = existing.data[0]
    if row.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Only native draft job postings can be deleted.")

    (
        supabase_admin.table("hr_job_postings")
        .delete()
        .eq("id", job_id)
        .eq("business_id", business_id)
        .eq("source", "native")
        .execute()
    )
    return {"deleted": True, "id": job_id}
