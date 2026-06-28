"""구글 OAuth 2.0 Authorization Code 플로우 (authlib 사용).

네트워크 호출은 콜백 처리 시점에만 일어난다. 단위 테스트는 이 모듈을
의존성/직접 호출 대신 우회(인증 자체는 통합 시나리오)하므로 hermetic 하다.
"""

from __future__ import annotations

from authlib.integrations.httpx_client import OAuth2Client

from contest_helper_core.config import get_settings

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email profile"


def _client() -> OAuth2Client:
    s = get_settings()
    return OAuth2Client(
        client_id=s.google_oauth_client_id,
        client_secret=s.google_oauth_client_secret,
        redirect_uri=s.google_oauth_redirect_uri,
        scope=SCOPE,
    )


def build_authorization_url(state: str) -> str:
    """동의 화면으로 보낼 authorization URL 생성. state 로 CSRF 방지."""
    uri, _ = _client().create_authorization_url(
        GOOGLE_AUTH_ENDPOINT,
        state=state,
        access_type="offline",
        prompt="consent",
    )
    return uri


def exchange_code(code: str) -> dict:
    """authorization code 를 access token 으로 교환."""
    client = _client()
    return client.fetch_token(
        GOOGLE_TOKEN_ENDPOINT,
        code=code,
        grant_type="authorization_code",
    )


def fetch_userinfo(token: dict) -> dict:
    """access token 으로 사용자 프로필(email, name 등) 조회."""
    client = _client()
    client.token = token
    resp = client.get(GOOGLE_USERINFO_ENDPOINT)
    resp.raise_for_status()
    return resp.json()
