# 마일스톤 1: Foundation API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로컬에서 도커로 띄우면 Postgres에 연결되고 `/health`와 `/competitions`(기존 공모전 DB 읽기)가 응답하는, 테스트 통과하는 최소 FastAPI 서비스를 만든다.

**Architecture:** Python/FastAPI 모듈러 모놀리식의 첫 골격. App DB(쓰기, Postgres+pgvector)와 공모전 DB(읽기 전용)를 별도 SQLAlchemy 엔진으로 분리한다. 외부 의존성은 FastAPI dependency injection으로 주입해 테스트를 hermetic하게 유지한다.

**Tech Stack:** Python 3.12, uv(패키지/가상환경), FastAPI, uvicorn, SQLAlchemy 2.0(sync) + psycopg3, Alembic(마이그레이션), pydantic-settings, pytest + httpx, ruff(린트), Docker + docker-compose(pgvector/pgvector:pg16).

## Global Constraints

- Python 3.12, 패키지 관리는 `uv` 사용 (`uv add`, `uv run`).
- DB 접근은 SQLAlchemy 2.0 스타일(`Session`, `select()`). raw 문자열 SQL은 공모전 DB 읽기 등 불가피한 경우만, 반드시 파라미터 바인딩.
- App DB와 공모전 DB는 **절대 같은 엔진/세션을 공유하지 않는다**. 공모전 DB는 읽기 전용.
- 모든 설정값(DB URL 등)은 코드에 하드코딩 금지 → 환경변수 + `pydantic-settings`.
- 각 Task는 실패하는 테스트 → 최소 구현 → 통과 → 커밋 순서(TDD).
- 커밋 메시지는 Conventional Commits(`feat:`, `chore:`, `test:` 등).

---

### Task 1: 레포 스캐폴드 + 헬스 엔드포인트

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/app/__init__.py`, `src/app/main.py`
- Test: `tests/test_health.py`
- Create: `.github/workflows/ci.yml` (테스트 자동 실행 골격)

**Interfaces:**
- Produces: `app = FastAPI()` 객체 (`src/app/main.py`의 모듈 전역 `app`), `GET /health` → `{"status": "ok"}`

- [ ] **Step 1: git 초기화 + uv 프로젝트 생성**

```bash
cd /Users/rental_mac_01/Desktop/keenee
git init
uv init --name keenee --python 3.12 --no-workspace
uv add fastapi uvicorn[standard]
uv add --dev pytest httpx ruff
mkdir -p src/app tests
```

- [ ] **Step 2: `.gitignore` 작성**

```gitignore
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 3: 실패하는 테스트 작성** — `tests/test_health.py`

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 4: 테스트 실패 확인**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` 또는 import 에러.

- [ ] **Step 5: 최소 구현** — `src/app/__init__.py`(빈 파일) + `src/app/main.py`

```python
from fastapi import FastAPI

app = FastAPI(title="keenee")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

`pyproject.toml`에 src 레이아웃 인식을 위해 pytest 설정 추가:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `uv run pytest tests/test_health.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: CI 골격 작성** — `.github/workflows/ci.yml`

```yaml
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.12"
      - run: uv sync --dev
      - run: uv run ruff check .
      - run: uv run pytest -v
```

- [ ] **Step 8: 커밋**

```bash
git add -A
git commit -m "feat: scaffold FastAPI app with health endpoint and CI skeleton"
```

---

### Task 2: 설정(Settings) 로딩

**Files:**
- Create: `src/app/config.py`, `.env.example`
- Modify: `src/app/main.py` (settings 사용)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings 클래스), `get_settings() -> Settings` (lru_cache). 필드: `app_db_url: str`, `competition_db_url: str`, `gemini_api_key: str = ""`.

- [ ] **Step 1: 의존성 추가**

```bash
uv add pydantic-settings
```

- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_config.py`

```python
import os
from app.config import Settings

def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("APP_DB_URL", "postgresql+psycopg://u:p@localhost/app")
    monkeypatch.setenv("COMPETITION_DB_URL", "postgresql+psycopg://u:p@localhost/comp")
    s = Settings()
    assert s.app_db_url == "postgresql+psycopg://u:p@localhost/app"
    assert s.competition_db_url == "postgresql+psycopg://u:p@localhost/comp"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 4: 최소 구현** — `src/app/config.py`

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_db_url: str = ""
    competition_db_url: str = ""
    gemini_api_key: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: `.env.example` 작성**

```dotenv
APP_DB_URL=postgresql+psycopg://keenee:keenee@localhost:5432/keenee
COMPETITION_DB_URL=postgresql+psycopg://readonly:pw@HOST:5432/competition
GEMINI_API_KEY=
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "feat: add pydantic settings loaded from environment"
```

---

### Task 3: App DB 엔진 + users 모델 + 마이그레이션

**Files:**
- Create: `src/app/db.py`, `src/app/models.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_create_users.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 2)
- Produces:
  - `app_engine` (App DB SQLAlchemy Engine), `AppSession` (sessionmaker), `get_app_session()` (FastAPI 의존성, `Session` yield)
  - `Base` (DeclarativeBase), `User` 모델 — 컬럼: `id:int PK`, `email:str unique`, `name:str`, `interests:list[str]`(JSON), `created_at:datetime`

