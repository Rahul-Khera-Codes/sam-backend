from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class HrJobPostingUpsertRequest(BaseModel):
    business_id: str
    title: str = ""
    department: str = ""
    location: str = ""
    location_type: str = ""
    employment_type: str = ""
    job_type: str = ""
    shift: str = ""
    schedule: str = ""
    summary: str = ""
    perks: str = ""
    responsibilities: str = ""
    qualifications: str = ""
    requirements_skills: str = ""
    comments: str = ""
    pay_min: str = ""
    pay_max: str = ""
    pay_period: str = "year"
    benefits: str = ""
    required_experience: str = ""
    seniority: str = ""
    publish_in_linkedin: bool = False
    publish_in_indeed: bool = False
    status: Literal["draft", "active", "closed"] = "draft"


class HrJobPostingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source: Literal["native"]
    status: Literal["Draft", "Active", "Closed"]
    sync_state: str
    title: str
    department: str
    location: str
    location_type: str = ""
    employment_type: str
    job_type: str = ""
    shift: str = ""
    schedule: str = ""
    summary: str = ""
    perks: str = ""
    responsibilities: str = ""
    qualifications: str = ""
    requirements_skills: str = ""
    comments: str = ""
    pay_min: str = ""
    pay_max: str = ""
    pay_period: str = ""
    benefits: str = ""
    required_experience: str = ""
    seniority: str = ""
    posted_on: str = ""
    absolute_url: str = ""
    language: str = "en"
    content_html: str = ""
    platforms: list[str] = []
    applicants: int = 0
    applicant_bar_class_name: str = ""
    publish_in_linkedin: bool = False
    publish_in_indeed: bool = False
    linkedin_status: str = ""
    indeed_status: str = ""
    ai_status: str = ""
    metadata: Any = None
    source_payload: Any = None


class HrJobsResponse(BaseModel):
    jobs: list[HrJobPostingResponse]
    native_draft_count: int = 0


class HrCandidateJobResponse(BaseModel):
    id: str
    title: str
    absolute_url: str = ""


class HrCandidateResponse(BaseModel):
    id: str
    application_id: str
    candidate_id: str
    name: str
    title: str = ""
    company: str = ""
    location: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    status: str = ""
    stage: str = ""
    applied_at: Optional[str] = None
    source: str = ""
    prospect: bool = False


class HrCandidatesResponse(BaseModel):
    available: bool = False
    selected_job: Optional[HrCandidateJobResponse] = None
    candidates: list[HrCandidateResponse] = Field(default_factory=list)
    total: int = 0
    message: str = ""


class HrJobPublicResponse(BaseModel):
    id: str
    title: str
    is_accepting_applications: bool = False
    department: str = ""
    location: str = ""
    location_type: str = ""
    employment_type: str = ""
    summary: str = ""
    responsibilities: str = ""
    qualifications: str = ""
    benefits: str = ""
    pay_min: str = ""
    pay_max: str = ""
    pay_period: str = ""
    business_name: str = ""
    business_logo_url: Optional[str] = None


class HrParsedResumeResponse(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""


class HrJobApplicationSubmitResponse(BaseModel):
    id: str
    submitted_at: str


class HrDashboardPostingResponse(BaseModel):
    role: str
    team: str
    applicants: int
    linkedin: str
    indeed: str
    aiStatus: str


HrDraftField = Literal[
    "summary",
    "perks",
    "responsibilities",
    "qualifications",
    "requirements_skills",
    "benefits",
    "comments",
]

HrDraftAssistMode = Literal["generate_draft", "refine_draft", "field_action"]
HrDraftAssistAction = Literal["improve", "suggest", "format_list"]


class HrDraftAssistRequest(BaseModel):
    business_id: str
    mode: HrDraftAssistMode
    job_context: HrJobPostingUpsertRequest
    target_field: Optional[HrDraftField] = None
    action: Optional[HrDraftAssistAction] = None


class HrDraftAssistResponse(BaseModel):
    model: str
    generated_fields: dict[str, str]
    updated_fields: list[str] = []
    message: str
    used_knowledge_base_entries: int = 0
    used_document_sources: int = 0
