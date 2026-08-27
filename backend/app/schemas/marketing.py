from typing import Any, Literal

from pydantic import BaseModel, Field

AspectRatio = Literal["1:1", "9:16", "16:9", "2:3"]
MarketingPlatform = Literal["instagram", "x", "linkedin", "tiktok"]
MarketingFormat = Literal["post", "reel", "video"]
CampaignStatus = Literal["draft", "generating", "ready", "failed", "archived"]
AssetType = Literal["concept", "image", "video"]
AssetStatus = Literal["pending", "generating", "ready", "failed", "disabled"]


class TikTokPublishOptions(BaseModel):
    privacy_level: str
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
JobType = Literal["concepts", "image", "video", "product_caption"]
JobStatus = Literal["pending", "running", "completed", "failed", "disabled"]
ScheduledPostStatus = Literal["draft", "scheduled", "publishing", "published", "failed", "cancelled"]


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
    reference_product_id: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class MarketingProductResponse(BaseModel):
    id: str
    business_id: str
    created_by: str | None = None
    name: str
    description: str | None = None
    storage_bucket: str
    storage_path: str
    content_type: str
    signed_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class MarketingProductSignedUrlResponse(BaseModel):
    product_id: str
    signed_url: str
    expires_in: int


class MarketingProductPostRequest(BaseModel):
    product_id: str
    platforms: list[MarketingPlatform] = Field(default_factory=lambda: ["instagram"])
    aspect_ratio: AspectRatio = "1:1"


class MarketingCaptionRegenerateRequest(BaseModel):
    current_caption: str | None = None


class MarketingCaptionResponse(BaseModel):
    caption: str


class MarketingLayerUploadResponse(BaseModel):
    storage_bucket: str
    storage_path: str
    signed_url: str


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


class MarketingDraftUpsertRequest(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    draft_data: dict[str, Any] = Field(default_factory=dict)
    asset_ids: list[str] = Field(default_factory=list)


class MarketingDraftResponse(BaseModel):
    id: str
    business_id: str
    created_by: str | None = None
    title: str
    draft_data: dict[str, Any] = Field(default_factory=dict)
    assets: list[MarketingAssetResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str


class MarketingPromptTemplateCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="Custom prompt saved for this business", max_length=240)
    prompt: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="Custom", max_length=80)


class MarketingPromptTemplateResponse(BaseModel):
    id: str
    business_id: str
    created_by: str | None = None
    title: str
    description: str
    prompt: str
    category: str
    created_at: str
    updated_at: str


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
    asset_ids: list[str] = Field(default_factory=list)
    caption: str = Field(min_length=1)
    platforms: list[MarketingPlatform] = Field(default_factory=lambda: ["instagram"])
    scheduled_for: str | None = None
    tiktok_options: TikTokPublishOptions | None = None


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
    provider_post_ids: dict[str, str] = Field(default_factory=dict)
    publish_error: str | None = None
    published_at: str | None = None
    attempt_count: int = 0
    asset: MarketingAssetResponse | None = None
    created_at: str
    updated_at: str


MarketingIntegrationProvider = Literal["instagram", "x", "tiktok", "linkedin"]


class MarketingIntegrationStatusResponse(BaseModel):
    provider: MarketingIntegrationProvider
    connected: bool
    account_id: str | None = None
    account_name: str | None = None
    account_avatar_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    last_error: str | None = None
    token_expires_at: str | None = None


class MarketingIntegrationsStatusResponse(BaseModel):
    integrations: list[MarketingIntegrationStatusResponse] = Field(default_factory=list)


class MarketingOAuthUrlResponse(BaseModel):
    url: str


class TikTokCreatorInfoResponse(BaseModel):
    creator_username: str | None = None
    creator_nickname: str | None = None
    creator_avatar_url: str | None = None
    privacy_level_options: list[str] = Field(default_factory=list)
    comment_disabled: bool = False
    duet_disabled: bool = False
    stitch_disabled: bool = False
    max_video_post_duration_sec: int | None = None


class MarketingOAuthCallbackRequest(BaseModel):
    code: str
    state: str
    business_id: str


class RandomIdeaResponse(BaseModel):
    idea: str


MarketingWorkspaceResponse.model_rebuild()
