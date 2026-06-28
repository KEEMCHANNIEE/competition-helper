"""FastAPI 앱 진입점: /health + 모듈 라우터 등록."""

from __future__ import annotations

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.competitions.router import router as competitions_router
from app.recommend.router import router as recommend_router
from app.workspaces.router import router as workspaces_router


def create_app() -> FastAPI:
    app = FastAPI(title="keenee api", version="0.0.0")

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(competitions_router)
    app.include_router(recommend_router)
    app.include_router(workspaces_router)
    return app


app = create_app()
