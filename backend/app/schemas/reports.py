# backend/app/schemas/reports.py
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class OldestOutstandingItem(BaseModel):
    appointment_id: str
    client_name: str
    service: Optional[str] = None
    appointment_date: str
    owing_amount: float


class RevenueSummaryResponse(BaseModel):
    week_start: str
    week_end: str
    collected_this_week: float
    collected_last_week: float
    collected_change_pct: float
    tax_collected_this_week: float
    appointments_paid_this_week: int
    outstanding_balance_total: float
    outstanding_appointment_count: int
    oldest_outstanding: Optional[OldestOutstandingItem] = None
