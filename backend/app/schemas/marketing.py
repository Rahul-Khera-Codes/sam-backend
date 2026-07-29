from typing import Any, Literal

from pydantic import BaseModel, Field

AspectRatio = Literal["1:1", "9:16", "16:9", "2:3"]
MarketingPlatform = Literal["instagram", "x", "linkedin", "tiktok"]
MarketingFormat = Literal["post", "reel", "video"]
CampaignStatus = Literal["draft", "generating", "ready", "failed", "archived"]
AssetType = Literal["concept", "image", "video"]
AssetStatus = Literal["pending", "generating", "ready", "failed", "disabled"]
JobType = Literal["concepts", "image", "video"]
JobStatus = Literal["pending", "running", "completed", "failed", "disabled"]
ScheduledPostStatus = Literal["draft", "scheduled", "published", "cancelled"]


class MarketingCampaignCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    aspect_ratio: AspectRatio = "1:1"
    image_count: int = Field(default=3, ge=1, le=9)
    advanced_settings_enabled: bool = True
    platforms: list[MarketingPlatform] = Field(default_factory=lambda: ["instagram"])


class MarketingCampaignResponse(BaseModel):
    id: str
    business_id: str
    created_by: str | None = None
    prompt: str
    aspect_ratio: AspectRatio
    image_count: int
    advanced_settings_enabled: bool
    platforms: list[str]
    status: CampaignStatus
    selected_asset_id: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class MarketingAssetResponse(BaseModel):
    id: str
    business_id: str
    campaign_id: str
    parent_asset_id: str | None = None
    asset_type: AssetType
    platform: MarketingPlatform
    format: MarketingFormat
    aspect_ratio: AspectRatio
    title: str
    caption: str | None = None
    script: str | None = None
    prompt: str | None = None
    status: AssetStatus
    provider: str | None = None
    provider_asset_id: str | None = None
    storage_bucket: str | None = None
    storage_path: str | None = None
    content_type: str | None = None
    signed_url: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class MarketingGenerationJobResponse(BaseModel):
    id: str
    business_id: str
    campaign_id: str
    asset_id: str | None = None
    job_type: JobType
    provider: str
    status: JobStatus
    error_message: str | None = None
    result_asset_ids: list[str] = Field(default_factory=list)
    result_assets: list[MarketingAssetResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str
    updated_at: str


class MarketingWorkspaceResponse(BaseModel):
    campaigns: list[MarketingCampaignResponse] = Field(default_factory=list)
    assets: list[MarketingAssetResponse] = Field(default_factory=list)
    scheduled_posts: list["MarketingScheduledPostResponse"] = Field(default_factory=list)


class MarketingSignedUrlResponse(BaseModel):
    asset_id: str
    signed_url: str
    expires_in: int


class MarketingImageGenerationRequest(BaseModel):
    confirm_cost: bool


class MarketingVideoGenerationRequest(BaseModel):
    confirm_cost: bool


class MarketingScheduledPostCreateRequest(BaseModel):
    campaign_id: str
    asset_id: str
    caption: str = Field(min_length=1)
    platforms: list[MarketingPlatform] = Field(default_factory=lambda: ["instagram"])
    scheduled_for: str | None = None


class MarketingScheduledPostResponse(BaseModel):
    id: str
    business_id: str
    campaign_id: str
    asset_id: str
    created_by: str | None = None
    caption: str
    platforms: list[str]
    status: ScheduledPostStatus
    scheduled_for: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    asset: MarketingAssetResponse | None = None
    created_at: str
    updated_at: str


class RandomIdeaResponse(BaseModel):
    idea: str


MarketingWorkspaceResponse.model_rebuild()
