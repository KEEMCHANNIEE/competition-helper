# =============================================================================
# api.Dockerfile — contest-helper의 FastAPI 서버(현관) 이미지
# =============================================================================
# 이 파일이 무엇인가:
#   - services/api (FastAPI, 포트 8000) 를 컨테이너로 만드는 설계도(Dockerfile).
#   - 기동 직전에 `alembic upgrade head` 로 DB 스키마를 최신으로 맞춘 뒤 uvicorn 을 띄운다.
#
# ★★★ 자주 틀리는 부분: "빌드 컨텍스트(build context)" ★★★
#   api 는 uv workspace 멤버라서 공유 라이브러리 libs/contest_helper_core 에 의존한다.
#   따라서 Docker 빌드 컨텍스트는 반드시 "레포 루트(contest-helper/)" 여야 한다.
#   (서비스 폴더 안이 아니라 루트에서 빌드해야 libs/ 를 COPY 할 수 있음)
#
#   올바른 빌드 명령 (레포 루트에서 실행):
#       docker build -f deploy/docker/api.Dockerfile -t contest-helper-api .
#                                                                   ^ 마지막 점(.) = 컨텍스트 = 레포 루트
#   docker-compose 에서는 build.context: .. / dockerfile: docker/api.Dockerfile 로 지정.
# =============================================================================

# ----- 베이스 이미지: 가벼운 파이썬 3.12 (시스템 파이썬 3.9 와 분리) -----
FROM python:3.12-slim AS base

# 파이썬/uv 동작을 컨테이너에 맞게 조정하는 환경변수.
ENV PYTHONUNBUFFERED=1 \
    # ↑ print/로그를 버퍼링 없이 즉시 출력(컨테이너 로그가 바로 보이도록)
    PYTHONDONTWRITEBYTECODE=1 \
    # ↑ .pyc 캐시 파일을 만들지 않음(이미지 깔끔하게)
    UV_LINK_MODE=copy \
    # ↑ uv 가 캐시에서 파일을 하드링크 대신 복사(컨테이너 레이어 경고 방지)
    PYTHONPATH=/app/services/api/src:/app/libs/contest_helper_core/src
    # ↑ 소스 경로를 직접 PYTHONPATH 에 넣어, 설치가 어긋나도 import 가 되도록 안전망.

# ----- uv 설치: 공식 이미지에서 정적 바이너리만 복사(빠르고 안정적) -----
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 작업 디렉터리 = 컨테이너 안의 /app (여기에 레포를 그대로 복사)
WORKDIR /app

# ----- 워크스페이스 인식 복사: 루트 pyproject + 공유 lib + api 서비스 -----
# uv workspace 가 의존성 그래프를 풀려면 이 3개가 모두 필요하다.
#   1) 루트 pyproject.toml  → [tool.uv.workspace] members 정의가 들어있음
#   2) libs/contest_helper_core/    → api 가 의존하는 공유 계약 계층
#   3) services/api/        → 실제 우리가 빌드할 서비스
COPY pyproject.toml ./
COPY libs/contest_helper_core/ libs/contest_helper_core/
COPY services/api/ services/api/

# ----- 의존성 설치 -----
# uv.lock 이 아직 생성되지 않았을 수 있으므로 --frozen 을 쓰지 않는다.
#   --no-dev   : 테스트/린트 같은 개발 의존성 제외(운영 이미지를 가볍게)
#   --package  : 워크스페이스 중 api 패키지(+그 의존 contest-helper-core)만 설치
# ※ 한 번이라도 `uv lock` 을 돌려 uv.lock 을 커밋한 뒤에는,
#   재현 가능한 빌드를 위해 아래 줄을 `uv sync --no-dev --frozen --package contest-helper-api` 로 바꿀 것.
RUN uv sync --no-dev --package contest-helper-api

# FastAPI 가 듣는 포트(문서/메타 용도. 실제 노출은 compose/helm 에서 매핑).
EXPOSE 8000

# alembic.ini 가 services/api 안에 있으므로 그 폴더에서 명령을 실행한다.
WORKDIR /app/services/api

# ----- 컨테이너 시작 명령 -----
# 1) alembic upgrade head : DB 스키마를 최신 리비전까지 적용(테이블 생성/변경)
#    ※ 마이그레이션이 pgvector 를 쓰므로, 첫 마이그레이션에서
#       `CREATE EXTENSION IF NOT EXISTS vector` 를 반드시 수행해야 한다(주의).
# 2) uvicorn app.main:app : 마이그레이션 성공 후에야 API 서버 기동
#    (&& 로 연결 → 마이그레이션 실패 시 서버를 띄우지 않음)
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
