from __future__ import annotations

from typing import Literal, Optional

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
