from __future__ import annotations
import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, field_validator

# Basic format check, not deliverability — also rejects embedded whitespace/newlines,
# which matters since this value flows into an email "To" header (header-injection safety).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_recipients(recipients: Optional[list[str]]) -> Optional[list[str]]:
    if recipients is None:
        return None
    for email in recipients:
        if not _EMAIL_RE.match(email):
            raise ValueError(f"'{email}' is not a valid email address.")
    return recipients


class CreateScheduleRequest(BaseModel):
    business_id: str
    name: str = "Sales Intelligence Digest"
    frequency: str = "weekly"  # daily | weekly | monthly
    recipients: list[str] = []
    include_lead_researcher: bool = True
    include_competitor_agent: bool = True
    include_market_agent: bool = True
    is_active: bool = False

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v):
        return _validate_recipients(v)


class UpdateScheduleRequest(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    recipients: Optional[list[str]] = None
    include_lead_researcher: Optional[bool] = None
    include_competitor_agent: Optional[bool] = None
    include_market_agent: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v):
        return _validate_recipients(v)


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
