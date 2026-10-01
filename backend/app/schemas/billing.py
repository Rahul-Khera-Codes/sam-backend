from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel


class SubscriptionResponse(BaseModel):
    has_subscription: bool
    status: Optional[str] = None
    plan_name: Optional[str] = None
    price_id: Optional[str] = None
    minute_limit: Optional[int] = None
    minutes_used: Optional[int] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    executive_agent_addon_enabled: bool = False
    executive_agent_addon_required: bool = False
    is_trial: bool = False
    trial_end: Optional[str] = None
    # "ok" | "grace" | "blocked" — see app/core/billing_gate.py. Drives the
    # frontend's grace-period banner; the backend's gated endpoints compute
    # this independently rather than trusting a value the client could send back.
    access_status: str = "ok"
    grace_days_remaining: Optional[int] = None


class CreateCheckoutSessionRequest(BaseModel):
    business_id: str
    plan: str  # "starter" | "growth" | "trial"


class CreateCheckoutSessionResponse(BaseModel):
    checkout_url: str


class CustomerPortalResponse(BaseModel):
    portal_url: str


class ExecutiveAgentAddonResponse(BaseModel):
    executive_agent_addon_enabled: bool


class ChangePlanRequest(BaseModel):
    business_id: str
    plan: Literal["starter", "growth", "enterprise"]


class ChangePlanResponse(BaseModel):
    status: str
    price_id: str
