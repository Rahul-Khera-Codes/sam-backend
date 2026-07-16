from __future__ import annotations
from typing import Optional
from datetime import datetime
from urllib.parse import urlparse
from pydantic import BaseModel, field_validator


class AddCompetitorRequest(BaseModel):
    business_id: str
    website_url: str


class UpdateCompetitorRequest(BaseModel):
    name: Optional[str] = None
    linkedin_url: Optional[str] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None

    @field_validator("linkedin_url", "facebook_url", "instagram_url", "youtube_url", mode="before")
    @classmethod
    def normalize_social_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        trimmed = value.strip()
        if not trimmed:
            return None

        parsed = urlparse(trimmed)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Social links must be full http(s) URLs.")
        return trimmed


class CompetitorResponse(BaseModel):
    id: str
    business_id: str
    name: Optional[str] = None
    website_url: str
    linkedin_url: Optional[str] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    discovery_status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CompetitorListResponse(BaseModel):
    competitors: list[CompetitorResponse]


class ReportCreatedResponse(BaseModel):
    id: str
    status: str


class PlatformActivity(BaseModel):
    """One platform's slice of the synthesized report, per competitor."""

    platform: str
    summary: Optional[str] = None
    pricing_signals: Optional[str] = None
    feature_launches: Optional[str] = None
    general_activity: Optional[str] = None
    # AI-judged directly, not inferred from text pattern-matching after the fact — "sparse" | "sufficient" | None
    # (None for reports generated before this field existed).
    data_availability: Optional[str] = None


class CompetitorReportResult(BaseModel):
    overview: Optional[str] = None
    platforms: list[PlatformActivity] = []


class CompetitorReportResponse(BaseModel):
    id: str
    competitor_id: str
    business_id: str
    status: str
    error_message: Optional[str] = None
    result: Optional[CompetitorReportResult] = None
    created_at: datetime
    updated_at: datetime


class CompetitorReportListResponse(BaseModel):
    reports: list[CompetitorReportResponse]
