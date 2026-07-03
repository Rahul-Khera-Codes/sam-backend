from __future__ import annotations
from typing import Optional
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


class CreateCheckoutSessionRequest(BaseModel):
    business_id: str
    plan: str  # "starter" | "growth" | "professional" | "enterprise"


class CreateCheckoutSessionResponse(BaseModel):
    checkout_url: str


class CustomerPortalResponse(BaseModel):
    portal_url: str