- [ ] **Step 1: 의존성 추가**

```bash
uv add "sqlalchemy>=2.0" psycopg alembic
```

- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_models.py` (SQLite in-memory로 모델 검증)

```python
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Base, User

def test_user_can_be_created_and_queried():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(email="a@b.com", name="A", interests=["ai", "data"]))
        s.commit()
        got = s.scalar(select(User).where(User.email == "a@b.com"))
        assert got is not None
        assert got.interests == ["ai", "data"]
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 4: 모델 구현** — `src/app/models.py`

```python
from datetime import datetime
from sqlalchemy import String, JSON, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 6: DB 엔진/세션 구현** — `src/app/db.py`

```python
from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.config import get_settings

settings = get_settings()

app_engine = create_engine(settings.app_db_url, pool_pre_ping=True)
AppSession = sessionmaker(bind=app_engine, class_=Session, expire_on_commit=False)

def get_app_session() -> Iterator[Session]:
    with AppSession() as session:
        yield session
```

- [ ] **Step 7: Alembic 초기화 + users 마이그레이션 작성**

```bash
uv run alembic init migrations
```

`migrations/env.py`에서 `target_metadata = Base.metadata` 로 연결하고 URL을 settings에서 읽도록 수정한 뒤, 첫 마이그레이션 생성:

```bash
uv run alembic revision -m "create users" --rev-id 0001
```

`migrations/versions/0001_create_users.py`의 `upgrade()`:

```python
import sqlalchemy as sa
from alembic import op

def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("interests", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table("users")
```

- [ ] **Step 8: 커밋**

```bash
git add -A
git commit -m "feat: add app db engine, User model and initial migration"
```

---

### Task 4: 공모전 DB 읽기 + `/competitions` 엔드포인트

**Files:**
- Create: `src/app/competitions/__init__.py`, `src/app/competitions/repository.py`, `src/app/competitions/router.py`, `src/app/competition_db.py`
- Modify: `src/app/main.py` (라우터 등록)
- Test: `tests/test_competitions.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 2)
- Produces:
  - `Competition` (pydantic 모델): `id:int`, `title:str`, `deadline:date | None`, `organizer:str | None`, `url:str | None`
  - `CompetitionRepository` 프로토콜: `list_open(limit:int) -> list[Competition]`
  - `SqlCompetitionRepository` (실제 공모전 DB 조회 구현)
  - `get_competition_repo()` FastAPI 의존성
  - `GET /competitions?limit=20` → `list[Competition]` JSON

> **참고:** 실제 공모전 DB 테이블/컬럼명은 접속 정보 보유자가 안다. 아래 SQL의 테이블명 `competitions`와 컬럼명은 **실제 스키마에 맞게 Step 5에서 치환**한다. 테스트(Step 2~4)는 가짜 repo로 hermetic하게 통과하므로 실제 DB 없이도 검증된다.

- [ ] **Step 1: 가짜 repo로 엔드포인트 동작을 검증하는 실패 테스트 작성** — `tests/test_competitions.py`

```python
from datetime import date
from fastapi.testclient import TestClient
from app.main import app
from app.competitions.repository import Competition, get_competition_repo

class FakeRepo:
    def list_open(self, limit: int) -> list[Competition]:
        return [Competition(id=1, title="AI 공모전", deadline=date(2026, 12, 31),
                            organizer="GC", url="http://x")][:limit]

def test_list_competitions_returns_items():
    app.dependency_overrides[get_competition_repo] = lambda: FakeRepo()
    client = TestClient(app)
    resp = client.get("/competitions?limit=5")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "AI 공모전"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_competitions.py -v`
Expected: FAIL — `app.competitions` 모듈 없음.

- [ ] **Step 3: 공모전 DB 엔진 구현** — `src/app/competition_db.py`

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.config import get_settings

settings = get_settings()

# 읽기 전용 소스. App DB와 분리된 엔진.
competition_engine = create_engine(settings.competition_db_url, pool_pre_ping=True)
CompetitionSession = sessionmaker(bind=competition_engine, class_=Session, expire_on_commit=False)
```

- [ ] **Step 4: repository 구현** — `src/app/competitions/repository.py`

```python
from datetime import date
from typing import Protocol
from pydantic import BaseModel
from sqlalchemy import text
from app.competition_db import CompetitionSession

class Competition(BaseModel):
    id: int
    title: str
    deadline: date | None = None
    organizer: str | None = None
    url: str | None = None

class CompetitionRepository(Protocol):
    def list_open(self, limit: int) -> list[Competition]: ...

