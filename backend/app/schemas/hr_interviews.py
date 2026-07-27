from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


InterviewQuestionCategory = Literal[
    "warm_up",
    "core",
    "technical",
    "behavioral",
    "situational",
    "culture",
    "closing",
]
InterviewQuestionSource = Literal[
    "manual",
    "ai_suggested",
    "platform_core",
    "greenhouse_import",
]


class HrInterviewSettings(BaseModel):
    duration_minutes: int = Field(default=45, ge=15, le=180)
    interview_type: Literal["video_audio", "audio", "text"] = "video_audio"
    language: str = Field(default="en-US", min_length=2, max_length=20)
    difficulty: Literal["entry", "mid", "senior", "lead"] = "mid"
    interviewer_persona: Literal[
        "professional_structured",
        "warm_conversational",
        "technical_direct",
    ] = "professional_structured"
    allow_follow_up_probing: bool = True
    adaptive_question_ordering: bool = True


class HrInterviewQuestionDraft(BaseModel):
    id: Optional[str] = None
    question_text: str = Field(min_length=10, max_length=2000)
    category: InterviewQuestionCategory = "core"
    competency: str = Field(default="", max_length=120)
    order_index: int = Field(ge=0)
    enabled: bool = True
    required: bool = True
    ai_generated: bool = False
    source: InterviewQuestionSource = "manual"
    expected_seconds: int = Field(default=120, ge=15, le=900)
    max_follow_ups: int = Field(default=2, ge=0, le=5)

    @field_validator("question_text")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        return " ".join(value.split())


