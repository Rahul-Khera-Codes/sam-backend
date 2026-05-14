# backend/app/schemas/appointments.py
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict


class CreateAppointmentRequest(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    assigned_user_id: str
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    service: Optional[str] = None
    appointment_date: str   # YYYY-MM-DD
    appointment_time: str   # HH:MM 24h
    duration: Optional[int] = None
    notes: Optional[str] = None


class UpdateAppointmentRequest(BaseModel):
    business_id: str
    appointment_date: Optional[str] = None   # YYYY-MM-DD
    appointment_time: Optional[str] = None   # HH:MM 24h
    assigned_user_id: Optional[str] = None
    service: Optional[str] = None
    duration: Optional[int] = None
    notes: Optional[str] = None


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    business_id: str
    location_id: Optional[str] = None
    assigned_user_id: str
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    service: Optional[str] = None
    appointment_date: str
    appointment_time: str
    duration: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    confirmation_ref: Optional[str] = None
    created_at: Optional[str] = None


class CancelAppointmentResponse(BaseModel):
    id: str
    status: str   # "cancelled"
    message: str
