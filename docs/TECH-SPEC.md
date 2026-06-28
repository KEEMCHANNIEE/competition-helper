# keenee — 기술 스펙 & 기능 명세 & 연결 지도 (구현자용 상세 가이드)

- 작성일: 2026-06-28
- 용도: 각 담당자가 **헤매지 않고** 구현할 수 있도록, 기술 스택·정확한 기능·고려사항·연결 관계를 한 장에 명시.
- 같이 볼 문서: `PROJECT-OVERVIEW.md`(구획·과제), `PROJECT-STRUCTURE.md`(폴더·파일 정의)
- 읽는 법: 본인 역할(🟦FE / 🟩BE / 🟨AI) 섹션 + 공통 "데이터 계약"·"환경변수"·"전체 연결도"는 **모두 필독**.

---

## 0. 전체 연결도 (이거 먼저 보기)

```
[🟦 web (React SPA)]
   │  HTTPS (REST, JSON)
   ▼
[🟩 api (FastAPI)] ──read──► [공모전 DB (읽기전용)]
   │  │                       
   │  └──read/write──► [App DB (Postgres + pgvector)]
   │
   │  무거운 AI 요청은 직접 처리 X → 큐에 던짐
   ▼
[Redis 큐]  ◄────────────────────┐
   │ worker가 꺼냄                 │ 결과/상태는 App DB에 기록 (api가 폴링으로 읽음)
   ▼                              │
[🟨 worker (agent-worker)] ───────┘
   │  ├─ MCP 도구 호출 ─► [공모전 DB 읽기 / pgvector 검색]
   │  └─ LLM 호출 ──────► [Gemini (Vertex AI)] + [Langfuse 추적]
   ▼
App DB: agent_jobs(상태) / recommendations(결과) / embeddings(RAG)
```

**핵심 규칙 3개 (어기면 구조 깨짐)**
1. **api는 LLM을 직접 호출하지 않는다.** 무거운 건 무조건 큐 → worker.
2. **App DB와 공모전 DB는 엔진/세션을 절대 공유하지 않는다.** 공모전 DB는 읽기 전용.
3. **worker는 상태를 메모리에 두지 않는다.** 모든 상태는 App DB(`agent_jobs`). 그래야 복제 가능.

---

## 1. 기술 스택 스펙

| 영역 | 선택 | 버전/이미지 | 용도 | 설정 포인트 |
|------|------|------------|------|------------|
| 언어 | Python | **3.12** | api·worker | 3.9 시스템 파이썬과 분리 필수 |
| 패키지/가상환경 | **uv** | 최신 | 의존성·실행 | `uv add`, `uv run`, `uv sync` |
| 웹 프레임워크 | FastAPI | 최신 | api | 모듈러 모놀리식(라우터 분리) |
| ASGI 서버 | uvicorn[standard] | 최신 | api 기동 | `--host 0.0.0.0 --port 8000` |
| ORM | SQLAlchemy | **2.0 (sync)** | App DB | `Mapped`/`mapped_column`/`select()` |
| DB 드라이버 | psycopg | **3.x** | Postgres | URL: `postgresql+psycopg://` |
| 마이그레이션 | Alembic | 최신 | 스키마 버전 | `target_metadata = Base.metadata` |
| 설정 | pydantic-settings | 최신 | env 로딩 | 하드코딩 금지 |
| 큐 | Redis + **RQ** | redis:7 / rq 최신 | 비동기 작업 | Celery 금지(과함). RQ or 리스트 |
| 벡터 DB | **pgvector** | `pgvector/pgvector:pg16` | RAG 임베딩 | App DB 내장(별도 벡터DB X) |
| LLM | **Gemini** | `google-genai` SDK | 추천 이유 생성 | Vertex AI 경로(아래 §3-AI 참고) |
| 임베딩 | Vertex AI 임베딩 | text-embedding 계열 | RAG 벡터화 | LLM과 동일 추상화 뒤 |
| 프론트 | React + **Vite + TypeScript** | 최신 | SPA | 정적 빌드 → nginx |
| 인증 | 구글 OAuth 2.0 | — | 로그인 | Authorization Code 플로우 |
| 테스트 | pytest + httpx | 최신 | 단위/통합 | `TestClient`, 의존성 override |
| 린트 | ruff | 최신 | CI 게이트 | `ruff check .` |
| 컨테이너 | Docker + compose | — | 로컬 전체 기동 | 멀티스테이지 권장 |
| 오케스트레이션 | Kubernetes (**kind** 로컬 / GKE 🟡) | — | 배포 학습 | Helm 차트로 템플릿화 |
| 패키징 | Helm | 최신 | K8s 매니페스트 | values로 환경 분리 |
| CI/CD | GitHub Actions | — | 테스트·빌드·배포 | `.github/workflows/` |
| IaC 🟡 | Terraform | 최신 | GCP 자원 | GKE·Cloud SQL·Artifact Registry |
| 관측-시스템 🟡 | Prometheus + Grafana | — | CPU·요청·에러 | helm |
| 관측-LLM 🟡 | Langfuse | — | 프롬프트·토큰·지연 | `llm.py` 훅 |