class SqlCompetitionRepository:
    def list_open(self, limit: int) -> list[Competition]:
        # NOTE: 테이블/컬럼명은 실제 공모전 DB 스키마에 맞게 치환.
        sql = text(
            "SELECT id, title, deadline, organizer, url "
            "FROM competitions "
            "WHERE deadline IS NULL OR deadline >= CURRENT_DATE "
            "ORDER BY deadline ASC NULLS LAST "
            "LIMIT :limit"
        )
        with CompetitionSession() as s:
            rows = s.execute(sql, {"limit": limit}).mappings().all()
        return [Competition(**dict(r)) for r in rows]

def get_competition_repo() -> CompetitionRepository:
    return SqlCompetitionRepository()
```

`src/app/competitions/__init__.py`는 빈 파일.

- [ ] **Step 5: 라우터 구현** — `src/app/competitions/router.py`

```python
from fastapi import APIRouter, Depends, Query
from app.competitions.repository import Competition, CompetitionRepository, get_competition_repo

router = APIRouter(prefix="/competitions", tags=["competitions"])

@router.get("", response_model=list[Competition])
def list_competitions(
    limit: int = Query(20, ge=1, le=100),
    repo: CompetitionRepository = Depends(get_competition_repo),
) -> list[Competition]:
    return repo.list_open(limit)
```

- [ ] **Step 6: 라우터 등록** — `src/app/main.py` 수정

```python
from fastapi import FastAPI
from app.competitions.router import router as competitions_router

app = FastAPI(title="keenee")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

app.include_router(competitions_router)
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `uv run pytest tests/test_competitions.py -v`
Expected: PASS

- [ ] **Step 8: 실제 공모전 DB 스키마 반영 + 수동 확인**

실제 접속정보를 `.env`에 넣고 Step 4의 SQL 테이블/컬럼명을 실제 스키마에 맞게 수정한 뒤 수동 검증:

Run: `uv run uvicorn app.main:app --reload` 후 다른 터미널에서 `curl "localhost:8000/competitions?limit=3"`
Expected: 실제 공모전 3건 JSON 반환.

- [ ] **Step 9: 커밋**

```bash
git add -A
git commit -m "feat: add read-only competition repository and /competitions endpoint"
```

---

### Task 5: 로컬 도커 실행 (Dockerfile + docker-compose)

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Modify: `README.md` (로컬 실행법)

**Interfaces:**
- Produces: `docker compose up`으로 app(8000) + pgvector Postgres(5432)가 뜨고, App DB 마이그레이션이 적용된 상태.

- [ ] **Step 1: `.dockerignore` 작성**

```dockerignore
.venv
__pycache__
.git
.pytest_cache
.ruff_cache
*.md
```

- [ ] **Step 2: `Dockerfile` 작성**

```dockerfile
FROM python:3.12-slim
WORKDIR /code
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
ENV PYTHONPATH=/code/src
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: `docker-compose.yml` 작성** (앱 + pgvector Postgres)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: keenee
      POSTGRES_PASSWORD: keenee
      POSTGRES_DB: keenee
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U keenee"]
      interval: 5s
      retries: 5

  api:
    build: .
    depends_on:
      db:
        condition: service_healthy
    environment:
      APP_DB_URL: postgresql+psycopg://keenee:keenee@db:5432/keenee
      COMPETITION_DB_URL: ${COMPETITION_DB_URL}
      GEMINI_API_KEY: ${GEMINI_API_KEY:-}
    ports: ["8000:8000"]
    command: >
      sh -c "uv run alembic upgrade head &&
             uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

- [ ] **Step 4: 빌드 및 기동 확인**

Run: `COMPETITION_DB_URL=<실제값> docker compose up --build`
Expected: db healthy → api가 `alembic upgrade head`로 users 테이블 생성 → uvicorn 기동.

- [ ] **Step 5: 헬스/엔드포인트 수동 확인**

Run: `curl localhost:8000/health` → `{"status":"ok"}`
Run: `curl "localhost:8000/competitions?limit=3"` → 공모전 JSON

- [ ] **Step 6: README에 실행법 작성** — `README.md`

```markdown
# keenee
공모전 추천 에이전트 (MLOps 학습 프로젝트).

## 로컬 실행
1. `.env.example`를 `.env`로 복사하고 `COMPETITION_DB_URL` 채우기
2. `docker compose up --build`
3. http://localhost:8000/health , http://localhost:8000/competitions

## 테스트
`uv run pytest -v`
```

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "feat: containerize app with docker-compose and pgvector postgres"
```

---

## 마일스톤 1 완료 기준 (Definition of Done)

- `uv run pytest -v` 전부 통과.
- `docker compose up --build`로 app+db 기동, `/health`·`/competitions` 응답.
- users 테이블이 마이그레이션으로 생성됨.
- App DB / 공모전 DB 엔진이 분리되어 있음.

## 다음 마일스톤 (별도 plan으로 작성 예정)

- **M2 — 추천 에이전트:** 구글 OAuth + 관심사, Redis 큐, `agent-worker` + `mcp-server`(MCP 도구), pgvector RAG + Gemini 추천, 최소 워크스페이스.
- **M3 — 클라우드/관측:** 로컬 kind + Helm → GitHub Actions 배포 → Terraform/GKE → Grafana + Langfuse.
