from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class CallDirection(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


class CallStatus(str, Enum):
    initiating = "initiating"
    active = "active"
    completed = "completed"
    forwarded = "forwarded"
    failed = "failed"
    missed = "missed"


class CallSentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


# ── Request schemas ───────────────────────────

class InitiateCallRequest(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    caller_phone: Optional[str] = None
    caller_name: Optional[str] = None
    direction: CallDirection = CallDirection.outbound


class OutboundCallRequest(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    to_phone_number: str        # E.164 number to dial
    call_purpose: Optional[str] = None   # brief note stored in call record


class OutboundCallResponse(BaseModel):
    call_id: str
    livekit_room_id: str
    status: str


# ── Response schemas ──────────────────────────

class CallResponse(BaseModel):
    id: str
    business_id: str
    location_id: Optional[str]
    caller_name: Optional[str]
    caller_phone: Optional[str]
    direction: str
    status: str
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    sentiment: Optional[str]
    livekit_room_id: Optional[str]
    created_at: datetime


class TranscriptUtterance(BaseModel):
    id: str
    speaker: str           # agent | customer
    text: str
    timestamp_seconds: Optional[float]
    sequence_order: Optional[int]


class TranscriptResponse(BaseModel):
    call_id: str
    utterances: List[TranscriptUtterance]


class CallSummaryResponse(BaseModel):
    call_id: str
    summary_text: Optional[str]
    key_topics: Optional[list]
    insights: Optional[dict]
    generated_at: Optional[datetime]


class InitiateCallResponse(BaseModel):
    call_id: str
    livekit_room_id: str
    livekit_token: str      # frontend uses this to join the LiveKit room
    livekit_ws_url: str     # WebSocket URL for the client (same as LIVEKIT_URL)
    status: str