---

## 2. 데이터 계약 (역할 간 통신 규약 — 가장 중요)

api와 worker는 아래 스키마로만 대화한다. `libs/keenee_core/schemas.py`에 정의.

```python
# 큐에 들어가는 작업 (api → worker)
class RecommendJobPayload(BaseModel):
    job_id: str
    user_id: int
    limit: int = 5            # 추천 개수

class JobStatus(str, Enum):
    queued = "queued"; running = "running"; done = "done"; failed = "failed"

# 추천 결과 1건 (worker가 저장, api가 반환, web이 표시)
class RecommendationOut(BaseModel):
    competition_id: int
    title: str
    reason: str               # LLM이 생성한 "왜 너에게 맞는지"
    score: float | None = None

# 폴링 응답 (api → web)  GET /recommend/{job_id}
class JobResultOut(BaseModel):
    job_id: str
    status: JobStatus
    results: list[RecommendationOut] = []
    error: str | None = None

# 공모전 1건 (공모전 DB 읽기 결과)
class CompetitionOut(BaseModel):
    id: int
    title: str
    deadline: date | None = None
    organizer: str | None = None
    url: str | None = None
```

**DB 테이블 핵심 컬럼** (`libs/keenee_core/models.py`)

| 테이블 | 핵심 컬럼 | 비고 |
|--------|-----------|------|
| `users` | id, email(unique), name, interests(JSON), skills(JSON), created_at | OAuth 회원 |
| `workspaces` | id, name, owner_id, created_at | 팀 |
| `workspace_members` | id, workspace_id, user_id, role | 멤버십 |
| `agent_jobs` | id, job_id(unique), user_id, status, error, created_at, updated_at | 큐 작업 추적 |
| `recommendations` | id, job_id, user_id, workspace_id(nullable), competition_id, reason, score, created_at | 추천 결과 이력 |
| `embeddings` | id, competition_id, embedding(vector), text, updated_at | pgvector |
| `tasks` ⚪ | id, workspace_id, title, status | 백로그 |

---

## 3. 역할별 상세 명세

### 🟩 BE — api 엔드포인트 명세

| 메서드·경로 | 입력 | 출력 | 동작 | 고려사항 | 연결 |
|------------|------|------|------|---------|------|
| `GET /health` | — | `{"status":"ok"}` | 헬스체크 | K8s liveness/readiness가 사용 | — |
| `GET /auth/google/login` | — | redirect | 구글 동의 화면으로 | state로 CSRF 방지 | 구글 OAuth |
| `GET /auth/google/callback` | `code` | 세션/토큰 | 코드↔토큰 교환→유저 upsert | 이메일 미검증 계정 처리 | `users` |
| `GET /me` | (인증) | User | 내 정보 | 미로그인 401 | `users` |
| `PATCH /me` | interests, skills | User | 관심사·스킬 저장 | 빈 배열 허용 | `users` |
| `GET /competitions?limit=` | limit(1~100) | `list[CompetitionOut]` | 마감 안 지난 공모전 | 공모전 DB 다운 시 503/폴백 | 공모전 DB(읽기) |
| `POST /recommend` | (인증), limit | `{job_id}` | job 생성→Redis enqueue→**즉시** 202 | 중복 요청 방지(진행중 job 재사용) | Redis, `agent_jobs` |
| `GET /recommend/{job_id}` | job_id | `JobResultOut` | 상태·결과 폴링 | 없는 job 404, 권한 체크 | `agent_jobs`,`recommendations` |
| `POST /workspaces` | name | Workspace | 팀 생성(생성자=owner) | — | `workspaces` |
| `POST /workspaces/{id}/members` | email/role | Member | 멤버 초대 | 권한(owner만), 중복 초대 | `workspace_members` |
| `POST /workspaces/{id}/recommendations` | recommendation ids | — | 추천을 팀에 저장 | 멤버만 | `recommendations` |
| `GET /workspaces/{id}` | id | Workspace+추천 | 팀 보기 | 멤버만 | `workspaces`,`recommendations` |

**api 공통 고려사항:** 모든 쓰기는 인증 필요 / 의존성 주입으로 테스트 override 가능하게 / 공모전 DB·LLM 등 외부는 타임아웃·폴백.

### 🟨 AI — worker 모듈 명세

**LLM 경로 결정 (Vertex AI):** `google-genai` SDK는 Gemini API(키)와 Vertex AI(서비스계정) **둘 다 지원**. 개발 초기엔 API 키로 빠르게, 클라우드 배포(M3) 시 Vertex로 전환. `llm.py` 추상화 뒤에 두면 코드 변경 최소. provider 교체(OpenAI 등)도 여기서 흡수.

