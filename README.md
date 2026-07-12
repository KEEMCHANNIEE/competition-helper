# ConMate (contest-helper)

**공모전 팀을 위한 대화형 AI 에이전트 + 협업 워크스페이스.**

"어떤 공모전을 준비해야 할지"부터 "이번 주까지 뭘 해야 할지", "우리 팀이 이 공모전에 잘 맞을지"까지, 하나의 챗봇과 대화하면서 팀 전체의 준비 과정을 관리하는 서비스입니다. (개인 학습 목적: MLOps 파이프라인(에이전트·큐·DB·CI/CD·컨테이너 오케스트레이션)을 실제로 굴려보는 프로젝트이기도 합니다.)

---

## 1. 프로젝트 소개

### 무엇을 하는 서비스인가

ConMate는 크게 두 화면으로 이루어져 있습니다.

- **채팅**: 자연어로 말을 걸면 에이전트가 의도를 파악해서 답합니다 — 공모전 추천, 개념 설명, 준비 계획 생성, 진행 상황 확인, 팀 적합도 평가 등.
- **워크스페이스**: 팀이 준비 중인 공모전 하나를 중심으로, 할 일(Task) 목록·팀원 진행률·주간 리포트·알림을 한눈에 봅니다.

로그인은 팀원 4명 중 한 명을 고르는 데모 화면(`MemberSelect`)에서 시작하고, 실제로는 Google OAuth로 인증합니다.

### 핵심 기능

| 기능 | 설명 |
|---|---|
| 공모전 추천 | 관심사·키워드로 실제 공모전 DB를 검색해 추천 |
| 자유 질문 응답 | "이거 팀으로도 나갈 수 있어?", "작년 수상작 뭐였어?" 같은 질문에 도구를 직접 호출해 답변 (환각 방지) |
| 준비 계획 생성 | 대화 요청을 주차별 할 일 목록으로 바꿔 워크스페이스에 저장 |
| 진행률 평가 | 할 일 완료 비율 + 대화 맥락을 종합해 수치(%)와 코멘트 생성 |
| 팀 적합도 평가 | 팀원들의 관심사·스킬과 공모전 요구사항을 비교해 평가 |
| 팀 현황 / 리스크 점검 | 팀 전체 실행 현황, 마감 대비 리스크를 팀장에게 요약 |
| 주간 리포트 | 워크스페이스 전체 진행률을 집계해 주 단위로 기록 |
| 계획 재조정 제안 | 리스크 점검 후 "이 할 일들 다음 주로 미루자" 같은 제안을 팀장이 승인하면 실제로 반영 |

### 왜 만들었나 (학습 목표)

이 레포는 실서비스 매출보다 **"엔드투엔드로 다 만들어보기"**가 목적입니다 — 큐 기반 비동기 에이전트 아키텍처, App DB/외부 읽기전용 DB 분리, LLM Function Calling, Docker/K8s(Helm)/Terraform 배포, GitHub Actions CI/CD까지 한 레포 안에서 굴립니다.

---

## 2. 데이터 소개

이 프로젝트는 **서로 다른 두 개의 Postgres DB**를 씁니다. 하나는 이 서비스가 직접 쓰는 데이터, 하나는 실제 공모전 정보를 담은 읽기 전용 외부 데이터입니다.

### 2-1. App DB (직접 소유, 쓰기 가능)

로컬/컨테이너의 `pgvector/pgvector:pg16` 이미지 위에서 이 서비스가 직접 관리하는 DB입니다 (Alembic 마이그레이션으로 스키마 관리).

| 테이블 | 역할 |
|---|---|
| `users` | 사용자 (이메일, 이름, 관심사·스킬 배열) |
| `workspaces` | 팀 워크스페이스 (연결된 공모전 id 포함) |
| `workspace_members` | 워크스페이스-사용자 매핑 (역할 포함) |
| `agent_jobs` | 큐에 올라간 에이전트 작업의 상태기계 (queued→running→done/failed) |
| `recommendations` | 에이전트가 만든 추천 결과 |
| `embeddings` | 공모전 텍스트 임베딩 (`pgvector`, 768차원) — 의미 기반 검색용 |
| `tasks` | 워크스페이스 할 일 (주차·담당자·완료 상태) |
| `workspace_progress` | 진행률 평가 이력 (호출 때마다 누적 저장) |
| `conversations` / `messages` | 대화 세션과 메시지 (role: user/assistant/recommend/report/proposal) |