class HrInterviewRubricCriterionDraft(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    weight: float = Field(gt=0, le=100)
    order_index: int = Field(ge=0)
    score_1_anchor: str = Field(default="", max_length=1000)
    score_3_anchor: str = Field(default="", max_length=1000)
    score_5_anchor: str = Field(default="", max_length=1000)


class HrInterviewBankDraftUpsertRequest(BaseModel):
    business_id: str
    settings: HrInterviewSettings
    opening_message: str = Field(default="", max_length=2000)
    closing_message: str = Field(default="", max_length=2000)
    questions: list[HrInterviewQuestionDraft] = Field(max_length=40)
    rubric: list[HrInterviewRubricCriterionDraft] = Field(max_length=20)


class HrInterviewBankResponse(BaseModel):
    id: Optional[str] = None
    business_id: str
    job_posting_id: str
    job_title: str
    settings: HrInterviewSettings
    opening_message: str
    closing_message: str
    questions: list[HrInterviewQuestionDraft]
    rubric: list[HrInterviewRubricCriterionDraft]
    draft_revision: int
    active_version_id: Optional[str] = None
    active_version_number: Optional[int] = None
    updated_at: Optional[str] = None


class HrInterviewAiSuggestRequest(BaseModel):
    business_id: str
    count: int = Field(default=4, ge=1, le=8)
    guidance: str = Field(default="", max_length=1000)


class HrInterviewAiSuggestResponse(BaseModel):
    model: str
    questions: list[HrInterviewQuestionDraft]
    rubric: list[HrInterviewRubricCriterionDraft] = []
    message: str


class HrInterviewPreviewRequest(BaseModel):
    business_id: str


class HrInterviewPreviewTurn(BaseModel):
    speaker: Literal["interviewer", "candidate", "system"]
    text: str
    question_id: Optional[str] = None


class HrInterviewPreviewResponse(BaseModel):
    model: str
    synthetic: bool = True
    turns: list[HrInterviewPreviewTurn]


class HrInterviewPublishRequest(BaseModel):
    business_id: str


class HrInterviewPublishResponse(BaseModel):
    active_version_id: str
    version_number: int
    published_at: str


InterviewSessionKind = Literal["ai_screen", "human_external"]
InterviewSessionStatus = Literal[
    "draft",
    "invited",
    "opened",
    "in_progress",
    "completed",
    "reviewed",
    "cancelled",
    "expired",
    "failed",
]
InterviewRecommendation = Literal["strong_hire", "hire", "review", "no_hire"]


class HrInterviewInviteRequest(BaseModel):
    business_id: str
    job_posting_id: str
    candidate_name: str = Field(min_length=1, max_length=200)
    candidate_email: str = Field(min_length=3, max_length=320)
    candidate_phone: str = Field(default="", max_length=80)
    candidate_id: Optional[str] = None
    application_id: Optional[str] = None
    greenhouse_candidate_id: Optional[str] = None
    greenhouse_application_id: Optional[str] = None
    frontend_base_url: Optional[str] = Field(default=None, max_length=500)


class HrHumanInterviewUpsertRequest(BaseModel):
    business_id: str
    job_posting_id: str
    candidate_name: str = Field(min_length=1, max_length=200)
    candidate_email: str = Field(default="", max_length=320)
    candidate_phone: str = Field(default="", max_length=80)
    provider: str = Field(default="", max_length=120)
    reference: str = Field(default="", max_length=500)
    scheduled_at: Optional[str] = None
    status: InterviewSessionStatus = "invited"
    stage: str = Field(default="human_interview", max_length=120)
    recruiter_notes: str = Field(default="", max_length=10000)
    recruiter_score: Optional[float] = Field(default=None, ge=0, le=100)


class HrHumanInterviewEmailDraftRequest(BaseModel):
    business_id: str
    job_posting_id: str
    candidate_name: str = Field(default="", max_length=200)
    provider: str = Field(default="", max_length=120)
    scheduled_at: Optional[str] = None
    guidance: str = Field(default="", max_length=1000)


class HrHumanInterviewEmailDraftResponse(BaseModel):
    subject: str
    message: str


class HrHumanInterviewResponse(BaseModel):
    session: "HrInterviewSessionSummary"
    email_delivery_status: str = "not_attempted"
    email_delivery_message: str = ""


class HrInterviewStatusUpdateRequest(BaseModel):
    business_id: str
    status: InterviewSessionStatus
    stage: Optional[str] = Field(default=None, max_length=120)


class HrInterviewNotesUpdateRequest(BaseModel):
    business_id: str
    recruiter_notes: str = Field(default="", max_length=10000)
    recruiter_score: Optional[float] = Field(default=None, ge=0, le=100)


class HrInterviewSessionSummary(BaseModel):
    id: str
    business_id: str
    job_posting_id: str
    job_title: str = ""
    interview_kind: InterviewSessionKind
    status: InterviewSessionStatus
    stage: str
    candidate_name: str
    candidate_email: str = ""
    candidate_phone: str = ""
    active_version_id: Optional[str] = None
    active_version_number: Optional[int] = None
    invited_at: Optional[str] = None
    opened_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    human_interview_provider: Optional[str] = None
    human_interview_reference: Optional[str] = None
    human_interview_scheduled_at: Optional[str] = None
    recruiter_notes: str = ""
    recruiter_score: Optional[float] = None
    greenhouse_sync_status: str = "not_applicable"
    has_transcript: bool = False
    has_recording: bool = False
    outcome: Optional["HrInterviewOutcomeResponse"] = None


class HrInterviewPipelineResponse(BaseModel):
    ai_screens: list[HrInterviewSessionSummary] = Field(default_factory=list)
    human_interviews: list[HrInterviewSessionSummary] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


class HrInterviewTranscriptTurnResponse(BaseModel):
    id: str
    speaker: Literal["interviewer", "candidate", "system"]
    text: str
    question_id: Optional[str] = None
    question_order: Optional[int] = None
    sequence_order: int
    created_at: Optional[str] = None


class HrInterviewRecordingResponse(BaseModel):
    id: str
    status: str
    storage_bucket: str
    storage_path: str
    duration_seconds: int = 0
    signed_url: Optional[str] = None
    created_at: Optional[str] = None


class HrInterviewOutcomeResponse(BaseModel):
    id: str
    model: str = ""
    total_score: float = 0
    recommendation: InterviewRecommendation = "review"
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    criterion_scores: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: Optional[str] = None


class HrInterviewDetailResponse(BaseModel):
    session: HrInterviewSessionSummary
    transcript: list[HrInterviewTranscriptTurnResponse] = Field(default_factory=list)
    recordings: list[HrInterviewRecordingResponse] = Field(default_factory=list)


class HrInterviewInviteResponse(BaseModel):
    session: HrInterviewSessionSummary
    join_url: str
    email_delivery_status: str = "not_attempted"
    email_delivery_message: str = ""


class HrInterviewPublicJoinResponse(BaseModel):
    session_id: str
    business_id: str
    job_title: str
    candidate_name: str
    status: InterviewSessionStatus
    expires_at: Optional[str] = None
    interview_minutes: int = 45
    avatar_available: bool = True


class HrInterviewLiveSessionResponse(BaseModel):
    session_id: str
    room_name: str
    token: str
    livekit_url: str
    avatar_enabled: bool = True


class HrInterviewCandidateSessionRequest(BaseModel):
    avatar_enabled: bool = True


class HrInterviewRecordingDeleteResponse(BaseModel):
    deleted: bool


HrInterviewSessionSummary.model_rebuild()
HrHumanInterviewResponse.model_rebuild()
