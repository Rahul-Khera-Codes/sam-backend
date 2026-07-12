from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class BusinessBrandingResponse(BaseModel):
    business_id: str
    primary_color: str = ""
    secondary_color: str = ""
    accent_color: str = ""
    heading_font: str = ""
    body_font: str = ""
    mission: str = ""
    unique_value_claims: list[str] = []
    extra_guidelines: str = ""
    use_emojis: bool = True
    competitors: list[str] = []
    competitor_strengths: str = ""
    competitor_weaknesses: str = ""
    key_differentiator: str = ""
    emerging_trends: str = ""
    target_niche: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UpdateBusinessBrandingRequest(BaseModel):
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    mission: Optional[str] = None
    unique_value_claims: Optional[list[str]] = None
    extra_guidelines: Optional[str] = None
    use_emojis: Optional[bool] = None
    competitors: Optional[list[str]] = None
    competitor_strengths: Optional[str] = None
    competitor_weaknesses: Optional[str] = None
    key_differentiator: Optional[str] = None
    emerging_trends: Optional[str] = None
    target_niche: Optional[str] = None
