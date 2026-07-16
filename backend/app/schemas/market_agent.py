from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class AddCustomAnalystRequest(BaseModel):
    business_id: str
    name: str
    prompt_description: str


class UpdateCustomAnalystRequest(BaseModel):
    name: str
    prompt_description: str


class CustomAnalystResponse(BaseModel):
    id: str
    business_id: str
    name: str
    prompt_description: str
    created_at: datetime
    updated_at: datetime


class CustomAnalystListResponse(BaseModel):
    custom_analysts: list[CustomAnalystResponse]


class RefreshCreatedResponse(BaseModel):
    id: str
    status: str


class SourceCitation(BaseModel):
    url: str
    title: Optional[str] = None


class MarketAnalysisCardResponse(BaseModel):
    id: str
    run_id: str
    business_id: str
    analyst_type: str
    analyst_name: str
    custom_analyst_id: Optional[str] = None
    headline: Optional[str] = None
    insight: Optional[str] = None
    confidence: Optional[str] = None
    timeframe_or_impact: Optional[str] = None
    prompt_used: Optional[str] = None
    sources: list[SourceCitation] = []
    is_bookmarked: bool
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MarketAnalysisCardListResponse(BaseModel):
    cards: list[MarketAnalysisCardResponse]


class MarketAnalysisRunResponse(BaseModel):
    id: str
    business_id: str
    status: str
    triggered_by: str
    whats_changing_summary: Optional[str] = None
    error_message: Optional[str] = None
    cards: list[MarketAnalysisCardResponse] = []
    created_at: datetime
    updated_at: datetime


class BookmarkCardRequest(BaseModel):
    is_bookmarked: bool
