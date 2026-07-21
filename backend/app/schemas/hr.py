from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class GreenhouseConnectionRequest(BaseModel):
    business_id: str
    board_token: str = Field(min_length=1)
    board_url: str = Field(min_length=1)
    job_board_api_key: Optional[str] = None


class GreenhouseConnectionStatusResponse(BaseModel):
    connected: bool
    board_token: Optional[str] = None
    board_url: Optional[str] = None
    board_name: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None
    last_sync_error: Optional[str] = None
    last_job_count: int = 0


class GreenhouseRefreshResponse(BaseModel):
    board_name: str
    total_jobs: int
    last_sync_at: str
    last_sync_status: str


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
    source: Literal["native", "greenhouse"]
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
    greenhouse_managed_distribution: bool = False
    linkedin_status: str = ""
    indeed_status: str = ""
    ai_status: str = ""
    greenhouse_job_id: Optional[str] = None
    greenhouse_internal_job_id: Optional[str] = None
    greenhouse_board_token_snapshot: Optional[str] = None
    metadata: Any = None
    source_payload: Any = None


class HrJobsResponse(BaseModel):
    source_of_truth: Literal["native", "greenhouse"]
    greenhouse_connected: bool
    greenhouse_status: Optional[GreenhouseConnectionStatusResponse] = None
    jobs: list[HrJobPostingResponse]
    native_draft_count: int = 0


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
