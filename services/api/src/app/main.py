"""FastAPI 앱 진입점: /health + 모듈 라우터 등록."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from contest_helper_core.config import get_settings

from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.competitions.router import router as competitions_router
from app.recommend.router import router as recommend_router
from app.workspaces.router import router as workspaces_router


def create_app() -> FastAPI:
    app = FastAPI(title="contest-helper api", version="0.0.0")

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(competitions_router)
    app.include_router(recommend_router)
    app.include_router(workspaces_router)
    app.include_router(chat_router)
    return app


app = create_app()
