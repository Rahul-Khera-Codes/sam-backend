from __future__ import annotations
import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, field_validator

# Matches a LinkedIn profile URL (with or without www/https, trailing slash, or query string).
# Mandatory server-side check — the frontend has the same check, but this endpoint must not
# trust that alone (defense in depth; also protects direct API callers) and must reject
# obviously-invalid input before spending a real, paid Apify run on it.
_LINKEDIN_PROFILE_URL_RE = re.compile(r"^https?://(www\.)?linkedin\.com/in/[^\s/]+/?(\?[^\s]*)?$", re.IGNORECASE)


class LeadLookupRequest(BaseModel):
    business_id: str
    linkedin_url: str

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, v: str) -> str:
        if not _LINKEDIN_PROFILE_URL_RE.match(v.strip()):
            raise ValueError("linkedin_url must be a LinkedIn profile URL, e.g. https://www.linkedin.com/in/your-profile")
        return v


class LeadLookupCreatedResponse(BaseModel):
    id: str
    status: str


class LeadCardResult(BaseModel):
    """LLM-enriched card fields shown to the user, generated from the raw Apify scrape."""

    full_name: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    predicted_email: Optional[str] = None
    email_confidence: Optional[str] = None  # e.g. "catch_all", "unverified_guess" — surfaced honestly, not implied "verified"
    job_role_insights: Optional[str] = None
    pain_points_and_sales_angles: Optional[str] = None
    personal_interests: Optional[str] = None
    best_time_to_reach: Optional[str] = None
    outreach_email_draft: Optional[str] = None


class LeadLookupResponse(BaseModel):
    id: str
    business_id: str
    linkedin_url: str
    status: str
    error_message: Optional[str] = None
    is_saved: bool
    result: Optional[LeadCardResult] = None
    created_at: datetime
    updated_at: datetime


class LeadLookupHistoryResponse(BaseModel):
    lookups: list[LeadLookupResponse]
