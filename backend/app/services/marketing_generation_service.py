import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.marketing import (
    MarketingAssetResponse,
    MarketingCampaignCreateRequest,
    MarketingCampaignResponse,
    MarketingGenerationJobResponse,
    MarketingScheduledPostCreateRequest,
    MarketingScheduledPostResponse,
)

logger = logging.getLogger(__name__)

MARKETING_ASSETS_BUCKET = "marketing-assets"
SIGNED_URL_TTL_SECONDS = 60 * 60

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key, value in list(normalized.items()):
        if isinstance(value, datetime):
            normalized[key] = value.isoformat()
    return normalized


def _openai_client(timeout: float = 60.0) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=timeout, max_retries=1)


def _campaign_response(row: dict[str, Any]) -> MarketingCampaignResponse:
    return MarketingCampaignResponse(**_normalize_row(row))


def _asset_response(row: dict[str, Any], signed_url: str | None = None) -> MarketingAssetResponse:
    payload = _normalize_row(row)
    payload["signed_url"] = signed_url
    return MarketingAssetResponse(**payload)


def _scheduled_post_response(row: dict[str, Any], asset: dict[str, Any] | None = None) -> MarketingScheduledPostResponse:
    payload = _normalize_row(row)
    if asset:
      payload["asset"] = _asset_response(asset)
    return MarketingScheduledPostResponse(**payload)


def _job_response(row: dict[str, Any], result_assets: list[dict[str, Any]] | None = None) -> MarketingGenerationJobResponse:
    payload = _normalize_row(row)
    payload["result_assets"] = [_asset_response(asset) for asset in (result_assets or [])]
    return MarketingGenerationJobResponse(**payload)


