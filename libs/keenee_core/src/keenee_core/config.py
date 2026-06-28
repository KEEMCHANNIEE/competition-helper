from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DB
    app_db_url: str = "postgresql+psycopg://keenee:keenee@localhost:5432/keenee"
    competition_db_url: str = ""

    # 큐
    redis_url: str = "redis://localhost:6379/0"

    # LLM (둘 중 한 경로)
    gemini_api_key: str = ""
    google_cloud_project: str = ""
    vertex_location: str = "us-central1"

    # 구글 OAuth
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    session_secret: str = "dev-secret-change-me"

    # 관측(보너스)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
