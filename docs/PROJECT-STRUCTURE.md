# contest-helper — 전체 구조 & 파일별 정의 & 역할 분담 (과제 출제용)

- 작성일: 2026-06-28
- 용도: **과제 출제자가 전체 골격을 미리 잡고, 일부를 비워 "채우기" 과제로 분배**하기 위한 설계도.
- 지금 단계: **각 폴더/파일에 "무엇이 정의돼야 하는지"만 정리**. 실제 코드/스캐폴드 생성은 다음 단계.
- 상위 지도: `docs/PROJECT-OVERVIEW.md` (구획·과제·마일스톤)

## 역할 분담 (4인)

| 태그 | 담당 | 인원 | 주 소유 영역 |
|------|------|------|-------------|
| 🟦 FE | 프론트엔드 | 1 | `services/web/` |
| 🟩 BE | 백엔드 + 배포환경 | 1 | `services/api/`, `libs/contest_helper_core/`(공유 소유), `deploy/`, `.github/`, 마이그레이션 |
| 🟨 AI | AI Agent 개발 | 2 | `services/worker/`(에이전트·LLM·RAG·MCP 도구·임베딩) |

> **계약 지점(seam):** `libs/contest_helper_core/`(모델·DB·공유 스키마)와 `services/api/src/app/recommend/`(요청 접수↔워커)는 **여러 역할이 공유**한다. 여기 인터페이스를 먼저 고정하면 각자 빈칸을 병렬로 채울 수 있다. 이 파일들은 비우지 말고 **출제자가 채워서 제공**하는 것을 권장.

---

## 전체 폴더 트리 (소유 태그 포함)

```
contest-helper/
├── libs/contest_helper_core/            🟩(공유)  ← 계약 계층: 모델·DB·스키마·설정
│   └── src/contest_helper_core/
│       ├── __init__.py
│       ├── config.py
│       ├── db.py
│       ├── competition_db.py
│       ├── models.py
│       └── schemas.py
├── services/
│   ├── api/                     🟩         ← FastAPI 모듈러 모놀리식 (현관)
│   │   ├── src/app/
│   │   │   ├── main.py
│   │   │   ├── deps.py
│   │   │   ├── queue.py
│   │   │   ├── auth/      (router.py, oauth.py, service.py)
│   │   │   ├── competitions/ (router.py, repository.py)
│   │   │   ├── recommend/ (router.py, schemas.py)   ← 🟩↔🟨 계약
│   │   │   └── workspaces/ (router.py, service.py)
│   │   ├── migrations/ (env.py, versions/)
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   ├── worker/                  🟨         ← agent-worker (+ MCP 도구 in-process)
│   │   ├── src/worker/
│   │   │   ├── main.py
│   │   │   ├── agent.py
│   │   │   ├── llm.py
│   │   │   ├── rag.py
│   │   │   ├── embed_job.py
│   │   │   └── mcp_tools/ (__init__.py, registry.py, competitions.py, semantic.py)
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── web/                     🟦         ← React SPA
│       ├── src/ (main, App, api/, pages/, components/, hooks/)
│       ├── package.json
│       └── Dockerfile
├── deploy/                      🟩
│   ├── docker-compose.yml
│   ├── helm/contest-helper/ (Chart.yaml, values.yaml, templates/)
│   └── terraform/ (main.tf, variables.tf, outputs.tf)
├── .github/workflows/ (ci.yml, cd.yml)   🟩
├── docs/
└── README.md
```

---

## 🟩 BE(공유) — `libs/contest_helper_core/`  (계약 계층, 출제자가 채워 제공 권장)

| 파일 | 정의할 것 |
|------|-----------|
| `config.py` | `Settings`(pydantic-settings): `app_db_url`, `competition_db_url`, `redis_url`, `gemini_api_key`/Vertex 설정, `google_oauth_*`, `langfuse_*`. `get_settings()` (lru_cache). **api·worker 공통.** |
| `db.py` | App DB 엔진/세션 팩토리: `app_engine`, `AppSession`, `get_session()` 컨텍스트. |
| `competition_db.py` | 공모전 DB **읽기 전용** 엔진/세션: `competition_engine`, `CompetitionSession`. App DB와 절대 분리. |
| `models.py` | SQLAlchemy 2.0 모델 + `Base`: `User`, `Workspace`, `WorkspaceMember`, `AgentJob`, `Recommendation`, `Embedding`(pgvector), `Task`⚪. 컬럼·관계·인덱스 정의. |
| `schemas.py` | **역할 간 계약 DTO**: `RecommendJobPayload`(워커 입력), `RecommendationOut`, `JobStatus`(enum: queued/running/done/failed), `CompetitionOut`. api·worker가 같은 스키마로 통신. |

---

## 🟩 BE — `services/api/`  (현관: 인증·탐색·워크스페이스·큐 위임)

