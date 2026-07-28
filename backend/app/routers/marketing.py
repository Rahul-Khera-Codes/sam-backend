"""
Marketing Employee mock router.

These endpoints are intentionally in-memory and API-shaped so the frontend can
exercise the Marketing Employee flow before real generation, storage, scheduling,
and publishing infrastructure is added.
"""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.auth import get_user_id, verify_business_access

router = APIRouter(prefix="/marketing", tags=["marketing"])

AspectRatio = Literal["1:1", "9:16", "16:9", "2:3"]
Platform = Literal["instagram", "x", "linkedin", "tiktok"]


class MarketingWorkspaceResponse(BaseModel):
    last_updated_label: str
    idea: str
    aspect_ratio: AspectRatio
    image_count: int
    advanced_settings_enabled: bool
    generated_assets: list["GeneratedAssetResponse"] = Field(default_factory=list)
    scheduled_posts: list["ScheduledPostResponse"] = Field(default_factory=list)


class GenerateCampaignRequest(BaseModel):
    idea: str
    aspect_ratio: AspectRatio
    image_count: int = Field(ge=1, le=9)
    advanced_settings_enabled: bool = True


class GeneratedAssetResponse(BaseModel):
    id: str
    title: str
    platform: Platform
    format: Literal["post", "reel", "video"]
    aspect_ratio: AspectRatio
    caption: str
    thumbnail_variant: Literal["botanical", "breakfast", "community", "serum", "moodboard", "creator", "studio"]


class RandomIdeaResponse(BaseModel):
    idea: str


class PublishPostRequest(BaseModel):
    asset_id: str
    caption: str
    platforms: list[Platform]
    scheduled_for: str | None = None


class ScheduledPostResponse(BaseModel):
    id: str
    asset_id: str
    title: str
    caption: str
    platforms: list[Platform]
    status: Literal["scheduled", "draft", "published"]
    scheduled_for: str
    thumbnail_variant: str


class PublishPostResponse(BaseModel):
    scheduled_post: ScheduledPostResponse
    scheduled_posts: list[ScheduledPostResponse]


_DEFAULT_IDEA = "A poster for a black friday sale for my LED water bottle product. I want it with gold accents."
_MOCK_ASSETS: dict[str, list[GeneratedAssetResponse]] = {}
_MOCK_SCHEDULED_POSTS: dict[str, list[ScheduledPostResponse]] = {}

_RANDOM_IDEAS = [
    "A premium carousel post for a winter launch of my smart desk lamp, using soft blue lighting and crisp product closeups.",
    "A bold Instagram story for a weekend flash sale on handmade candles, with warm shadows and minimal copy.",
    "A product poster for a new organic skincare bundle, using clean white space, botanical accents, and a calm luxury feel.",
]

_CALENDAR_SLOTS = [
    "2026-07-08T09:00:00Z",
    "2026-07-10T15:30:00Z",
    "2026-07-15T08:00:00Z",
    "2026-07-21T10:00:00Z",
    "2026-07-24T14:30:00Z",
]


def _mock_assets_for_campaign(request: GenerateCampaignRequest) -> list[GeneratedAssetResponse]:
    requested_count = max(3, min(request.image_count, 9))
    base_assets = [
        ("Routine Refresh.", "instagram", "post", "botanical"),
        ("Healthy Starts.", "instagram", "post", "breakfast"),
        ("Community First.", "linkedin", "post", "community"),
        ("Glow Routine", "instagram", "reel", "serum"),
        ("Behind the Blend", "instagram", "reel", "moodboard"),
        ("GRWM Demo", "tiktok", "video", "creator"),
        ("Studio Energy", "tiktok", "video", "studio"),
        ("Launch Notes", "linkedin", "post", "moodboard"),
        ("Founder Pick", "instagram", "post", "serum"),
    ]

    return [
        GeneratedAssetResponse(
            id=f"asset_{index + 1}_{uuid4().hex[:8]}",
            title=title,
            platform=platform,
            format=format_,
            aspect_ratio=request.aspect_ratio,
            caption=(
                "A polished campaign concept based on: "
                f"{request.idea.strip() or _DEFAULT_IDEA}"
            ),
            thumbnail_variant=variant,
        )
        for index, (title, platform, format_, variant) in enumerate(base_assets[:requested_count])
    ]


def _next_calendar_slot(business_id: str) -> str:
    used_count = len(_MOCK_SCHEDULED_POSTS.get(business_id, []))
    return _CALENDAR_SLOTS[used_count % len(_CALENDAR_SLOTS)]


@router.get("/workspace", response_model=MarketingWorkspaceResponse)
async def get_marketing_workspace(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    return MarketingWorkspaceResponse(
        last_updated_label="Last 7 days",
        idea=_DEFAULT_IDEA,
        aspect_ratio="2:3",
        image_count=3,
        advanced_settings_enabled=True,
        generated_assets=_MOCK_ASSETS.get(business_id, []),
        scheduled_posts=_MOCK_SCHEDULED_POSTS.get(business_id, []),
    )


@router.post("/campaigns/generate", response_model=list[GeneratedAssetResponse])
async def generate_marketing_campaign(
    body: GenerateCampaignRequest,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    assets = _mock_assets_for_campaign(body)
    _MOCK_ASSETS[business_id] = assets
    return assets


@router.post("/campaigns/randomize", response_model=RandomIdeaResponse)
async def randomize_marketing_campaign_idea(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    index = datetime.now(timezone.utc).second % len(_RANDOM_IDEAS)
    return RandomIdeaResponse(idea=_RANDOM_IDEAS[index])


@router.post("/posts/publish", response_model=PublishPostResponse)
async def publish_marketing_post(
    body: PublishPostRequest,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    assets = _MOCK_ASSETS.get(business_id, [])
    selected_asset = next((asset for asset in assets if asset.id == body.asset_id), None)
    scheduled_post = ScheduledPostResponse(
        id=f"post_{uuid4().hex[:10]}",
        asset_id=body.asset_id,
        title=selected_asset.title if selected_asset else "Scheduled campaign post",
        caption=body.caption,
        platforms=body.platforms,
        status="scheduled",
        scheduled_for=body.scheduled_for or _next_calendar_slot(business_id),
        thumbnail_variant=selected_asset.thumbnail_variant if selected_asset else "moodboard",
    )

    _MOCK_SCHEDULED_POSTS.setdefault(business_id, []).append(scheduled_post)
    return PublishPostResponse(
        scheduled_post=scheduled_post,
        scheduled_posts=_MOCK_SCHEDULED_POSTS[business_id],
    )


@router.get("/calendar", response_model=list[ScheduledPostResponse])
async def get_marketing_calendar(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)

    return _MOCK_SCHEDULED_POSTS.get(business_id, [])
