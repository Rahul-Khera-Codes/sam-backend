from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import uuid
import os

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import get_user_id, require_business_access, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.documents import OnboardingChatRequest, OnboardingChatResponse
from app.schemas.hr import (
    HrCandidateFileUrlResponse,
    HrCandidateLookupResponse,
    HrCandidatePromoteRequest,
    HrCandidateResponse,
    HrCandidatesResponse,
    HrCandidateStageUpdateRequest,
    HrDashboardPostingResponse,
    HrDashboardStatCard,
    HrDraftAssistRequest,
    HrDraftAssistResponse,
    HrFunnelStage,
    HrJobPostingResponse,
    HrJobsResponse,
    HrJobPostingUpsertRequest,
)
from app.services.hr_drafting_service import generate_hr_draft_assistance
from app.services.hr_onboarding_chat_service import answer_onboarding_question, stream_onboarding_question
from app.services.hr_onboarding_conversation_memory_service import (
    delete_all_conversations as delete_all_hr_onboarding_conversations,
    delete_conversation as delete_hr_onboarding_conversation,
)
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
                    "aiStatus": "Screening",
                },
                {
                    "role": "Product Designer",
                    "team": "Design",
                    "applicants": 89,
                    "linkedin": "Active",
                    "aiStatus": "Waiting Review",
                },
                {
                    "role": "Marketing Manager",
                    "team": "Marketing",
                    "applicants": 215,
                    "linkedin": "Active",
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


def _status_label(status: str) -> str:
    return {
        "draft": "Draft",
        "active": "Active",
        "closed": "Closed",
    }.get(status, "Draft")


def _native_job_to_response(row: dict, applicants: int = 0) -> dict:
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
        "applicants": applicants,
        "applicant_bar_class_name": "bg-blue-500" if status == "Active" else "bg-slate-300",
        "publish_in_linkedin": bool(row.get("publish_in_linkedin")),
        "linkedin_status": "Pending" if row.get("publish_in_linkedin") else "Off",
        "ai_status": "Drafting" if status == "Draft" else "Ready",
        "metadata": None,
        "source_payload": row.get("source_payload") or {},
    }


