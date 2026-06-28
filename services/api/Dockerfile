# NOTE: 배포 담당 에이전트가 정식(canonical) Dockerfile 을 소유한다.
# 이 파일은 동작하는 최소 버전이며, build context = 레포 루트(contest-helper/) 기준이다.
#   docker build -f services/api/Dockerfile -t contest-helper-api .
#
# 멀티스테이지: uv 로 의존성 동기화 후 uvicorn 으로 기동.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

# uv 설치(정적 바이너리 복사).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 워크스페이스 구성: 루트 + 공유 lib + api 서비스.
COPY pyproject.toml ./
COPY libs/contest_helper_core/ libs/contest_helper_core/
COPY services/api/ services/api/

# api 서비스와 그 워크스페이스 의존성(contest-helper-core) 설치(개발 의존성 제외).
RUN uv sync --no-dev --package contest-helper-api

EXPOSE 8000

# 기동 전 마이그레이션 적용 후 uvicorn. (compose/helm 에서 override 가능)
WORKDIR /app/services/api
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
