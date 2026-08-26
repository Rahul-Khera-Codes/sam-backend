"""Marketing platform integrations for Instagram and X."""

from fastapi import APIRouter, Depends, Query, Request

from app.core.auth import get_user_id, verify_business_access
from app.schemas.marketing import (
    MarketingIntegrationStatusResponse,
    MarketingIntegrationsStatusResponse,
    MarketingOAuthCallbackRequest,
    MarketingOAuthUrlResponse,
    TikTokCreatorInfoResponse,
)
from app.services.marketing_social_service import (
    build_instagram_auth_url,
    build_linkedin_auth_url,
    build_tiktok_auth_url,
    build_x_auth_url,
    complete_instagram_oauth,
    complete_linkedin_oauth,
    complete_tiktok_oauth,
    complete_x_oauth,
    disconnect_marketing_integration,
    get_marketing_integrations_status,
    get_tiktok_creator_info,
)

router = APIRouter(prefix="/integrations/marketing", tags=["marketing-integrations"])


@router.get("/status", response_model=MarketingIntegrationsStatusResponse)
async def get_marketing_integrations_status_route(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return get_marketing_integrations_status(business_id)


@router.get("/x/auth-url", response_model=MarketingOAuthUrlResponse)
async def get_x_auth_url(
    request: Request,
    business_id: str = Query(...),
    return_to: str = Query("/dashboard/settings/business?tab=integrations"),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return MarketingOAuthUrlResponse(url=build_x_auth_url(business_id, user_id, return_to, request.headers.get("origin")))


@router.post("/x/callback", response_model=MarketingIntegrationStatusResponse)
async def complete_x_callback(
    body: MarketingOAuthCallbackRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await complete_x_oauth(body.code, body.state, body.business_id)


@router.get("/instagram/auth-url", response_model=MarketingOAuthUrlResponse)
async def get_instagram_auth_url(
    request: Request,
    business_id: str = Query(...),
    return_to: str = Query("/dashboard/settings/business?tab=integrations"),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return MarketingOAuthUrlResponse(url=build_instagram_auth_url(business_id, user_id, return_to, request.headers.get("origin")))


@router.post("/instagram/callback", response_model=MarketingIntegrationStatusResponse)
async def complete_instagram_callback(
    body: MarketingOAuthCallbackRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await complete_instagram_oauth(body.code, body.state, body.business_id)


@router.get("/tiktok/auth-url", response_model=MarketingOAuthUrlResponse)
async def get_tiktok_auth_url(
    request: Request,
    business_id: str = Query(...),
    return_to: str = Query("/dashboard/settings/business?tab=integrations"),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return MarketingOAuthUrlResponse(url=build_tiktok_auth_url(business_id, user_id, return_to, request.headers.get("origin")))


@router.post("/tiktok/callback", response_model=MarketingIntegrationStatusResponse)
async def complete_tiktok_callback(
    body: MarketingOAuthCallbackRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await complete_tiktok_oauth(body.code, body.state, body.business_id)


@router.get("/linkedin/auth-url", response_model=MarketingOAuthUrlResponse)
async def get_linkedin_auth_url(
    request: Request,
    business_id: str = Query(...),
    return_to: str = Query("/dashboard/settings/business?tab=integrations"),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return MarketingOAuthUrlResponse(url=build_linkedin_auth_url(business_id, user_id, return_to, request.headers.get("origin")))


@router.post("/linkedin/callback", response_model=MarketingIntegrationStatusResponse)
async def complete_linkedin_callback(
    body: MarketingOAuthCallbackRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await complete_linkedin_oauth(body.code, body.state, body.business_id)


@router.get("/tiktok/creator-info", response_model=TikTokCreatorInfoResponse)
async def get_tiktok_creator_info_route(
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return await get_tiktok_creator_info(business_id)


@router.delete("/{provider}/disconnect")
async def disconnect_marketing_provider(
    provider: str,
    business_id: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    return await disconnect_marketing_integration(business_id, provider)
