# backend/app/schemas/appointments.py
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


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
    appointment_is_onsite: bool = False
    appointment_address_street: Optional[str] = None
    appointment_address_city: Optional[str] = None
    appointment_address_state: Optional[str] = None
    appointment_address_postal_code: Optional[str] = None
    appointment_address_country: Optional[str] = None


class UpdateAppointmentRequest(BaseModel):
    business_id: str
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    appointment_date: Optional[str] = None   # YYYY-MM-DD
    appointment_time: Optional[str] = None   # HH:MM 24h
    assigned_user_id: Optional[str] = None
    service: Optional[str] = None
    duration: Optional[int] = None
    notes: Optional[str] = None
    appointment_is_onsite: Optional[bool] = None
    appointment_address_street: Optional[str] = None
    appointment_address_city: Optional[str] = None
    appointment_address_state: Optional[str] = None
    appointment_address_postal_code: Optional[str] = None
    appointment_address_country: Optional[str] = None


VALID_APPOINTMENT_STATUSES = {"confirmed", "checked_in", "no_show", "cancelled"}


class UpdateAppointmentStatusRequest(BaseModel):
    business_id: str
    status: str


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
    appointment_is_onsite: Optional[bool] = False
    appointment_address_street: Optional[str] = None
    appointment_address_city: Optional[str] = None
    appointment_address_state: Optional[str] = None
    appointment_address_postal_code: Optional[str] = None
    appointment_address_country: Optional[str] = None
    status: Optional[str] = None
    confirmation_ref: Optional[str] = None
    created_at: Optional[str] = None


class CancelAppointmentResponse(BaseModel):
    id: str
    status: str   # "cancelled"
    message: str


PaymentStatus = Literal["pending", "paid", "unpaid", "refunded"]
PaymentType = Literal["cash", "credit_card", "debit_card", "e_transfer", "other"]


class AppointmentPaymentLineItem(BaseModel):
    service_id: Optional[str] = None
    service_name: str
    price: Optional[float] = None
    quantity: int = 1


class SaveAppointmentPaymentRequest(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    status: PaymentStatus = "pending"
    payment_type: Optional[PaymentType] = None
    line_items: list[AppointmentPaymentLineItem]
    tax_config_ids: list[str] = Field(default_factory=list)
    tip_amount: float = 0


class AppointmentPaymentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    appointment_id: str
    business_id: str
    location_id: Optional[str] = None
    status: PaymentStatus
    payment_type: Optional[PaymentType] = None
    line_items: list[dict]
    selected_taxes: list[dict]
    subtotal: float
    tax_total: float
    tip_amount: float
    grand_total: float
    paid_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
