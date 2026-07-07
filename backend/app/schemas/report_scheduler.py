from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class CreateScheduleRequest(BaseModel):
    business_id: str
    name: str = "Sales Intelligence Digest"
    frequency: str = "weekly"  # daily | weekly | monthly
    recipients: list[str] = []
    include_lead_researcher: bool = True
    include_competitor_agent: bool = True
    include_market_agent: bool = True
    is_active: bool = False


class UpdateScheduleRequest(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    recipients: Optional[list[str]] = None
    include_lead_researcher: Optional[bool] = None
    include_competitor_agent: Optional[bool] = None
    include_market_agent: Optional[bool] = None
    is_active: Optional[bool] = None


class ScheduleResponse(BaseModel):
    id: str
    business_id: str
    name: str
    frequency: str
    recipients: list[str]
    include_lead_researcher: bool
    include_competitor_agent: bool
    include_market_agent: bool
    is_active: bool
    last_sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleResponse]


class PreviewResponse(BaseModel):
    subject: str
    html_body: str


class SendTestResponse(BaseModel):
    sent: bool
    detail: Optional[str] = None
