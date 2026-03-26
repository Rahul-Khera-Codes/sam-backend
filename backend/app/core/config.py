from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


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

    # App
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:8081"

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
