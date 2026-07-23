# =============================================================================
# worker.Dockerfile — contest-helper의 agent-worker(백그라운드 루프) 이미지
# =============================================================================
# 이 파일이 무엇인가:
#   - services/worker 를 컨테이너로 만든다.
#   - worker 는 "포트가 없다". 웹 요청을 받지 않고, Redis 큐를 계속 꺼내(BRPOP)
#     LLM 추천을 생성하는 무한 루프(python -m worker.main)를 돈다.
#
# ★ api.Dockerfile 과 똑같은 "워크스페이스 인식" 패턴을 쓴다 ★
#   worker 도 libs/contest_helper_core 에 의존하므로, 빌드 컨텍스트 = 레포 루트.
#       docker build -f deploy/docker/worker.Dockerfile -t contest-helper-worker .
# =============================================================================

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    # worker 소스/공유 lib 경로를 PYTHONPATH 에 명시(안전망).
    PYTHONPATH=/app/services/worker/src:/app/libs/contest_helper_core/src

# uv 정적 바이너리 복사.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 워크스페이스 인식 복사: 루트 pyproject + 공유 lib + worker 서비스.
#   (api 와 동일한 이유 — uv workspace 가 contest-helper-core 를 로컬 멤버로 풀어야 함)
COPY pyproject.toml ./
COPY libs/contest_helper_core/ libs/contest_helper_core/
COPY services/worker/ services/worker/

# 의존성 설치. uv.lock 이 커밋돼 있으므로 --frozen 으로 재현 가능한 빌드를 보장한다.
RUN uv sync --frozen --no-dev --package contest-helper-worker

# worker 패키지 루트에서 실행(작업 디렉터리 정리 목적).
WORKDIR /app/services/worker

# ----- 컨테이너 시작 명령 -----
# worker.main 의 main() → run_loop() 가 Redis 큐를 무한 소비한다.
# (포트 EXPOSE 없음: 외부에서 접속하는 서비스가 아님)
CMD ["uv", "run", "--no-dev", "--package", "contest-helper-worker", "python", "-m", "worker.main"]