def _get_single(table: str, row_id: str, business_id: str) -> dict[str, Any]:
    result = (
        supabase_admin.table(table)
        .select("*")
        .eq("id", row_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"{table} row not found")
    return result.data[0]


def _update_row(table: str, row_id: str, business_id: str, values: dict[str, Any]) -> dict[str, Any]:
    result = (
        supabase_admin.table(table)
        .update(values)
        .eq("id", row_id)
        .eq("business_id", business_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"{table} row not found")
    return result.data[0]


def _next_calendar_slot(business_id: str) -> str:
    result = (
        supabase_admin.table("marketing_scheduled_posts")
        .select("id")
        .eq("business_id", business_id)
        .execute()
    )
    used_count = len(result.data or [])
    return _CALENDAR_SLOTS[used_count % len(_CALENDAR_SLOTS)]


def _signed_asset_url(asset: dict[str, Any]) -> str | None:
    bucket = asset.get("storage_bucket")
    path = asset.get("storage_path")
    if not bucket or not path:
        return None

    try:
        signed = supabase_admin.storage.from_(bucket).create_signed_url(path, SIGNED_URL_TTL_SECONDS)
        return signed.get("signedURL") or signed.get("signed_url") or signed.get("signedUrl")
    except Exception as exc:
        logger.warning("Failed to create signed marketing asset URL: %s", exc)
        return None


def create_campaign(
    business_id: str,
    user_id: str,
    body: MarketingCampaignCreateRequest,
) -> MarketingCampaignResponse:
    row = {
        "business_id": business_id,
        "created_by": user_id,
        "prompt": body.prompt.strip(),
        "aspect_ratio": body.aspect_ratio,
        "image_count": body.image_count,
        "advanced_settings_enabled": body.advanced_settings_enabled,
        "platforms": body.platforms,
        "status": "draft",
        "metadata": {"source": "marketing_employee"},
    }
    result = supabase_admin.table("marketing_campaigns").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create marketing campaign")
    return _campaign_response(result.data[0])


def get_workspace(business_id: str) -> dict[str, list[Any]]:
    campaigns = (
        supabase_admin.table("marketing_campaigns")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(12)
        .execute()
        .data
        or []
    )
    assets = (
        supabase_admin.table("marketing_assets")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=False)
        .limit(50)
        .execute()
        .data
        or []
    )
    scheduled = list_calendar_posts(business_id)

    return {
        "campaigns": [_campaign_response(row) for row in campaigns],
        "assets": [_asset_response(row, _signed_asset_url(row)) for row in assets],
        "scheduled_posts": scheduled,
    }


def start_concepts_job(business_id: str, campaign_id: str) -> MarketingGenerationJobResponse:
    campaign = _get_single("marketing_campaigns", campaign_id, business_id)
    result = supabase_admin.table("marketing_generation_jobs").insert(
        {
            "business_id": business_id,
            "campaign_id": campaign["id"],
            "job_type": "concepts",
            "provider": "openai",
            "status": "pending",
            "metadata": {"prompt": campaign["prompt"]},
        }
    ).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create concepts generation job")

    _update_row("marketing_campaigns", campaign_id, business_id, {"status": "generating", "error_message": None})
    return _job_response(result.data[0])


async def run_concepts_job(job_id: str, business_id: str) -> None:
    job = _get_single("marketing_generation_jobs", job_id, business_id)
    campaign = _get_single("marketing_campaigns", job["campaign_id"], business_id)

    try:
        _update_row(
            "marketing_generation_jobs",
            job_id,
            business_id,
            {"status": "running", "started_at": _now_iso(), "error_message": None},
        )
        concepts = await _generate_caption_concepts(campaign)
        asset_ids: list[str] = []
        for concept in concepts[: campaign["image_count"]]:
            concept_aspect_ratio = _aspect_ratio_for_concept(campaign, concept["platform"], concept["format"])
            inserted = supabase_admin.table("marketing_assets").insert(
                {
                    "business_id": business_id,
                    "campaign_id": campaign["id"],
                    "asset_type": "concept",
                    "platform": concept["platform"],
                    "format": concept["format"],
                    "aspect_ratio": concept_aspect_ratio,
                    "title": concept["title"],
                    "caption": concept["caption"],
                    "script": concept.get("script"),
                    "prompt": concept["image_prompt"],
                    "status": "ready",
                    "provider": "openai",
                    "metadata": {
                        "source_job_id": job_id,
                        "advanced_settings_enabled": campaign.get("advanced_settings_enabled", True),
                    },
                }
            ).execute()
            if inserted.data:
                asset_ids.append(inserted.data[0]["id"])

        _update_row(
            "marketing_generation_jobs",
            job_id,
            business_id,
            {"status": "completed", "completed_at": _now_iso(), "result_asset_ids": asset_ids},
        )
        _update_row("marketing_campaigns", campaign["id"], business_id, {"status": "ready", "error_message": None})
    except Exception as exc:
        logger.exception("Marketing concepts job failed")
        _update_row(
            "marketing_generation_jobs",
            job_id,
            business_id,
            {"status": "failed", "completed_at": _now_iso(), "error_message": str(exc)},
        )
        _update_row("marketing_campaigns", campaign["id"], business_id, {"status": "failed", "error_message": str(exc)})


async def _generate_caption_concepts(campaign: dict[str, Any]) -> list[dict[str, str]]:
    platforms = campaign.get("platforms") or ["instagram"]
    count = int(campaign.get("image_count") or 3)
    client = _openai_client(timeout=45.0)
    response = await client.chat.completions.create(
        model=settings.marketing_text_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the Marketing Employee caption and creative planner. "
                    "Return only JSON. Create practical, brand-safe social concepts. "
                    "Do not claim platform publishing has happened."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create social post concepts for this campaign.\n"
                    f"Prompt: {campaign['prompt']}\n"
                    f"Advanced settings enabled: {campaign.get('advanced_settings_enabled', True)}\n"
                    f"Requested aspect ratio when advanced settings are enabled: {campaign['aspect_ratio']}\n"
                    f"Platforms: {', '.join(platforms)}\n"
                    f"Number of concepts: {count}\n"
                    "When advanced settings are disabled, choose the best native aspect ratio for each platform. "
                    "When advanced settings are enabled, every image_prompt must be composed for the requested aspect ratio exactly.\n"
                    "Return JSON with key concepts, an array. Each item must include "
                    "title, platform, format, caption, script, image_prompt."
                ),
            },
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"concepts": []}

    concepts = parsed.get("concepts") or []
    normalized = [_normalize_concept(item, campaign, index) for index, item in enumerate(concepts)]
    while len(normalized) < count:
        normalized.append(_fallback_concept(campaign, len(normalized)))
    return normalized[:count]


