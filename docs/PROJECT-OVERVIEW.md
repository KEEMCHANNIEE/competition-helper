# contest-helper — 프로젝트 개괄 & 작업 구획 (살아있는 지도)

- 작성일: 2026-06-28
- 성격: **2~4명 사이드 프로젝트**(회사 업무 아님), 파트타임 ~10h/주, **3주**
- 1차 목적: **MLOps / AI-Eng 풀 사이클 학습**(컨테이너→K8s→CI/CD→IaC→관측). 제품은 무대.
- 원칙: 학습 가치 ↑ / 과설계 ↓. 자른 기능도 나중에 붙기 쉽게 **구조만 미리**.
- 관련 문서: 설계 스펙 `docs/superpowers/specs/2026-06-25-...-design.md`, M1 구현계획 `docs/superpowers/plans/2026-06-25-milestone-1-foundation-api.md`

> 범례: 🔴 필수 / 🟡 보너스 / ⚪ 백로그 · 과제 ID는 `구획.번호` (예: A1)

---

## 1. 폴더 구조 (목표 모노레포)

4개 서비스가 한 레포에 공존. 기존 M1 plan의 루트 `src/app`은 **`services/api/`로 이동**한다.

```
contest-helper/
├── services/
│   ├── api/                      # 🔴 FastAPI 모듈러 모놀리식 (현관)
│   │   ├── src/app/
│   │   │   ├── main.py           # FastAPI 앱, 라우터 등록
│   │   │   ├── config.py         # pydantic-settings
│   │   │   ├── db.py             # App DB 엔진/세션
│   │   │   ├── competition_db.py # 공모전 DB 엔진(읽기 전용)
│   │   │   ├── queue.py          # Redis enqueue
│   │   │   ├── auth/             # 구글 OAuth 모듈
│   │   │   ├── competitions/     # 공모전 탐색 (router/repository)
│   │   │   ├── recommend/        # 추천 요청 접수 → 큐 위임
│   │   │   └── workspaces/       # 팀 워크스페이스
│   │   ├── migrations/           # Alembic
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   ├── worker/                   # 🔴 agent-worker (+ MCP 도구 초기엔 in-process)
│   │   ├── src/worker/
│   │   │   ├── main.py           # 큐 소비 루프
│   │   │   ├── agent.py          # 추천 에이전트 루프(머리)
│   │   │   ├── llm.py            # LLM 추상화 계층 (기본: Gemini)
│   │   │   ├── rag.py            # pgvector 의미 검색
│   │   │   └── mcp_tools/        # MCP 도구(손) — 나중에 mcp-server로 분리
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── web/                      # 🔴 React SPA
│       ├── src/
│       ├── package.json
│       └── Dockerfile
├── libs/
│   └── contest_helper_core/              # 🔴 api·worker 공유(모델/스키마) — 모델 드리프트 방지
├── deploy/
│   ├── docker-compose.yml        # 🔴 로컬: api + worker + redis + pgvector
│   ├── helm/contest-helper/              # 🔴 로컬 kind / 🟡 GKE 배포 차트
│   └── terraform/                # 🟡 GKE·Cloud SQL·네트워크·Artifact Registry
├── .github/workflows/ci.yml      # 🔴 CI/CD
├── docs/
└── README.md
```

> **분리/통합 메모**
> - `mcp-server`는 **초기엔 worker 안 in-process**(`worker/src/worker/mcp_tools/`), M3 무렵 별도 `services/mcp/` 컨테이너로 떼어낸다 (학습용 분리).
> - `libs/contest_helper_core`는 uv workspace로 api·worker가 공유 (User/recommendation 모델 중복·드리프트 방지). 부담되면 초기엔 api에만 두고 나중에 추출.

---

## 2. 작업 구획 & 세분화 과제

### 구획 A — 백엔드 뼈대 (api) 🔴  → `services/api/`
가벼운 요청 즉시 응답, 무거운 건 큐로 위임하는 현관. (대부분 기존 M1 plan)

| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| A1 | 레포 스캐폴드 + `/health` + CI 골격 | `services/api/src/app/main.py`, `pyproject.toml`, `.github/workflows/ci.yml` | — |
| A2 | 설정 로딩 (env → pydantic-settings) | `config.py`, `.env.example` | A1 |
| A3 | App DB 엔진/세션 + 라우터 모듈 골격 | `db.py`, `main.py`(include_router) | A2, C1 |
| A4 | 공모전 DB 엔진(읽기 전용) + `/competitions` | `competition_db.py`, `competitions/` | A2, C3 |
| A5 | 모듈러 라우팅 정리(auth/recommend/workspaces 빈 모듈) | 각 모듈 `router.py` | A3 |

**DoD:** `uv run pytest` 통과, `/health`·`/competitions` 응답, App/공모전 DB 엔진 분리.

### 구획 B — 인증 & 사용자 🔴  → `services/api/src/app/auth/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| B1 | 구글 OAuth 로그인 플로우(콜백·세션/토큰) | `auth/router.py`, `auth/oauth.py` | A5 |
| B2 | 로그인 사용자 → `users` upsert | `auth/service.py`, `models.User` | B1, C1 |
| B3 | 관심사·스킬 입력 API | `auth/router.py`(PATCH /me) | B2 |

**DoD:** 구글 로그인 → 내 정보/관심사 저장·조회 가능.

### 구획 C — 데이터 계층 🔴  → `libs/contest_helper_core/`, `services/api/migrations/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| C1 | App DB 모델 정의 (`users`) + Alembic 초기화 | `contest_helper_core/models.py`, `migrations/0001_users` | A2 |
| C2 | 나머지 테이블 (`workspaces`,`workspace_members`,`agent_jobs`,`recommendations`,`embeddings`,`tasks`⚪) | 모델 + 마이그레이션 0002~ | C1 |
| C3 | 공모전 DB **실제 스키마 파악** → SQL 테이블/컬럼 치환 | `competitions/repository.py` SQL | (접속정보 필요) |
| C4 | 공모전 텍스트 → 임베딩 적재 잡 (RAG 준비) | `worker/.../embed_job.py`, `embeddings` 테이블 | C2, E2 |

**DoD:** 마이그레이션으로 전체 스키마 생성, 공모전 실 데이터 조회, 임베딩 적재.

### 구획 D — 비동기 처리 (Redis 큐 + worker) 🔴  → `services/worker/`, `api/queue.py`
> 사이드 프로젝트엔 과할 수 있으나 **학습 목적의 의도적 선택.** 가볍게(RQ/Redis 리스트), Celery 회피.

| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| D1 | Redis enqueue (api가 작업 투입 → "접수됨" 응답) | `api/queue.py`, `recommend/router.py` | A5 |
| D2 | worker 큐 소비 루프 (stateless) | `worker/main.py` | D1 |
| D3 | `agent_jobs` 상태머신 (`queued/running/done/failed`) | `worker/main.py`, `models.AgentJob` | C2, D2 |
| D4 | 실패 재시도/백오프 + 폴링 조회 API | `worker/main.py`, `recommend/router.py`(GET job) | D3 |

**DoD:** 추천 요청 → 즉시 접수 → worker 처리 → 폴링으로 결과 확인, 실패 시 상태 노출.

### 구획 E — AI 에이전트 & MCP 🔴  → `services/worker/src/worker/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| E1 | LLM 추상화 계층 (provider 교체 가능, 기본 Gemini) | `worker/llm.py` | — |
| E2 | pgvector RAG 검색 | `worker/rag.py` | C2 |
| E3 | MCP 도구 정의 `search_competitions`/`get_competition_detail`/`semantic_search` | `worker/mcp_tools/` | E2, C3 |
| E4 | 추천 루프(관심사→RAG 후보→이유 생성→`recommendations` 저장) | `worker/agent.py` | E1,E3,D3 |
| E5 | `web_search` 도구 🟡 / `create_tasks` ⚪ | `worker/mcp_tools/` | E3 |
| E6 | mcp-server 별도 컨테이너로 분리 🟡 | `services/mcp/` | E3 |

**DoD:** 유저 관심사로 추천 N건 + "왜 맞는지" 이유 생성·저장, MCP tool-use 동작.

### 구획 F — 워크스페이스 (협업) 🔴  → `services/api/src/app/workspaces/`
2~4명 팀이라 의미 있는 부분.

| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| F1 | 팀 생성 / 멤버 초대 / 역할 | `workspaces/router.py`,`service.py` | C2,B2 |
| F2 | 추천 결과를 팀에 저장·공유 | `recommendations`(workspace_id 연결) | F1,E4 |

**DoD:** 팀 만들고 멤버 초대, 추천을 팀에 저장·열람.

### 구획 G — 프론트엔드 🔴  → `services/web/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| G1 | SPA 골격 + 구글 로그인 연동 | `web/src/` 라우팅·auth | B1 |
| G2 | 관심사 입력 화면 | `web/src/pages/Interests` | B3 |
| G3 | 추천 요청 + **결과 폴링** 표시 | `web/src/pages/Recommend` | D4,E4 |
| G4 | 워크스페이스 화면 | `web/src/pages/Workspace` | F1 |

**DoD:** 로그인→관심사→추천 받기→팀 보기 전 플로우 화면 동작.

### 구획 H — 컨테이너화 & 로컬 K8s 🔴  → `deploy/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| H1 | 서비스별 Dockerfile (api/worker/web) | 각 `Dockerfile` | A4 |
| H2 | docker-compose (api+worker+redis+pgvector) | `deploy/docker-compose.yml` | H1,D2 |
| H3 | 로컬 kind 클러스터 + Helm 차트(Deployment/Service/Ingress/Config·Secret) | `deploy/helm/contest-helper/` | H2 |

**DoD:** `docker compose up`으로 전체 기동, kind에 helm install로 배포.

### 구획 I — CI/CD 🔴  → `.github/workflows/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| I1 | CI: ruff 린트 + pytest 게이트 | `ci.yml` (A1에서 골격) | A1 |
| I2 | CD: 빌드→이미지 푸시(Artifact Registry)→배포 | `ci.yml`/`cd.yml` | H3,J1 |

**DoD:** 푸시 시 테스트 자동 실행, 통과 시 이미지 빌드·배포.

### 구획 J — 클라우드 인프라 (IaC) 🟡  → `deploy/terraform/`
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| J1 | Terraform: GKE·Cloud SQL·네트워크·Artifact Registry | `deploy/terraform/` | — |
| J2 | apply/destroy 운영(켤 때만, 비용 절감) | README 운영 절차 | J1 |

**DoD:** `terraform apply`로 GKE+Cloud SQL 생성, `destroy`로 정리.

### 구획 K — 관측 🟡
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| K1 | 시스템: Prometheus + Grafana 대시보드 1개 | helm values, 대시보드 | H3 |
| K2 | LLM: Langfuse 연동(프롬프트·토큰·지연·품질) | `worker/llm.py` 훅 | E4 |

**DoD:** 시스템 지표 대시보드 + LLM 호출 추적 가시화.

### 구획 L — 테스트/품질 🔴 (상시)
| ID | 과제 | 산출물 | 의존 |
|----|------|--------|------|
| L1 | 단위/통합 테스트 (추천 로직·MCP 도구·API) | 각 `tests/` | 해당 구획 |
| L2 | 외부 의존성 타임아웃·재시도·폴백 | `worker/llm.py`,`competition_db.py` | E1,A4 |

**원칙:** 각 과제는 실패 테스트 → 최소 구현 → 통과 → 커밋 (TDD).

### 구획 M — 백로그 ⚪ (구조만 미리)
업무관리(`tasks`)·계획 에이전트·HPA 오토스케일·추천 eval 파이프라인.

---

## 3. 마일스톤 매핑 (3주)

- **M1 (1주차) 🔴**: A1~A5, C1, C3, H1~H2, I1 — *도커로 띄우면 `/health`·`/competitions` 응답* (기존 M1 plan)
- **M2 (2주차) 🔴**: B1~B3, C2/C4, D1~D4, E1~E4, F1~F2, G1~G4 — *추천 에이전트 + 워크스페이스 동작*
- **M3 (3주차) 🟡**: H3, I2, J1~J2, K1~K2 — *kind/Helm→GKE→Terraform→관측* (또는 1~2주차 마무리·QA 버퍼)

> 🔴만 완성해도 "컨테이너→K8s→CI/CD→돌아가는 AI 에이전트 + 팀 워크스페이스"로 MLOps 포트폴리오로 충분히 강함.
