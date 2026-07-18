from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 이 파일(config.py)에서 4단계 위로 올라가면 레포 루트의 .env 위치
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # DB
    app_db_url: str = "postgresql+psycopg://contest_helper:contest_helper@localhost:5432/contest_helper"
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

    # 프론트엔드 URL (OAuth 콜백 후 리다이렉트)
    frontend_url: str = "http://localhost:5173"

    # 관측(보너스)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # 개발용 OAuth 우회 (절대 프로덕션에서 사용 금지)
    dev_bypass_auth: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