def _normalize_concept(item: dict[str, Any], campaign: dict[str, Any], index: int) -> dict[str, str]:
    fallback = _fallback_concept(campaign, index)
    platform = item.get("platform") if item.get("platform") in {"instagram", "x", "linkedin", "tiktok"} else fallback["platform"]
    format_ = item.get("format") if item.get("format") in {"post", "reel", "video"} else fallback["format"]
    return {
        "title": str(item.get("title") or fallback["title"])[:80],
        "platform": platform,
        "format": format_,
        "caption": str(item.get("caption") or fallback["caption"])[:2200],
        "script": str(item.get("script") or fallback["script"])[:2200],
        "image_prompt": str(item.get("image_prompt") or fallback["image_prompt"])[:2000],
    }


def _fallback_concept(campaign: dict[str, Any], index: int) -> dict[str, str]:
    platforms = campaign.get("platforms") or ["instagram"]
    platform = platforms[index % len(platforms)]
    format_ = "video" if platform == "tiktok" else "reel" if campaign.get("aspect_ratio") == "9:16" else "post"
    title = ["Routine Refresh", "Healthy Starts", "Community First", "Launch Moment", "Creator Demo"][index % 5]
    caption = f"{title}: {campaign['prompt']}"
    return {
        "title": title,
        "platform": platform,
        "format": format_,
        "caption": caption,
        "script": caption,
        "image_prompt": (
            f"Premium social media creative for: {campaign['prompt']}. "
            "Clean product photography, polished lighting, modern marketing layout, no readable text."
        ),
    }


def _aspect_ratio_for_concept(campaign: dict[str, Any], platform: str, format_: str) -> str:
    if campaign.get("advanced_settings_enabled", True):
        return campaign["aspect_ratio"]
    if platform in {"x", "linkedin"}:
        return "16:9"
    if platform == "tiktok" or format_ in {"reel", "video"}:
        return "9:16"
    return "1:1"


def start_image_job(business_id: str, concept_asset_id: str, confirm_cost: bool) -> MarketingGenerationJobResponse:
    if not confirm_cost:
        raise HTTPException(status_code=400, detail="Image generation requires cost confirmation")

    concept = _get_single("marketing_assets", concept_asset_id, business_id)
    if concept["asset_type"] != "concept":
        raise HTTPException(status_code=422, detail="Image generation must start from a concept asset")

    image_asset = supabase_admin.table("marketing_assets").insert(
        {
            "business_id": business_id,
            "campaign_id": concept["campaign_id"],
            "parent_asset_id": concept["id"],
            "asset_type": "image",
            "platform": concept["platform"],
            "format": concept["format"],
            "aspect_ratio": concept["aspect_ratio"],
            "title": concept["title"],
            "caption": concept["caption"],
            "script": concept.get("script"),
            "prompt": concept.get("prompt"),
            "status": "generating",
            "provider": "openai",
            "metadata": {"source_concept_asset_id": concept["id"]},
        }
    ).execute()
    if not image_asset.data:
        raise HTTPException(status_code=500, detail="Failed to create image asset")

    job = supabase_admin.table("marketing_generation_jobs").insert(
        {
            "business_id": business_id,
            "campaign_id": concept["campaign_id"],
            "asset_id": image_asset.data[0]["id"],
            "job_type": "image",
            "provider": "openai",
            "status": "pending",
            "metadata": {"source_concept_asset_id": concept["id"]},
        }
    ).execute()
    if not job.data:
        raise HTTPException(status_code=500, detail="Failed to create image generation job")

    return _job_response(job.data[0], [image_asset.data[0]])


