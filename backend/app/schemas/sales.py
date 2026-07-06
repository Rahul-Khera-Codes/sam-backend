from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class LeadLookupRequest(BaseModel):
    business_id: str
    linkedin_url: str


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
