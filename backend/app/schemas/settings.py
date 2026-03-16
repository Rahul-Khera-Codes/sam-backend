from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime


# ── Agent Settings ────────────────────────────

class AgentSettingItem(BaseModel):
    feature_key: str
    is_enabled: bool
    config_value: Optional[Dict[str, Any]] = {}


class AgentSettingsResponse(BaseModel):
    business_id: str
    settings: List[AgentSettingItem]


class UpdateAgentSettingsRequest(BaseModel):
    settings: List[AgentSettingItem]


# ── Agent State (on/off toggle) ───────────────

class AgentStateResponse(BaseModel):
    business_id: str
    is_active: bool
    toggled_at: Optional[datetime]


class ToggleAgentStateRequest(BaseModel):
    is_active: bool


# ── Forwarding Contacts ───────────────────────

class ForwardingContactResponse(BaseModel):
    id: str
    business_id: str
    location_id: Optional[str]
    name: str
    phone: str
    department_tag: Optional[str]
    priority: str
    is_active: bool
    created_at: datetime


class CreateForwardingContactRequest(BaseModel):
    name: str
    phone: str
    department_tag: Optional[str] = None
    priority: str = "medium"
    location_id: Optional[str] = None


class UpdateForwardingContactRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    department_tag: Optional[str] = None
    priority: Optional[str] = None
    is_active: Optional[bool] = None


# ── Forwarding Rules ──────────────────────────

class ForwardingRuleResponse(BaseModel):
    id: str
    business_id: str
    name: str
    condition_type: str
    condition_value: Optional[Dict[str, Any]]
    action: Optional[Dict[str, Any]]
    is_active: bool
    priority_order: int
    created_at: datetime


class CreateForwardingRuleRequest(BaseModel):
    name: str
    condition_type: str
    condition_value: Optional[Dict[str, Any]] = {}
    action: Optional[Dict[str, Any]] = {}
    priority_order: int = 0


# ── Communication Settings ────────────────────

class CommunicationSettingItem(BaseModel):
    channel: str        # call, email, sms
    type: str           # reminder, followup
    is_enabled: bool
    days_offset: int
    script: Optional[str]


class CommunicationSettingsResponse(BaseModel):
    business_id: str
    settings: List[CommunicationSettingItem]


class UpdateCommunicationSettingsRequest(BaseModel):
    settings: List[CommunicationSettingItem]


# ── Analytics ─────────────────────────────────

class AnalyticsSummaryResponse(BaseModel):
    period: str
    total_calls: int
    total_calls_change_pct: Optional[float]
    avg_call_duration_seconds: Optional[float]
    avg_duration_change_pct: Optional[float]
    success_rate_pct: Optional[float]
    success_rate_change_pct: Optional[float]
    completed_calls: int
    missed_calls: int
    forwarded_calls: int


class RecentActivityItem(BaseModel):
    call_id: str
    title: str
    description: Optional[str]
    status: str
    sentiment: Optional[str]
    time_ago: str
    created_at: datetime


class RecentActivityResponse(BaseModel):
    items: List[RecentActivityItem]