async def run_image_job(job_id: str, business_id: str) -> None:
    job = _get_single("marketing_generation_jobs", job_id, business_id)
    if not job.get("asset_id"):
        return
    image_asset = _get_single("marketing_assets", job["asset_id"], business_id)

    try:
        _update_row(
            "marketing_generation_jobs",
            job_id,
            business_id,
            {"status": "running", "started_at": _now_iso(), "error_message": None},
        )
        image_bytes = await _generate_image_bytes(image_asset)
        storage_path = f"{business_id}/{image_asset['campaign_id']}/{image_asset['id']}.png"
        supabase_admin.storage.from_(MARKETING_ASSETS_BUCKET).upload(
            storage_path,
            image_bytes,
            {"content-type": "image/png"},
        )
        updated_asset = _update_row(
            "marketing_assets",
            image_asset["id"],
            business_id,
            {
                "status": "ready",
                "storage_bucket": MARKETING_ASSETS_BUCKET,
                "storage_path": storage_path,
                "content_type": "image/png",
                "error_message": None,
            },
        )
        _update_row(
            "marketing_generation_jobs",
            job_id,
            business_id,
            {
                "status": "completed",
                "completed_at": _now_iso(),
                "result_asset_ids": [updated_asset["id"]],
            },
        )
    except Exception as exc:
        logger.exception("Marketing image job failed")
        _update_row("marketing_assets", image_asset["id"], business_id, {"status": "failed", "error_message": str(exc)})
        _update_row(
            "marketing_generation_jobs",
            job_id,
            business_id,
            {"status": "failed", "completed_at": _now_iso(), "error_message": str(exc)},
        )


async def _generate_image_bytes(asset: dict[str, Any]) -> bytes:
    client = _openai_client(timeout=120.0)
    aspect_ratio = asset["aspect_ratio"]
    prompt = (
        f"{asset.get('prompt') or asset.get('caption') or asset['title']}\n\n"
        f"Create the final image for a {aspect_ratio} social media canvas. "
        "Respect the requested canvas orientation and composition. Keep key product subjects away from the edges "
        "so the creative can be safely previewed in platform frames."
    )
    response = await client.images.generate(
        model=settings.marketing_image_model,
        prompt=prompt,
        size=_image_size_for_aspect_ratio(aspect_ratio),
        n=1,
    )
    image = response.data[0]
    b64_json = getattr(image, "b64_json", None)
    if b64_json:
        return base64.b64decode(b64_json)

    url = getattr(image, "url", None)
    if not url:
        raise RuntimeError("OpenAI image generation returned no image data")

    async with httpx.AsyncClient(timeout=60) as client:
        fetched = await client.get(url)
        fetched.raise_for_status()
        return fetched.content


def _image_size_for_aspect_ratio(aspect_ratio: str) -> str:
    if aspect_ratio == "16:9":
        return "1536x1024"
    if aspect_ratio in {"9:16", "2:3"}:
        return "1024x1536"
    return "1024x1024"


def start_video_job_disabled(business_id: str, asset_id: str, confirm_cost: bool) -> MarketingGenerationJobResponse:
    if not confirm_cost:
        raise HTTPException(status_code=400, detail="Video generation requires cost confirmation")

    asset = _get_single("marketing_assets", asset_id, business_id)
    video_asset = supabase_admin.table("marketing_assets").insert(
        {
            "business_id": business_id,
            "campaign_id": asset["campaign_id"],
            "parent_asset_id": asset["id"],
            "asset_type": "video",
            "platform": asset["platform"],
            "format": "video",
            "aspect_ratio": asset["aspect_ratio"],
            "title": f"{asset['title']} video",
            "caption": asset.get("caption"),
            "script": asset.get("script") or asset.get("caption"),
            "prompt": asset.get("prompt"),
            "status": "disabled",
            "provider": "heygen",
            "error_message": "HeyGen video generation is disabled until credentials are configured.",
            "metadata": {"source_asset_id": asset["id"], "needs_credentials": True},
        }
    ).execute()
    if not video_asset.data:
        raise HTTPException(status_code=500, detail="Failed to create disabled video asset")

    job = supabase_admin.table("marketing_generation_jobs").insert(
        {
            "business_id": business_id,
            "campaign_id": asset["campaign_id"],
            "asset_id": video_asset.data[0]["id"],
            "job_type": "video",
            "provider": "heygen",
            "status": "disabled",
            "error_message": "HeyGen video generation is disabled until credentials are configured.",
            "result_asset_ids": [video_asset.data[0]["id"]],
            "metadata": {"needs_credentials": True},
            "completed_at": _now_iso(),
        }
    ).execute()
    if not job.data:
        raise HTTPException(status_code=500, detail="Failed to create disabled video job")
    return _job_response(job.data[0], video_asset.data)


