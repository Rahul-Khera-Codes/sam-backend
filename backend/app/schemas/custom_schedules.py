from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator


ALLOWED_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


class CustomScheduleBase(BaseModel):
    name: str
    schedule_type: str  # 'one_time' | 'recurring'
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days_of_week: Optional[List[str]] = None
    is_agent_disabled: bool = False
    open_time: Optional[str] = None  # "HH:MM"
    close_time: Optional[str] = None  # "HH:MM"
    is_enabled: bool = True
    priority: int = 100

    @field_validator("schedule_type")
    @classmethod
    def check_schedule_type(cls, v):
        if v not in ("one_time", "recurring"):
            raise ValueError("schedule_type must be 'one_time' or 'recurring'")
        return v

    @field_validator("days_of_week")
    @classmethod
    def check_days(cls, v):
        if v is None:
            return v
        for d in v:
            if d.lower() not in ALLOWED_DAYS:
                raise ValueError(f"Invalid day: {d}")
        return [d.lower() for d in v]


class CreateCustomScheduleRequest(CustomScheduleBase):
    location_id: str


class UpdateCustomScheduleRequest(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days_of_week: Optional[List[str]] = None
    is_agent_disabled: Optional[bool] = None
    open_time: Optional[str] = None
    close_time: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None


class CustomScheduleResponse(CustomScheduleBase):
    id: str
    business_id: str
    location_id: str
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