| 함수/모듈 | 시그니처(예) | 동작 | 고려사항 | 연결 |
|-----------|-------------|------|---------|------|
| `main.run_loop()` | — | 큐 BRPOP → job running → `agent.run` → done/failed | 예외 잡아 failed 기록, 백오프 재시도 | Redis, `agent_jobs` |
| `agent.run(payload)` | `(RecommendJobPayload)->list[RecommendationOut]` | 관심사 로드→RAG 후보→LLM 이유 생성→저장 | 후보 0건 처리, LLM 실패 폴백 | DB, llm, mcp_tools |
| `llm.generate(prompt)` | `(str)->str` | 텍스트 생성(Gemini) | 토큰/타임아웃, Langfuse 추적 | Gemini, Langfuse |
| `llm.embed(text)` | `(str)->list[float]` | 임베딩 벡터 | 배치 처리 권장 | Vertex 임베딩 |
| `rag.semantic_search(q, k)` | `(str,int)->list[CompetitionOut]` | 쿼리 임베딩→pgvector top-k | 인덱스(ivfflat) 필요 | embeddings(pgvector) |
| `embed_job.run()` | — | 신규 공모전 텍스트→임베딩 적재 | 증분(이미 한 건 skip) | 공모전 DB, embeddings |
| `mcp_tools.registry` | 도구 등록 | MCP 도구 노출(초기 in-process) | 후에 서버 분리(E6) | — |
| `mcp_tools.search_competitions` | 조건→`list[CompetitionOut]` | 키워드/마감 검색 | SQL 파라미터 바인딩 | 공모전 DB(읽기) |
| `mcp_tools.semantic_search` | rag 위임 | 의미 검색 도구화 | — | rag.py |

**추천 루프 의사코드 (agent.run):**
```
user = load_user(payload.user_id)
query = build_query(user.interests, user.skills)
candidates = semantic_search(query, k=payload.limit*3)   # 후보 넉넉히
recos = []
for c in candidates[:payload.limit]:
    reason = llm.generate(prompt(user, c))                # "왜 맞는지"
    recos.append(RecommendationOut(competition_id=c.id, title=c.title, reason=reason))
save_recommendations(payload.job_id, recos)
```

### 🟦 FE — 페이지 명세

| 페이지 | 호출 API | 상태/로직 | 고려사항 |
|--------|----------|-----------|---------|
| Login | `/auth/google/login` | 로그인 버튼→리다이렉트 | 콜백 후 토큰 저장 |
| Interests | `GET/PATCH /me` | 관심사·스킬 폼 | 저장 후 추천 페이지 유도 |
| Recommend | `POST /recommend` → `GET /recommend/{job_id}` | **폴링**: 202 받고 status가 done 될 때까지 N초 간격 조회 | 로딩 UI, timeout, failed 표시 |
| Workspace | `/workspaces*` | 팀 생성·초대·추천 공유 | 권한별 UI(owner/member) |

**FE 공통:** API 응답 타입은 §2 데이터 계약과 **1:1 일치**(타입 생성/공유). 폴링은 지수 백오프 또는 고정 2~3초.

### 🟩 BE — 배포 환경 명세

| 구성 | 정의 | 고려사항 |
|------|------|---------|
| `docker-compose.yml` | api+worker+redis+pgvector, api 기동 전 `alembic upgrade head` | 의존성 healthcheck, env 주입 |
| Dockerfile(api/worker) | python:3.12-slim + uv, 멀티스테이지 | 캐시 활용, `--no-dev` |
| Helm 차트 | Deployment(api/worker/web)·Service·Ingress·ConfigMap/Secret | secret은 차트에 평문 금지 |
| CI(`ci.yml`) | ruff + pytest(서비스별 매트릭스) | PR 게이트 |
| CD(`cd.yml`) | 빌드→Artifact Registry 푸시→GKE 배포 | 태그=커밋 SHA |
| Terraform 🟡 | GKE(Spot,e2-small)·Cloud SQL(pgvector)·VPC·Artifact Registry | apply/destroy로 비용 절감 |

---

## 4. 환경변수 전체 목록 (`.env.example`)

```dotenv
# DB
APP_DB_URL=postgresql+psycopg://keenee:keenee@db:5432/keenee
COMPETITION_DB_URL=postgresql+psycopg://readonly:pw@HOST:5432/competition   # 읽기전용
# 큐
REDIS_URL=redis://redis:6379/0
# LLM (둘 중 한 경로)
GEMINI_API_KEY=                      # 개발 초기(AI Studio)
GOOGLE_CLOUD_PROJECT=                # Vertex 경로
GOOGLE_APPLICATION_CREDENTIALS=      # 서비스계정 키 경로(Vertex)
VERTEX_LOCATION=us-central1
# 인증
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=
# 관측 🟡
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
```

---

## 5. 공통 고려사항 (전 역할)

- **에러/실패:** 외부 의존성(LLM·공모전 DB)은 타임아웃·재시도·폴백 필수. worker 실패는 `agent_jobs.status=failed`+error로 노출.
- **보안:** secret은 코드/깃에 금지(env·K8s Secret). 공모전 DB는 읽기 전용 계정. SQL은 항상 파라미터 바인딩.
- **테스트:** 각 과제는 실패 테스트→구현→통과(TDD). 외부 의존성은 의존성 주입으로 가짜(fake)로 대체해 hermetic하게.
- **계약 우선:** §2 데이터 계약·api 엔드포인트는 **출제자가 먼저 고정**. 구현자는 그 인터페이스를 깨지 말 것.
```