def get_job(business_id: str, job_id: str) -> MarketingGenerationJobResponse:
    job = _get_single("marketing_generation_jobs", job_id, business_id)
    result_assets = []
    if job.get("result_asset_ids"):
        result_assets = (
            supabase_admin.table("marketing_assets")
            .select("*")
            .eq("business_id", business_id)
            .in_("id", job["result_asset_ids"])
            .execute()
            .data
            or []
        )
    elif job.get("asset_id"):
        result_assets = (
            supabase_admin.table("marketing_assets")
            .select("*")
            .eq("business_id", business_id)
            .eq("id", job["asset_id"])
            .execute()
            .data
            or []
        )

    return _job_response(job, result_assets)


def list_campaign_assets(business_id: str, campaign_id: str) -> list[MarketingAssetResponse]:
    _get_single("marketing_campaigns", campaign_id, business_id)
    assets = (
        supabase_admin.table("marketing_assets")
        .select("*")
        .eq("business_id", business_id)
        .eq("campaign_id", campaign_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    return [_asset_response(asset, _signed_asset_url(asset)) for asset in assets]


def get_asset_signed_url(business_id: str, asset_id: str) -> tuple[str, int]:
    asset = _get_single("marketing_assets", asset_id, business_id)
    signed_url = _signed_asset_url(asset)
    if not signed_url:
        raise HTTPException(status_code=404, detail="Asset does not have a generated media file yet")
    return signed_url, SIGNED_URL_TTL_SECONDS


def create_scheduled_post(
    business_id: str,
    user_id: str,
    body: MarketingScheduledPostCreateRequest,
) -> MarketingScheduledPostResponse:
    asset = _get_single("marketing_assets", body.asset_id, business_id)
    _get_single("marketing_campaigns", body.campaign_id, business_id)
    row = {
        "business_id": business_id,
        "campaign_id": body.campaign_id,
        "asset_id": body.asset_id,
        "created_by": user_id,
        "caption": body.caption,
        "platforms": body.platforms,
        "status": "scheduled",
        "scheduled_for": body.scheduled_for or _next_calendar_slot(business_id),
        "metadata": {"publishing_deferred": True},
    }
    result = supabase_admin.table("marketing_scheduled_posts").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to schedule marketing post")
    return _scheduled_post_response(result.data[0], asset)


def delete_scheduled_post(business_id: str, scheduled_post_id: str) -> MarketingScheduledPostResponse:
    post = _get_single("marketing_scheduled_posts", scheduled_post_id, business_id)
    result = (
        supabase_admin.table("marketing_scheduled_posts")
        .delete()
        .eq("id", scheduled_post_id)
        .eq("business_id", business_id)
        .execute()
    )
    if result.data is None:
        raise HTTPException(status_code=500, detail="Failed to delete scheduled marketing post")
    return _scheduled_post_response(post)


def list_calendar_posts(business_id: str) -> list[MarketingScheduledPostResponse]:
    posts = (
        supabase_admin.table("marketing_scheduled_posts")
        .select("*")
        .eq("business_id", business_id)
        .order("scheduled_for", desc=False)
        .execute()
        .data
        or []
    )
    asset_ids = [post["asset_id"] for post in posts]
    assets_by_id: dict[str, dict[str, Any]] = {}
    if asset_ids:
        assets = (
            supabase_admin.table("marketing_assets")
            .select("*")
            .eq("business_id", business_id)
            .in_("id", asset_ids)
            .execute()
            .data
            or []
        )
        assets_by_id = {asset["id"]: asset for asset in assets}

    return [_scheduled_post_response(post, assets_by_id.get(post["asset_id"])) for post in posts]


def randomize_idea() -> str:
    index = datetime.now(timezone.utc).second % len(_RANDOM_IDEAS)
    return _RANDOM_IDEAS[index]