### 2-2. 공모전 DB (외부, 읽기 전용)

**Supabase**에 호스팅된 별도 Postgres이며, 실제로 존재하는 공모전 정보가 담긴 소스입니다 (예: Linkareer 등에서 수집된 것으로 보이는 실데이터). 이 서비스는 여기에 **절대 쓰지 않고 SELECT만** 합니다.

`contests` 테이블 주요 컬럼:

```
id, title, organizer, host, host_type,
category TEXT[], target TEXT[], keywords TEXT[],
start_date DATE, end_date DATE(=마감),
homepage(=외부링크), poster_url,
total_prize_amount, first_prize_amount,
participation_type, team_config, is_career_benefit,
requirements TEXT[], evaluation_criteria TEXT[],
description JSONB, status VARCHAR(진행중/마감)
```

부가 테이블 `contests_sources`(출처 사이트·조회수·스크랩 수 등)도 있습니다.

> ⚠️ **데이터 품질 참고**: `category`/`target` 은 원본 소스가 자체적으로 붙인 값이라, 가끔 직관과 다르게 분류된 경우가 있습니다(예: 손글씨 대회가 "광고/마케팅"으로 분류). 에이전트는 이 값을 있는 그대로 신뢰하고 검색하므로, 추천 결과의 정확도는 원본 데이터 태깅 품질에 달려 있습니다.

### 2-3. 검색 방식

- **키워드/구조화 필터 검색** (`search_competitions`): `category`/`target`/`상금`/`참가형태`/`취업연계`/`마감일`을 조합해 SQL로 직접 필터링. LLM이 자연어 요청을 `CompetitionSearchFilters` 구조로 뽑아낸 뒤 이 함수를 호출합니다.
- **의미 기반 검색** (`semantic_search`, 구현 예정): 쿼리를 임베딩(`gemini-embedding-001`, 768차원)으로 바꿔 `embeddings` 테이블에서 코사인 유사도로 top-k를 찾는 방식.
- **웹 검색** (`web_search`): DB에 없는 사실(작년 수상작, 심사위원 등)은 DuckDuckGo로 실시간 보완.

---

## 3. 사용 기술 소개

### 백엔드