def _workspace_view_from_jobs(jobs: list[dict]) -> HrWorkspaceJobPayload:
    active_count = sum(1 for job in jobs if job["status"] == "Active")
    draft_count = sum(1 for job in jobs if job["status"] == "Draft")
    closed_count = sum(1 for job in jobs if job["status"] == "Closed")

    dashboard_postings = [
        HrDashboardPostingResponse(
            role=job["title"],
            team=job["department"] or "Unassigned",
            applicants=job.get("applicants", 0),
            linkedin="Active" if job.get("publish_in_linkedin") else "Off",
            aiStatus=job.get("ai_status") or "Ready",
            status=job["status"],
            source=job["source"],
        ).model_dump()
        for job in jobs
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


def _load_native_jobs(business_id: str, applicants_by_job: dict[str, int]) -> list[dict]:
    rows = (
        supabase_admin.table("hr_job_postings")
        .select("*")
        .eq("business_id", business_id)
        .eq("source", "native")
        .order("updated_at", desc=True)
        .execute()
    )
    return [
        _native_job_to_response(row, applicants_by_job.get(row["id"], 0))
        for row in (rows.data or [])
    ]


def _fetch_hr_applications(business_id: str) -> list[dict]:
    rows = (
        supabase_admin.table("hr_job_applications")
        .select("job_posting_id,status,submitted_at")
        .eq("business_id", business_id)
        .execute()
    )
    return rows.data or []


def _fetch_hr_interview_sessions(business_id: str) -> list[dict]:
    rows = (
        supabase_admin.table("hr_interview_sessions")
        .select("status,interview_kind,invited_at")
        .eq("business_id", business_id)
        .execute()
    )
    return rows.data or []


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct_change_label(current: int, previous: int) -> str:
    if previous == 0:
        return "+0%" if current == 0 else "+100%"
    pct = round(((current - previous) / previous) * 100)
    return f"{'+' if pct >= 0 else ''}{pct}%"


def _windowed_change(rows: list[dict], ts_key: str, predicate, now: datetime) -> str:
    window = timedelta(days=7)
    current_start = now - window
    prev_start = current_start - window
    current = 0
    previous = 0
    for row in rows:
        if predicate is not None and not predicate(row):
            continue
        ts = _parse_ts(row.get(ts_key))
        if ts is None:
            continue
        if ts >= current_start:
            current += 1
        elif ts >= prev_start:
            previous += 1
    return _pct_change_label(current, previous)


def _build_dashboard_stats(applications: list[dict], interview_sessions: list[dict]) -> dict:
    now = datetime.now(timezone.utc)

    total_applicants = len(applications)
    pending_review = sum(1 for a in applications if a.get("status") == "new")
    hired = sum(1 for a in applications if a.get("status") == "hired")

    active_interview_statuses = {"invited", "opened", "in_progress"}
    active_interviews = sum(
        1 for s in interview_sessions if s.get("status") in active_interview_statuses
    )
    ai_screened = sum(
        1
        for s in interview_sessions
        if s.get("interview_kind") == "ai_screen" and s.get("status") != "draft"
    )
    interviewed = sum(
        1 for s in interview_sessions if s.get("status") in {"completed", "reviewed"}
    )

    stats = [
        HrDashboardStatCard(
            title="Total Applicants",
            value=str(total_applicants),
            change=_windowed_change(applications, "submitted_at", None, now),
            icon="users",
        ).model_dump(),
        HrDashboardStatCard(
            title="Pending Review",
            value=str(pending_review),
            change=_windowed_change(
                applications, "submitted_at", lambda a: a.get("status") == "new", now
            ),
            icon="briefcase",
        ).model_dump(),
        HrDashboardStatCard(
            title="Active Interviews",
            value=str(active_interviews),
            change=_windowed_change(
                interview_sessions,
                "invited_at",
                lambda s: s.get("status") in active_interview_statuses,
                now,
            ),
            icon="calendar",
        ).model_dump(),
    ]

    funnel_stages = [
        HrFunnelStage(label="Applicants", value=total_applicants).model_dump(),
        HrFunnelStage(label="AI Screened", value=ai_screened).model_dump(),
        HrFunnelStage(label="Interviewed", value=interviewed).model_dump(),
        HrFunnelStage(label="Hired", value=hired).model_dump(),
    ]

    return {"stats": stats, "funnel_stages": funnel_stages}


async def _get_hr_jobs_payload(
    business_id: str, applications: list[dict] | None = None
) -> HrJobsResponse:
    if applications is None:
        applications = _fetch_hr_applications(business_id)
    applicants_by_job = Counter(
        row["job_posting_id"] for row in applications if row.get("job_posting_id")
    )
    native_jobs = _load_native_jobs(business_id, applicants_by_job)
    native_draft_count = sum(1 for job in native_jobs if job["status"] == "Draft")
    return HrJobsResponse(
        jobs=[HrJobPostingResponse.model_validate(job) for job in native_jobs],
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
    applications = _fetch_hr_applications(business_id)
    interview_sessions = _fetch_hr_interview_sessions(business_id)

    payload = await _get_hr_jobs_payload(business_id, applications=applications)
    jobs = [job.model_dump() for job in payload.jobs]
    workspace = _workspace_view_from_jobs(jobs).model_dump()

    dashboard_stats = _build_dashboard_stats(applications, interview_sessions)
    workspace["dashboard"]["stats"] = dashboard_stats["stats"]
    workspace["dashboard"]["funnel_stages"] = dashboard_stats["funnel_stages"]

    return {
        "native_draft_count": payload.native_draft_count,
        **workspace,
    }


def _completed_interview_keys(business_id: str) -> tuple[set[str], set[str]]:
    """Application IDs and candidate emails with at least one completed interview.

    Interview sessions are only reliably linked to a candidate application via
    application_id when the invite came from a candidate row; ad hoc invites
    (freeform name/email on the Interviews page) only carry candidate_email, so
    both keys are checked when deciding Final Round eligibility.
    """
    rows = (
        supabase_admin.table("hr_interview_sessions")
        .select("application_id,candidate_email,status")
        .eq("business_id", business_id)
        .in_("status", ["completed", "reviewed"])
        .execute()
    ).data or []
    application_ids = {row["application_id"] for row in rows if row.get("application_id")}
    emails = {row["candidate_email"].strip().lower() for row in rows if row.get("candidate_email")}
    return application_ids, emails


def _is_eligible_for_final_round(
    row: dict,
    completed_application_ids: set[str],
    completed_emails: set[str],
) -> bool:
    if row["id"] in completed_application_ids:
        return True
    email = (row.get("candidate_email") or "").strip().lower()
    return bool(email) and email in completed_emails


_INTERVIEW_STATUS_RANK = {"in_progress": 1, "completed": 2, "reviewed": 3}


def _fetch_interview_activity(business_id: str) -> list[dict]:
    """All in-progress/completed/reviewed interview sessions for a business, each merged with its outcome (if any)."""
    sessions = (
        supabase_admin.table("hr_interview_sessions")
        .select(
            "id,application_id,candidate_id,candidate_email,candidate_name,candidate_phone,"
            "job_posting_id,interview_kind,status,started_at,completed_at,"
            "human_interview_provider,recruiter_score"
        )
        .eq("business_id", business_id)
        .in_("status", list(_INTERVIEW_STATUS_RANK.keys()))
        .execute()
    ).data or []
    if not sessions:
        return []

    session_ids = [s["id"] for s in sessions if s.get("id")]
    outcomes_by_session: dict[str, dict] = {}
    if session_ids:
        outcome_rows = (
            supabase_admin.table("hr_interview_outcomes")
            .select("session_id,total_score,recommendation,criterion_scores,strengths")
            .in_("session_id", session_ids)
            .execute()
        ).data or []
        outcomes_by_session = {row["session_id"]: row for row in outcome_rows}

    return [{**session, "outcome": outcomes_by_session.get(session["id"])} for session in sessions]


def _interview_rank_key(session: dict) -> tuple:
    rank = _INTERVIEW_STATUS_RANK.get(session.get("status"), 0)
    timestamp = session.get("completed_at") or session.get("started_at") or ""
    return (rank, timestamp)


def _group_interview_activity_by_key(sessions: list[dict]) -> dict[str, dict]:
    """Most relevant session per candidate, keyed by both application_id and lowercased
    candidate_email, same dual-key pattern as _completed_interview_keys, since ad hoc
    interview invites only carry an email rather than a real application_id.
    """
    activity: dict[str, dict] = {}
    for session in sessions:
        keys = []
        if session.get("application_id"):
            keys.append(session["application_id"])
        email = (session.get("candidate_email") or "").strip().lower()
        if email:
            keys.append(email)
        for key in keys:
            existing = activity.get(key)
            if existing is None or _interview_rank_key(session) > _interview_rank_key(existing):
                activity[key] = session
    return activity


def _distinct_interviewed_candidates(sessions: list[dict]) -> list[dict]:
    """One session per unique candidate identity (application_id, else candidate_id, else email)."""
    best: dict[str, dict] = {}
    for session in sessions:
        email = (session.get("candidate_email") or "").strip().lower()
        identity = session.get("application_id") or session.get("candidate_id") or email or session["id"]
        existing = best.get(identity)
        if existing is None or _interview_rank_key(session) > _interview_rank_key(existing):
            best[identity] = session
    return list(best.values())


def _interview_activity_by_key(business_id: str) -> dict[str, dict]:
    return _group_interview_activity_by_key(_fetch_interview_activity(business_id))


def _interviewed_candidate_response(
    session: dict,
    applications_by_id: dict[str, dict],
    applications_by_email: dict[str, dict],
    jobs_by_id: dict[str, dict],
    completed_application_ids: set[str],
    completed_emails: set[str],
) -> HrCandidateResponse:
    application = None
    if session.get("application_id"):
        application = applications_by_id.get(session["application_id"])
    if application is None:
        email = (session.get("candidate_email") or "").strip().lower()
        if email:
            application = applications_by_email.get(email)

    outcome = session.get("outcome") or {}
    job_posting_id = (application or {}).get("job_posting_id") or session.get("job_posting_id")
    title = jobs_by_id.get(job_posting_id, {}).get("title", "") if job_posting_id else ""

    if application:
        candidate_id = application["id"]
        application_id = application["id"]
        name = application.get("candidate_name") or session.get("candidate_name") or ""
        location = application.get("candidate_location") or ""
        email = application.get("candidate_email") or session.get("candidate_email")
        phone = application.get("candidate_phone") or session.get("candidate_phone")
        status = application.get("status") or "new"
        stage = application.get("stage") or "applied"
        applied_at = application.get("submitted_at")
        final_round_at = application.get("final_round_at")
        eligible = _is_eligible_for_final_round(application, completed_application_ids, completed_emails)
        has_resume = bool(application.get("resume_storage_path"))
        has_cover_letter = bool(application.get("cover_letter_storage_path"))
    else:
        # No application on file for this candidate — they were interviewed via an ad hoc
        # invite (freeform name/email on the Interviews page), never went through the
        # careers-apply flow. Surface real session data anyway; final-round/resume actions
        # stay disabled since there's no application to move or file to show.
        candidate_id = session.get("candidate_id") or session["id"]
        application_id = ""
        name = session.get("candidate_name") or ""
        location = ""
        email = session.get("candidate_email")
        phone = session.get("candidate_phone")
        status = ""
        stage = ""
        applied_at = None
        final_round_at = None
        eligible = False
        has_resume = False
        has_cover_letter = False

    return HrCandidateResponse(
        id=candidate_id,
        application_id=application_id,
        candidate_id=candidate_id,
        name=name,
        title=title,
        location=location,
        email=email,
        phone=phone,
        status=status,
        stage=stage,
        applied_at=applied_at,
        source="native",
        prospect=application is None,
        eligible_for_final_round=eligible,
        final_round_at=final_round_at,
        interview_kind=session.get("interview_kind"),
        interview_status=session.get("status"),
        interview_started_at=session.get("started_at"),
        interview_completed_at=session.get("completed_at"),
        human_interview_provider=session.get("human_interview_provider"),
        ai_score=outcome.get("total_score"),
        recommendation=outcome.get("recommendation"),
        recruiter_score=session.get("recruiter_score"),
        criterion_scores=outcome.get("criterion_scores") or [],
        strengths=outcome.get("strengths") or [],
        has_resume=has_resume,
        has_cover_letter=has_cover_letter,
        interview_session_id=session.get("id"),
    )


def _list_interviewed_candidates(business_id: str) -> HrCandidatesResponse:
    sessions = _fetch_interview_activity(business_id)
    if not sessions:
        return HrCandidatesResponse(
            available=False,
            message="No candidates have started or completed an interview yet.",
        )
    distinct_sessions = _distinct_interviewed_candidates(sessions)

    application_ids = {s["application_id"] for s in distinct_sessions if s.get("application_id")}
    emails = {(s.get("candidate_email") or "").strip().lower() for s in distinct_sessions if s.get("candidate_email")}

    applications_by_id: dict[str, dict] = {}
    applications_by_email: dict[str, dict] = {}
    if application_ids or emails:
        app_rows = (
            supabase_admin.table("hr_job_applications")
            .select("*")
            .eq("business_id", business_id)
            .execute()
        ).data or []
        for row in app_rows:
            applications_by_id[row["id"]] = row
            email = (row.get("candidate_email") or "").strip().lower()
            if email:
                applications_by_email.setdefault(email, row)

    job_ids = {row["job_posting_id"] for row in applications_by_id.values() if row.get("job_posting_id")}
    job_ids |= {s["job_posting_id"] for s in distinct_sessions if s.get("job_posting_id")}
    jobs_by_id: dict[str, dict] = {}
    if job_ids:
        job_rows = (
            supabase_admin.table("hr_job_postings")
            .select("id,title")
            .in_("id", list(job_ids))
            .execute()
        ).data or []
        jobs_by_id = {job["id"]: job for job in job_rows}

    completed_application_ids, completed_emails = _completed_interview_keys(business_id)
    candidates = [
        _interviewed_candidate_response(
            session, applications_by_id, applications_by_email, jobs_by_id, completed_application_ids, completed_emails
        )
        for session in distinct_sessions
    ]
    candidates.sort(key=lambda c: c.interview_completed_at or c.interview_started_at or "", reverse=True)

    return HrCandidatesResponse(available=True, candidates=candidates, total=len(candidates))


def _candidate_response(
    row: dict,
    title: str,
    completed_application_ids: set[str],
    completed_emails: set[str],
    interview_activity: dict[str, dict] | None = None,
) -> HrCandidateResponse:
    activity_entry = None
    if interview_activity:
        activity_entry = interview_activity.get(row["id"])
        if activity_entry is None:
            email = (row.get("candidate_email") or "").strip().lower()
            if email:
                activity_entry = interview_activity.get(email)
    outcome = (activity_entry or {}).get("outcome") or {}

    return HrCandidateResponse(
        id=row["id"],
        application_id=row["id"],
        candidate_id=row["id"],
        name=row.get("candidate_name") or "",
        title=title,
        location=row.get("candidate_location") or "",
        email=row.get("candidate_email") or None,
        phone=row.get("candidate_phone") or None,
        status=row.get("status") or "new",
        stage=row.get("stage") or "applied",
        applied_at=row.get("submitted_at"),
        source="native",
        prospect=False,
        eligible_for_final_round=_is_eligible_for_final_round(row, completed_application_ids, completed_emails),
        final_round_at=row.get("final_round_at"),
        interview_kind=(activity_entry or {}).get("interview_kind"),
        interview_status=(activity_entry or {}).get("status"),
        interview_started_at=(activity_entry or {}).get("started_at"),
        interview_completed_at=(activity_entry or {}).get("completed_at"),
        human_interview_provider=(activity_entry or {}).get("human_interview_provider"),
        ai_score=outcome.get("total_score"),
        recommendation=outcome.get("recommendation"),
        recruiter_score=(activity_entry or {}).get("recruiter_score"),
        criterion_scores=outcome.get("criterion_scores") or [],
        strengths=outcome.get("strengths") or [],
        has_resume=bool(row.get("resume_storage_path")),
        has_cover_letter=bool(row.get("cover_letter_storage_path")),
        interview_session_id=(activity_entry or {}).get("id"),
    )


@router.get("/candidates")
async def list_hr_candidates(
    business_id: str,
    stage: str | None = None,
    interviewed: bool = False,
    _: str = Depends(require_business_access()),
) -> HrCandidatesResponse:
    if interviewed:
        return _list_interviewed_candidates(business_id)

    query = (
        supabase_admin.table("hr_job_applications")
        .select("*")
        .eq("business_id", business_id)
    )
    if stage:
        query = query.eq("stage", stage)
    applications = query.order("submitted_at", desc=True).execute().data or []

    if not applications:
        message = "No candidates in this stage yet." if stage else "No candidates have applied yet."
        return HrCandidatesResponse(available=False, message=message)

    interview_activity = _interview_activity_by_key(business_id)
    job_ids = {row["job_posting_id"] for row in applications}
    jobs_by_id: dict[str, dict] = {}
    if job_ids:
        job_rows = (
            supabase_admin.table("hr_job_postings")
            .select("id,title")
            .in_("id", list(job_ids))
            .execute()
        ).data or []
        jobs_by_id = {job["id"]: job for job in job_rows}

    completed_application_ids, completed_emails = _completed_interview_keys(business_id)
    candidates = [
        _candidate_response(
            row,
            jobs_by_id.get(row["job_posting_id"], {}).get("title", ""),
            completed_application_ids,
            completed_emails,
            interview_activity,
        )
        for row in applications
    ]

    return HrCandidatesResponse(
        available=True,
        candidates=candidates,
        total=len(candidates),
    )


@router.get("/candidates/lookup")
async def lookup_hr_candidate_by_email(
    business_id: str,
    email: str,
    _: str = Depends(require_business_access()),
) -> HrCandidateLookupResponse:
    normalized = email.strip().lower()
    if not normalized:
        return HrCandidateLookupResponse(found=False)

    rows = (
        supabase_admin.table("hr_job_applications")
        .select("*")
        .eq("business_id", business_id)
        .ilike("candidate_email", normalized)
        .order("submitted_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return HrCandidateLookupResponse(found=False)
    row = rows[0]

    job_rows = (
        supabase_admin.table("hr_job_postings")
        .select("id,title")
        .eq("id", row["job_posting_id"])
        .limit(1)
        .execute()
    ).data or []
    title = job_rows[0].get("title", "") if job_rows else ""

    completed_application_ids, completed_emails = _completed_interview_keys(business_id)
    interview_activity = _interview_activity_by_key(business_id)
    return HrCandidateLookupResponse(
        found=True,
        candidate=_candidate_response(row, title, completed_application_ids, completed_emails, interview_activity),
    )


@router.patch("/candidates/{application_id}/stage")
async def update_hr_candidate_stage(
    application_id: str,
    body: HrCandidateStageUpdateRequest,
    user_id: str = Depends(get_user_id),
) -> HrCandidateResponse:
    verify_business_access(user_id, body.business_id)

    existing = (
        supabase_admin.table("hr_job_applications")
        .select("*")
        .eq("business_id", body.business_id)
        .eq("id", application_id)
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status_code=404, detail="Candidate application not found.")
    application = existing[0]

    completed_application_ids, completed_emails = _completed_interview_keys(body.business_id)
    if body.stage == "final_round" and not _is_eligible_for_final_round(
        application, completed_application_ids, completed_emails
    ):
        raise HTTPException(
            status_code=422,
            detail="This candidate needs at least one completed interview before moving to Final Round.",
        )

    updates: dict = {"stage": body.stage}
    updates["final_round_at"] = datetime.now(timezone.utc).isoformat() if body.stage == "final_round" else None
    updated = (
        supabase_admin.table("hr_job_applications")
        .update(updates)
        .eq("business_id", body.business_id)
        .eq("id", application_id)
        .select("*")
        .execute()
    ).data
    row = updated[0]

    job_rows = (
        supabase_admin.table("hr_job_postings")
        .select("id,title")
        .eq("id", row["job_posting_id"])
        .limit(1)
        .execute()
    ).data or []
    title = job_rows[0].get("title", "") if job_rows else ""
    interview_activity = _interview_activity_by_key(body.business_id)

    return _candidate_response(row, title, completed_application_ids, completed_emails, interview_activity)


@router.post("/candidates/promote-from-interview")
async def promote_interview_candidate_to_final_round(
    body: HrCandidatePromoteRequest,
    user_id: str = Depends(get_user_id),
) -> HrCandidateResponse:
    """Move a candidate to Final Round starting from an interview session rather than an
    existing application — for candidates interviewed via an ad hoc invite who never went
    through the careers-apply flow. Creates the missing application record from the real
    session data (name/email/phone/job) rather than leaving the promotion impossible.
    """
    verify_business_access(user_id, body.business_id)

    session_rows = (
        supabase_admin.table("hr_interview_sessions")
        .select("*")
        .eq("business_id", body.business_id)
        .eq("id", body.session_id)
        .limit(1)
        .execute()
    ).data
    if not session_rows:
        raise HTTPException(status_code=404, detail="Interview session not found.")
    session = session_rows[0]

    if session.get("status") not in ("completed", "reviewed"):
        raise HTTPException(
            status_code=422,
            detail="This candidate needs a completed interview before moving to Final Round.",
        )

    application = None
    if session.get("application_id"):
        rows = (
            supabase_admin.table("hr_job_applications")
            .select("*")
            .eq("business_id", body.business_id)
            .eq("id", session["application_id"])
            .limit(1)
            .execute()
        ).data
        application = rows[0] if rows else None
    if application is None:
        email = (session.get("candidate_email") or "").strip().lower()
        if email:
            rows = (
                supabase_admin.table("hr_job_applications")
                .select("*")
                .eq("business_id", body.business_id)
                .ilike("candidate_email", email)
                .order("submitted_at", desc=True)
                .limit(1)
                .execute()
            ).data
            application = rows[0] if rows else None

    now = datetime.now(timezone.utc).isoformat()

    if application is None:
        if not session.get("job_posting_id"):
            raise HTTPException(
                status_code=422,
                detail="This interview isn't linked to a job posting, so a candidate record can't be created.",
            )
        inserted = (
            supabase_admin.table("hr_job_applications")
            .insert(
                {
                    "business_id": body.business_id,
                    "job_posting_id": session["job_posting_id"],
                    "candidate_name": session.get("candidate_name") or "",
                    "candidate_email": session.get("candidate_email") or "",
                    "candidate_phone": session.get("candidate_phone") or "",
                    # No resume/cover letter exists — this candidate came from an ad hoc
                    # interview invite, not the careers-apply flow that uploads one.
                    # resume_storage_path is NOT NULL with no default; "" is the honest
                    # "no file on record" value, and has_resume/has_cover_letter already
                    # treat an empty path as falsy.
                    "resume_storage_path": "",
                    "status": "reviewed",
                    "stage": "final_round",
                    "final_round_at": now,
                    "source": "native",
                    "submitted_at": session.get("started_at") or now,
                }
            )
            .execute()
        ).data
        application = inserted[0]
        supabase_admin.table("hr_interview_sessions").update({"application_id": application["id"]}).eq(
            "id", session["id"]
        ).execute()
    else:
        completed_application_ids, completed_emails = _completed_interview_keys(body.business_id)
        if not _is_eligible_for_final_round(application, completed_application_ids, completed_emails):
            raise HTTPException(
                status_code=422,
                detail="This candidate needs at least one completed interview before moving to Final Round.",
            )
        updated = (
            supabase_admin.table("hr_job_applications")
            .update({"stage": "final_round", "final_round_at": now})
            .eq("business_id", body.business_id)
            .eq("id", application["id"])
            .select("*")
            .execute()
        ).data
        application = updated[0]

    job_rows = (
        supabase_admin.table("hr_job_postings")
        .select("id,title")
        .eq("id", application["job_posting_id"])
        .limit(1)
        .execute()
    ).data or []
    title = job_rows[0].get("title", "") if job_rows else ""
    completed_application_ids, completed_emails = _completed_interview_keys(body.business_id)
    interview_activity = _interview_activity_by_key(body.business_id)

    return _candidate_response(application, title, completed_application_ids, completed_emails, interview_activity)


_APPLICATIONS_BUCKET = "hr-job-applications"


def _signed_application_file_url(path: str) -> str | None:
    try:
        result = supabase_admin.storage.from_(_APPLICATIONS_BUCKET).create_signed_url(path, 60 * 60)
        if isinstance(result, dict):
            return result.get("signedURL") or result.get("signed_url")
    except Exception:
        return None
    return None


def _get_application_or_404(business_id: str, application_id: str) -> dict:
    rows = (
        supabase_admin.table("hr_job_applications")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", application_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Candidate application not found.")
    return rows[0]


@router.get("/candidates/{application_id}/resume")
async def get_hr_candidate_resume_url(
    application_id: str,
    business_id: str,
    _: str = Depends(require_business_access()),
) -> HrCandidateFileUrlResponse:
    application = _get_application_or_404(business_id, application_id)
    path = application.get("resume_storage_path")
    url = _signed_application_file_url(path) if path else None
    if not url:
        raise HTTPException(status_code=404, detail="No resume on file for this candidate.")
    return HrCandidateFileUrlResponse(url=url)


@router.get("/candidates/{application_id}/cover-letter")
async def get_hr_candidate_cover_letter_url(
    application_id: str,
    business_id: str,
    _: str = Depends(require_business_access()),
) -> HrCandidateFileUrlResponse:
    application = _get_application_or_404(business_id, application_id)
    path = application.get("cover_letter_storage_path")
    url = _signed_application_file_url(path) if path else None
    if not url:
        raise HTTPException(status_code=404, detail="No cover letter on file for this candidate.")
    return HrCandidateFileUrlResponse(url=url)


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
            category=body.category,
            user_id=user_id,
            conversation_id=body.conversation_id,
        )
    except Exception as exc:
        logger.error("HR onboarding chat failed for business %s: %s", body.business_id, exc)
        raise HTTPException(status_code=502, detail="The HR onboarding assistant is unavailable right now.") from exc


@router.post("/onboarding/chat/stream")
async def stream_chat_with_hr_onboarding_agent(
    body: OnboardingChatRequest,
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    verify_business_access(user_id, body.business_id)
    return StreamingResponse(
        stream_onboarding_question(
            business_id=body.business_id,
            question=body.question.strip(),
            document_id=body.document_id,
            category=body.category,
            user_id=user_id,
            conversation_id=body.conversation_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/onboarding/conversations/{conversation_id}")
async def delete_hr_onboarding_conversation_endpoint(
    conversation_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    try:
        deleted = delete_hr_onboarding_conversation(conversation_id=conversation_id, business_id=business_id)
    except Exception as exc:
        logger.error("Failed to delete HR onboarding conversation %s: %s", conversation_id, exc)
        raise HTTPException(status_code=502, detail="Failed to delete conversation.") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"deleted": True}


@router.delete("/onboarding/conversations")
async def delete_all_hr_onboarding_conversations_endpoint(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    try:
        count = delete_all_hr_onboarding_conversations(business_id=business_id)
    except Exception as exc:
        logger.error("Failed to clear HR onboarding conversation history for business %s: %s", business_id, exc)
        raise HTTPException(status_code=502, detail="Failed to clear conversation history.") from exc
    return {"deleted": count}


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
    status = body.status
    sync_state = "native_only"

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

    status = body.status
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
