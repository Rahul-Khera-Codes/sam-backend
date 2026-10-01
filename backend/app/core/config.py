from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # OpenAI
    openai_api_key: str
    marketing_text_model: str = "gpt-4o-mini"
    marketing_image_model: str = "gpt-image-1"
    marketing_x_client_id: str = ""
    marketing_x_client_secret: str = ""
    marketing_x_redirect_uri: str = "http://localhost:8080/integrations/marketing/x/callback"
    marketing_x_redirect_uri_local: str = "http://localhost:8080/integrations/marketing/x/callback"
    marketing_x_redirect_uri_production: str = ""
    marketing_meta_app_id: str = ""
    marketing_meta_app_secret: str = ""
    marketing_meta_redirect_uri: str = "http://localhost:8080/integrations/marketing/instagram/callback"
    marketing_meta_redirect_uri_local: str = "http://localhost:8080/integrations/marketing/instagram/callback"
    marketing_meta_redirect_uri_production: str = ""
    marketing_instagram_app_id: str = ""
    marketing_instagram_app_secret: str = ""
    marketing_instagram_redirect_uri_local: str = ""
    marketing_instagram_redirect_uri_production: str = ""
    marketing_token_encryption_key: str = ""

    # LinkedIn — built against LinkedIn's documented OAuth + Posts API, but unverified:
    # no LinkedIn Developer app exists yet, so exact scope/product names may need adjustment
    # once one is created. See docs/features/marketing_platform_integrations.md.
    marketing_linkedin_client_id: str = ""
    marketing_linkedin_client_secret: str = ""
    marketing_linkedin_redirect_uri_local: str = "http://localhost:8080/integrations/marketing/linkedin/callback"
    marketing_linkedin_redirect_uri_production: str = ""
    # LinkedIn-Version header (YYYYMM) — bump via env once the real app is live and tested
    # against whatever version is current then; no code change needed.
    marketing_linkedin_api_version: str = "202502"

    # AWS S3 (optional)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket_name: str = ""

    # Google OAuth (shared client_id/secret for Calendar + Gmail integrations)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:5173/integrations/google/callback"
    gmail_redirect_uri: str = "http://localhost:5173/integrations/gmail/callback"

    # Microsoft OAuth (Outlook email integration — Azure AD app "AI Employees - Outlook Integration")
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    outlook_redirect_uri: str = "https://portal.aiemployeesinc.com/integrations/outlook/callback"

    # Twilio / SIP
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_trunk_sid: str = ""
    livekit_sip_inbound_trunk_id: str = ""
    livekit_sip_host: str = ""  # from LiveKit Cloud dashboard → Project Settings → SIP URI
    agent_name: str = "ai-employee-agent"
    sip_auth_username: str = ""
    sip_auth_password: str = ""
    twilio_term_sip_username: str = ""
    twilio_term_sip_password: str = ""
    twilio_term_domain: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_starter_price_id: str = ""
    stripe_growth_price_id: str = ""
    stripe_enterprise_price_id: str = ""
    stripe_exec_agent_price_id: str = ""
    # Free during beta — flip on once Sam names a price and is ready to enforce.
    # See docs/adr/0001-billing-addon-access-gating.md
    exec_agent_addon_enforced: bool = False
    # Minute caps per plan — tunable via .env without a code change/redeploy.
    # Mirrors the price-id-via-settings pattern above. See docs/features/billing-pricing-page.md.
    plan_starter_minute_limit: int = 800
    plan_growth_minute_limit: int = 1500
    # None = unlimited — Enterprise has no hard cap, distinct from "not configured" (which
    # would be 0 on the other plans). _plan_by_price_id/get_subscription pass this through as-is.
    plan_enterprise_minute_limit: Optional[int] = None
    plan_trial_minute_limit: int = 60
    trial_period_days: int = 14
    # Days a past_due subscription gets before gated dashboard actions
    # (Marketing/Sales/HR — see billing_gate.py) start blocking. Phone calls
    # are never gated, regardless of this setting.
    subscription_grace_period_days: int = 5

    # PLAN_ENTERPRISE_MINUTE_LIMIT="" in .env (set but left blank, meaning
    # "use the default unlimited") would otherwise fail int parsing — pydantic
    # only applies the None default when the var is absent entirely, not when
    # it's present-but-empty. Treat blank the same as absent.
    @field_validator("plan_enterprise_minute_limit", mode="before")
    @classmethod
    def _blank_means_unset(cls, v):
        return None if v == "" else v
    
    billing_success_url: str = "http://localhost:8080/dashboard/settings/billing?success=true"
    billing_cancel_url: str = "http://localhost:8080/dashboard/settings/billing"

    # Apify (Sales Employee — Lead Researcher + Competitor Agent)
    apify_api_token: str = ""
    apify_webhook_base_url: str = ""  # public backend URL Apify calls on run completion — set in prod, use ngrok for local testing
    apify_webhook_secret: str = ""  # random string, checked on inbound webhook calls so randoms can't spoof "run finished" events

    # YouTube Data API v3 (Sales Employee — Competitor Agent). Plain API key, not
    # OAuth — separate from the google_client_id/secret above, which are for
    # Calendar/Gmail. Enable "YouTube Data API v3" on the same Google Cloud project.
    youtube_api_key: str = ""

    # Exa.ai (Sales Employee — Market Agent). Sent via x-api-key header, not Authorization.
    exa_api_key: str = ""

    # Resend (Support + Wish List transactional email — fixed platform sender, not per-business)
    resend_api_key: str = ""

    # App
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:8081,http://localhost:8080"
    valkey_url: str = "redis://localhost:6379/0"
    hr_onboarding_cache_enabled: bool = True
    hr_onboarding_cache_ttl_seconds: int = 3600
    hr_onboarding_cache_client_name: str = "hr-onboarding-backend"
    hr_onboarding_semantic_cache_enabled: bool = True
    hr_onboarding_semantic_cache_similarity_threshold: float = 0.985
    hr_onboarding_semantic_cache_max_entries: int = 32
    hr_onboarding_validation_cache_enabled: bool = True
    hr_onboarding_validation_cache_ttl_seconds: int = 3600

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    
    use_livekit_agent: bool = Field(
        default=True,
        alias="USE_LIVEKIT_AGENT",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # or keep existing settings but remove 'extra="forbid"' if present
    )

    # class Config:
    #     env_file = ".env"
    #     case_sensitive = False


settings = Settings()