| 분류 | 기술 |
|---|---|
| 언어/런타임 | Python 3.12, [uv](https://docs.astral.sh/uv/) (워크스페이스 모노레포 패키지 매니저) |
| API 서버 | FastAPI + Uvicorn(`--reload`) |
| ORM/DB 드라이버 | SQLAlchemy 2.0 + psycopg3 |
| 마이그레이션 | Alembic |
| 데이터 검증 | Pydantic v2 / pydantic-settings |
| 인증 | Authlib (Google OAuth2) + 서명 세션 쿠키(itsdangerous) |
| 큐 | Redis (`brpop` 블로킹 큐, api → worker 비동기 작업 전달) |
| 린트/포맷 | ruff (E/F/I/UP/B 룰셋) |
| 테스트 | pytest |

### AI / 에이전트

| 분류 | 기술 |
|---|---|
| LLM | Google Gemini (`google-genai` SDK) — 생성: `gemini-flash-lite-latest`, 임베딩: `gemini-embedding-001` |
| 실행 경로 | Gemini API 키 또는 Vertex AI(GCP) 중 택1, 설정으로 분기 |
| 도구 호출(Tool Use) | google-genai의 **Automatic Function Calling** — 파이썬 함수를 그대로 넘기면 모델이 필요할 때 알아서 실행 |
| 벡터 검색 | pgvector (코사인 거리) |
| 웹 검색 | `ddgs` (DuckDuckGo, API 키 불필요) |
| 관측(옵션) | Langfuse (환경변수 설정 시) |

### 프론트엔드

| 분류 | 기술 |
|---|---|
| 프레임워크 | React 19 + Vite |
| 라우팅 | 없음 — `useState` 기반으로 두 페이지(Chat/Workspace)를 동시에 마운트해두고 `display` 토글 (대화 내용 유지 목적) |
| 상태 저장 | `sessionStorage` (현재 페이지, 팀원 전환 여부 유지) |
| 아이콘 | react-icons |
| 린트 | eslint |

### 인프라 / 배포

| 분류 | 기술 |
|---|---|
| 로컬 개발 | Docker Compose (`docker-compose.dev.yml`: DB+Redis+API+Worker+Web, 소스 마운트로 핫리로드) |
| 컨테이너 이미지 | `deploy/docker/{api,worker,web}.Dockerfile` |
| 오케스트레이션 | Kubernetes(GKE) + Helm 차트 (`deploy/helm/contest-helper`) |
| IaC | Terraform (`deploy/terraform`) |
| CI | GitHub Actions — ruff 린트 + pytest(api/worker) + npm build/vitest(web) |
| CD | GitHub Actions — 이미지 빌드 → GCP Artifact Registry push → `helm upgrade`로 GKE 롤링 배포 |
| DB(App) | `pgvector/pgvector:pg16` (pgvector 확장 포함 Postgres) |
| DB(공모전, 외부) | Supabase Postgres (읽기 전용) |

---

## 4. 구현 내용 소개

### 4-1. 전체 아키텍처

```
┌─────────┐   HTTP    ┌──────────────┐   Redis Queue   ┌────────────────┐
│   Web    │ ───────► │  api (FastAPI) │ ─────────────► │ worker (에이전트) │
│ (React)  │ ◄─────── │  동기 응답      │ ◄────────────── │ 큐 소비·상태기계   │
└─────────┘  폴링      └──────────────┘   (job 상태만)   └────────────────┘
                              │                                   │
                              ▼                                   ▼
                        ┌───────────┐                    ┌──────────────────┐
                        │  App DB   │◄───────────────────│  Gemini / 웹검색   │
                        │(Postgres) │                    │  공모전 DB(읽기전용) │
                        └───────────┘                    └──────────────────┘
```

- **api**: 요청을 받아 즉시 `202 Accepted` + `job_id`를 돌려주고, 실제 작업은 Redis 큐(`contest-helper:jobs:recommend` / `contest-helper:jobs:chat`)에 올립니다. 프론트는 `GET /recommend/{job_id}`, `GET /chat/{conversation_id}`로 폴링해 결과를 받습니다.
- **worker**: `brpop`으로 큐를 무한 대기하다가 payload를 받으면 상태를 `queued→running→done/failed`로 전이시키고, 실패해도 워커 프로세스 전체가 죽지 않도록 예외를 흡수합니다.
- **App DB**는 이 서비스가 쓰기까지 하는 자체 데이터, **공모전 DB**는 읽기 전용 외부 소스로 완전히 분리되어 있습니다.

### 4-2. 대화형 에이전트 (`worker/agent.py`)

하나의 `chat(conversation_id, user_id)` 진입점이 있고, 내부에서 아래 순서로 의도를 분류합니다:

1. **키워드 우선 규칙**(workspace/wsedit/log/topic/advice/teamstatus/riskcheck 등) — 서로 헷갈리기 쉬운 표현을 먼저 확정.
2. 위에서 안 걸리면 **LLM에게 직접 분류를 맡김** (`_classify_intent`) — 13가지 의도 중 하나만 답하도록 프롬프트.
3. LLM 호출이 실패하면(자격증명·네트워크 문제) **키워드 기반 폴백**으로 대체 — 대화가 끊기지 않도록.

분류된 의도별로 별도 핸들러가 실행됩니다:

| 의도 | 처리 |
|---|---|
| `recommend` | 키워드 추출 → DB 검색 → 없으면 전체 목록 재시도 |
| `plan` | LLM으로 주차별 할 일 JSON 생성 → 실패 시 단일 항목 폴백 → `create_tasks` 도구로 저장 |
| `progress` | `progress_agent.evaluate_progress` 호출 (아래 4-3) |
| `teamstatus` / `riskcheck` / `report` | 팀 전체 실행 현황·리스크·주간 집계 (아래 4-4) |
| 그 외 전부(`study`) | **도구 호출형 자유 응답** (아래 4-3) |

### 4-3. 도구 호출(Function Calling) 기반 자유 응답 (`worker/competition_agent.py`)

"이거 팀으로도 나갈 수 있어?", "작년 수상작이 뭐였어?" 같은 질문은 미리 if/elif로 분기하지 않고, **파이썬 함수를 그대로 LLM에 도구로 넘겨** 모델이 스스로 필요한 함수를 호출하게 합니다(`GeminiClient.generate_with_tools`, Automatic Function Calling). 어떤 질문에 어떤 도구를 쓸지는 **각 도구 함수의 docstring**이 기준이라, 새 도구를 추가해도 분기 코드를 늘릴 필요가 없습니다.

등록된 도구: `compare_competitions`(비교), `get_competition_detail`(상세 조회), `search_competitions`(재검색), `web_search`(DB에 없는 사실 확인), `check_team_fit`(팀 적합도), `list_saved_competitions`(워크스페이스 저장 목록). 프롬프트에는 "확인 없이 답하지 말고, 모르면 도구부터 불러라"는 규칙을 명시해 환각을 억제합니다.

추천/검색 결과는 `Message(role="recommend")`로 저장해두고 **순번(1, 2, 3...)만 사용자에게 노출**하며, 실제 DB id는 대화 기록 안에만 남겨 LLM이 이후 "1번 공모전 자세히 알려줘" 같은 후속 질문에서 참조하게 합니다.

### 4-4. 워크스페이스 에이전트 (`worker/progress_agent.py`, `worker/team_fit.py`)

- **진행률 평가**: 담당자 배정된 할 일의 완료 비율(없으면 전체 할 일로 대체) + 최근 대화 내용을 근거로 LLM 코멘트 생성. LLM이 실패하면 규칙 기반 코멘트("마감까지 N일 남았는데 진행률이 X%예요")로 폴백. 결과는 `workspace_progress`에 이력으로 누적 저장.
- **팀 적합도**: 팀원 전체의 관심사·스킬과 공모전의 지원자격·심사기준을 LLM에 함께 넣어 강점/약점/총평 생성.
- **주간 리포트 / 리스크 점검(S-03)**: 워크스페이스 전체 진행률 + 팀원별 진행률을 집계해 `Message(role="report")`로 기록하고, 리스크가 보이면 "이 할 일들 다음 주로 미루자" 같은 **제안**(`role="proposal"`)을 생성 — 팀장이 승인하면 해당 Task들의 `week_no`를 실제로 +1 하여 반영합니다(중복 반영 방지 플래그 포함).

### 4-5. API 엔드포인트 (`services/api`)

| 분류 | 엔드포인트 |
|---|---|
| 인증 | `GET /auth/google/login`, `GET /auth/google/callback`, `GET/PATCH /me`, `POST /auth/dev/switch`(데모용 팀원 전환) |
| 공모전 | `GET /competitions`, `GET /competitions/{id}` |
| 추천 | `POST /recommend`(큐 등록), `GET /recommend/{job_id}`(폴링) |
| 채팅 | `POST /chat`, `GET /chat/{conversation_id}`, `GET /notifications`, `POST /notifications/read` |
| 워크스페이스 | `POST/GET /workspaces`, `GET /workspaces/{id}`, `GET/POST /workspaces/{id}/members`, `POST /workspaces/{id}/demo-team`, `GET/POST /workspaces/{id}/tasks`, `PATCH /workspaces/{id}/tasks/{task_id}`, `POST /workspaces/{id}/recommendations`, `GET /workspaces/{id}/logs`, `GET /workspaces/{id}/reports`, `POST /workspaces/{id}/weekly-report`, `POST /workspaces/{id}/proposals/approve` |

### 4-6. 프론트엔드 (`services/web`)

- 진입 시 `MemberSelect` 화면에서 데모 팀원 중 한 명을 골라 세션을 그 사용자로 전환합니다.
- 이후 `Chat`/`Workspace` 두 페이지를 **항상 함께 마운트**해두고 `display: contents`로만 전환합니다 — 화면을 오가도 채팅 내용이 사라지지 않게 하기 위함입니다.
- 워크스페이스에서 할 일을 클릭하면 "이거 어떻게 시작하면 좋을지" 묻는 메시지가 채팅으로 자동 전달됩니다(`pendingChat`).
- 알림은 `NotificationToast` 컴포넌트가 주기적으로 폴링해 표시합니다.

### 4-7. 인증 흐름

- 실제: Google OAuth2 (Authlib) — `state` CSRF 토큰을 쿠키에 잠깐 저장 → 콜백에서 검증 → 사용자 upsert → 서명된 세션 쿠키 발급.
- 로컬 개발용: `dev_bypass_auth` 설정 시 로그인 없이 더미 사용자로 즉시 인증(프로덕션 사용 금지, 코드에도 명시).

---

## 로컬 실행

### 방법 A — Docker Compose (전체 스택 한 번에)

```bash
cp .env.example .env   # COMPETITION_DB_URL(Supabase), GEMINI_API_KEY, Google OAuth 등 채우기
docker compose -f docker-compose.dev.yml --env-file .env up --build
```

- api: http://localhost:8000 (`/health`)
- web: http://localhost:5173
- DB: localhost:5432, Redis: localhost:6379

### 방법 B — 로컬 직접 실행 (DB/Redis만 컨테이너)

```bash
# 의존성 (워크스페이스 전체 — 반드시 --all-packages 필요)
uv sync --dev --all-packages

# DB 마이그레이션
cd services/api && uv run alembic upgrade head

# 각각 별도 터미널에서
uv run uvicorn app.main:app --reload            # services/api
uv run python -m worker.main                    # services/worker
npm run dev -- --host                           # services/web
```

### 테스트 / 린트

```bash
uv run ruff check .                                          # 전체 린트
uv run --package contest-helper-api pytest services/api/tests
uv run --package contest-helper-worker pytest services/worker/tests
```

> `.venv`가 없거나 도구가 "program not found"로 나오면 `--all-packages` 없이 `uv sync`한 게 원인일 수 있습니다 — 워크스페이스 루트 프로젝트 자체엔 의존성이 없어서, 이 옵션 없이는 api/worker의 dev 의존성(ruff, pytest 등)이 설치되지 않습니다.

---

## 저장소 구조

```
competition-helper/
├── libs/contest_helper_core/   공유 계약 — App DB 모델, 공모전 DB 엔진, 통신 스키마(DTO), 설정
├── services/
│   ├── api/      FastAPI — 인증·공모전 조회·추천 위임·채팅·워크스페이스
│   ├── worker/   에이전트 — 큐 소비, 의도 분류, 도구 호출, 진행률/팀적합도/리포트
│   └── web/      React SPA (채팅 + 워크스페이스)
├── deploy/       docker-compose(prod-like) · Dockerfile · Helm 차트 · Terraform
├── docker-compose.dev.yml   로컬 개발용 전체 스택(핫리로드)
└── .github/workflows/       CI(ruff/pytest/vitest) · CD(GKE 배포)
```

## 환경변수 (`.env`)

| 변수 | 용도 |
|---|---|
| `APP_DB_URL` | App DB(Postgres) 접속 문자열 |
| `COMPETITION_DB_URL` | 공모전 DB(Supabase, 읽기 전용) 접속 문자열 |
| `REDIS_URL` | 큐 접속 문자열 |
| `GEMINI_API_KEY` | Gemini API 직접 호출용 (미설정 시 Vertex AI 경로로 분기) |
| `GOOGLE_CLOUD_PROJECT` / `VERTEX_LOCATION` | Vertex AI 경로 사용 시 |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Google 로그인 |
| `SESSION_SECRET` | 세션 쿠키 서명 키 |
| `FRONTEND_URL` | OAuth 콜백 후 리다이렉트 대상 |
| `LANGFUSE_*` | (옵션) LLM 호출 관측 |
| `DEV_BYPASS_AUTH` | 로컬 전용 — 로그인 없이 더미 사용자로 우회 |

## 규칙

- `libs/contest_helper_core/`는 api·worker가 공유하는 계약 계층 — 임의 변경 시 양쪽 모두 영향을 받으므로 신중히.
- App DB / 공모전 DB(읽기 전용) 엔진은 항상 분리해서 사용 — 공모전 DB에는 절대 쓰지 않음.
- 비밀값은 `.env`/Secret으로만 관리 (`.env`는 깃에 올리지 않음).
