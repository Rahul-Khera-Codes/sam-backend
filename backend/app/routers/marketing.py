"""Marketing Employee router."""
from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.auth import get_user_id, verify_business_access
from app.schemas.marketing import (
    MarketingAssetResponse,
    MarketingCampaignCreateRequest,
    MarketingCampaignResponse,
    MarketingGenerationJobResponse,
    MarketingImageGenerationRequest,
    MarketingScheduledPostCreateRequest,
    MarketingScheduledPostResponse,
    MarketingSignedUrlResponse,
    MarketingVideoGenerationRequest,
    MarketingWorkspaceResponse,
    RandomIdeaResponse,
)
from app.services.marketing_generation_service import (
    create_campaign,
    create_scheduled_post,
    delete_scheduled_post,
    get_asset_signed_url,
    get_job,
    get_workspace,
    list_calendar_posts,
    list_campaign_assets,
    randomize_idea,
    run_concepts_job,
    run_image_job,
    start_concepts_job,
    start_image_job,
    start_video_job_disabled,
)

router = APIRouter(prefix="/marketing", tags=["marketing"])


@router.get("/workspace", response_model=MarketingWorkspaceResponse)
async def get_marketing_workspace(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return MarketingWorkspaceResponse(**get_workspace(business_id))


@router.post("/campaigns", response_model=MarketingCampaignResponse)
async def create_marketing_campaign(
    body: MarketingCampaignCreateRequest,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return create_campaign(business_id, user_id, body)


@router.post("/campaigns/{campaign_id}/concepts", response_model=MarketingGenerationJobResponse)
async def generate_marketing_concepts(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    job = start_concepts_job(business_id, campaign_id)
    background_tasks.add_task(run_concepts_job, job.id, business_id)
    return job


@router.get("/campaigns/{campaign_id}/assets", response_model=list[MarketingAssetResponse])
async def get_marketing_campaign_assets(
    campaign_id: str,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return list_campaign_assets(business_id, campaign_id)


@router.post("/assets/{asset_id}/image", response_model=MarketingGenerationJobResponse)
async def generate_marketing_asset_image(
    asset_id: str,
    body: MarketingImageGenerationRequest,
    background_tasks: BackgroundTasks,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    job = start_image_job(business_id, asset_id, body.confirm_cost)
    background_tasks.add_task(run_image_job, job.id, business_id)
    return job


@router.post("/assets/{asset_id}/video", response_model=MarketingGenerationJobResponse)
async def generate_marketing_asset_video(
    asset_id: str,
    body: MarketingVideoGenerationRequest,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return start_video_job_disabled(business_id, asset_id, body.confirm_cost)


@router.get("/jobs/{job_id}", response_model=MarketingGenerationJobResponse)
async def get_marketing_generation_job(
    job_id: str,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return get_job(business_id, job_id)


@router.get("/assets/{asset_id}/signed-url", response_model=MarketingSignedUrlResponse)
async def get_marketing_asset_signed_url(
    asset_id: str,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    signed_url, expires_in = get_asset_signed_url(business_id, asset_id)
    return MarketingSignedUrlResponse(asset_id=asset_id, signed_url=signed_url, expires_in=expires_in)


@router.post("/scheduled-posts", response_model=MarketingScheduledPostResponse)
async def create_marketing_scheduled_post(
    body: MarketingScheduledPostCreateRequest,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return create_scheduled_post(business_id, user_id, body)


@router.get("/calendar", response_model=list[MarketingScheduledPostResponse])
async def get_marketing_calendar(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return list_calendar_posts(business_id)


@router.delete("/scheduled-posts/{scheduled_post_id}", response_model=MarketingScheduledPostResponse)
async def delete_marketing_scheduled_post(
    scheduled_post_id: str,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return delete_scheduled_post(business_id, scheduled_post_id)


@router.post("/campaigns/randomize", response_model=RandomIdeaResponse)
async def randomize_marketing_campaign_idea(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return RandomIdeaResponse(idea=randomize_idea())
