# keenee worker (agent-worker) 이미지.
# 빌드 컨텍스트 = 레포 루트 (uv workspace 가 libs/keenee_core 를 해석해야 하므로).
#   docker build -f services/worker/Dockerfile -t keenee-worker .
FROM python:3.12-slim AS base

# uv 설치 (공식 정적 바이너리 복사).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 워크스페이스 메타데이터 먼저 복사 → 의존성 레이어 캐시 활용.
COPY pyproject.toml uv.lock* ./
COPY libs/keenee_core/pyproject.toml libs/keenee_core/
COPY services/worker/pyproject.toml services/worker/

# 의존성만 먼저 설치(소스 변경 시 재설치 최소화). 락이 없으면 이 단계는 건너뛰어도 됨.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --package keenee-worker --no-install-project || true

# 실제 소스 복사.
COPY libs/keenee_core/ libs/keenee_core/
COPY services/worker/ services/worker/

# 프로젝트 동기화(프로덕션: --no-dev).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --package keenee-worker

# 워커 루프 기동.
CMD ["uv", "run", "--no-dev", "--package", "keenee-worker", "python", "-m", "worker.main"]