| 파일 | 정의할 것 |
|------|-----------|
| `src/app/main.py` | `app = FastAPI()`, `GET /health`, 각 모듈 라우터 include. |
| `src/app/deps.py` | FastAPI 의존성: `get_db`(세션), `get_current_user`(인증), repo/queue 주입. 테스트 override 지점. |
| `src/app/queue.py` | Redis enqueue 래퍼: `enqueue_recommend(payload) -> job_id`, 상태 조회. (RQ 또는 리스트, **가볍게**) |
| `auth/router.py` | `GET /auth/google/login`, `GET /auth/google/callback`, `GET/PATCH /me`(관심사·스킬). |
| `auth/oauth.py` | 구글 OAuth 코드↔토큰 교환, 사용자 프로필 획득. |
| `auth/service.py` | 로그인 사용자 → `users` upsert, 세션/토큰 발급. |
| `competitions/repository.py` | 공모전 DB 읽기. `list_open(limit)` 등. **실제 테이블/컬럼명 치환 필요(C3).** |
| `competitions/router.py` | `GET /competitions?limit=` → `list[CompetitionOut]`. |
| `recommend/router.py` | 🟩↔🟨 **계약.** `POST /recommend`(요청 접수→enqueue→job_id 반환), `GET /recommend/{job_id}`(상태·결과 폴링). |
| `recommend/schemas.py` | 요청/응답 스키마(필요 시 contest_helper_core.schemas 재노출). |
| `workspaces/router.py` | 팀 생성·멤버 초대·역할, 추천을 팀에 저장·조회. |
| `workspaces/service.py` | 워크스페이스/멤버십 비즈니스 로직. |
| `migrations/env.py` | Alembic ← `contest_helper_core.models.Base.metadata`, URL은 settings에서. |
| `migrations/versions/` | `0001_users`, `0002_workspaces_jobs_recos`, `0003_embeddings` ... |
| `Dockerfile` | python:3.12-slim + uv, 마이그레이션 후 uvicorn 기동. |

---

## 🟨 AI(2인) — `services/worker/`  (에이전트의 머리+손)

| 파일 | 정의할 것 |
|------|-----------|
| `src/worker/main.py` | 큐 소비 루프(stateless): 작업 수령 → `AgentJob` 상태 갱신(running) → `agent.run()` → 결과 저장(done/failed) → 재시도/백오프. |
| `src/worker/agent.py` | **추천 에이전트 루프(머리).** 유저 관심사 로드 → MCP 도구 호출(후보 검색) → LLM으로 "왜 맞는지" 이유 생성 → `Recommendation` 저장. |
| `src/worker/llm.py` | **LLM 추상화 계층.** `generate()`/`embed()` 인터페이스 + 기본 구현(Gemini/Vertex). provider 교체 가능. Langfuse 훅 지점(K2). |
| `src/worker/rag.py` | pgvector 의미 검색: 쿼리 임베딩 → 유사 공모전 top-k. |
| `src/worker/embed_job.py` | 공모전 텍스트 → 임베딩 적재 잡(C4). `embeddings` 채움. |
| `mcp_tools/registry.py` | MCP 도구 등록·노출(초기 in-process, 후에 서버 분리 E6). |
| `mcp_tools/competitions.py` | `search_competitions`, `get_competition_detail` (공모전 DB 읽기). |
| `mcp_tools/semantic.py` | `semantic_search`(rag.py 사용), `web_search`🟡. |
| `Dockerfile` | worker 컨테이너. |

> **AI 2인 내부 분담 제안** — AI-1: `agent.py`+`llm.py`+`main.py`(루프·추론·LLM). AI-2: `rag.py`+`embed_job.py`+`mcp_tools/`(도구·검색·임베딩). 둘은 `mcp_tools/registry.py` 인터페이스로 만남.

---

## 🟦 FE — `services/web/`

| 파일/폴더 | 정의할 것 |
|-----------|-----------|
| `src/main.tsx`,`App.tsx` | 라우팅 골격, 인증 가드. |
| `src/api/` | 백엔드 호출 클라이언트(엔드포인트별 함수, 타입은 BE 스키마와 일치). |
| `src/hooks/` | `useAuth`, `useRecommendJob`(폴링 훅) 등. |
| `pages/Login` | 구글 로그인. |
| `pages/Interests` | 관심사·스킬 입력. |
| `pages/Recommend` | 추천 요청 + **결과 폴링** 표시. |
| `pages/Workspace` | 팀 생성·초대·추천 공유 화면. |
| `components/` | 공통 UI. |
| `Dockerfile` | 정적 빌드 서빙(nginx 등). |

---

## 🟩 BE — `deploy/` & `.github/` (배포 환경)

| 파일 | 정의할 것 |
|------|-----------|
| `deploy/docker-compose.yml` | 로컬 전체 기동: `api`+`worker`+`redis`+`pgvector`. 마이그레이션 자동 적용. |
| `deploy/helm/contest-helper/Chart.yaml`,`values.yaml` | 차트 메타·이미지 태그·env·리소스. |
| `deploy/helm/contest-helper/templates/` | `Deployment`(api/worker/web), `Service`, `Ingress`, `ConfigMap/Secret`, (`hpa`⚪). |
| `deploy/terraform/main.tf` 등 🟡 | GKE·Cloud SQL(pgvector)·네트워크·Artifact Registry. `variables.tf`/`outputs.tf`. |
| `.github/workflows/ci.yml` | ruff 린트 + pytest(서비스별) 게이트. |
| `.github/workflows/cd.yml` | 빌드→이미지 푸시(Artifact Registry)→배포. |

---

## "비워서 과제로 주기" 가이드

- **고정(채워서 제공):** `libs/contest_helper_core/`(특히 `models.py`,`schemas.py`)와 `recommend/` 계약 — 인터페이스가 흔들리면 모두가 막힘.
- **빈칸 후보(역할별 과제):**
  - 🟦 FE: `pages/Recommend`의 폴링 로직, `pages/Workspace`
  - 🟩 BE: `competitions/repository.py`의 실제 SQL, `auth/oauth.py`, `queue.py`, helm 템플릿
  - 🟨 AI: `agent.py`의 추천 루프, `rag.py`의 top-k 검색, `mcp_tools/semantic.py`
- **권장 방식:** 각 빈칸 파일에 ① 시그니처/타입, ② docstring으로 "해야 할 일", ③ `raise NotImplementedError` 또는 실패 테스트를 미리 넣어두고 "이 테스트를 통과시켜라" 형태로 출제.
```

