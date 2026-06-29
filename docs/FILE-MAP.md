# 파일 지도 — 각 파일이 왜 필요한가 (순서대로)

- 작성일: 2026-06-29
- 용도: 프로젝트의 **모든 파일**을 "읽는 순서(토대 → 바깥)"대로 훑으며, **왜 존재하는지** 한 줄로 설명.
- 같이 보기: `PROJECT-STRUCTURE.md`(폴더·역할), `TECH-SPEC.md`(엔드포인트·계약), `AGENT-GUIDE.md`(에이전트 구현 예시)
- 상태: ✅채움 · 🔒고정(계약) · 🟨AI과제(빈칸) · ⚠️값/설정필요

> 읽는 추천 순서: **0 루트 → 1 계약(libs) → 2 api → 3 worker → 4 web → 5 deploy → 6 CI/CD**.
> 데이터가 흐르는 순서이기도 하다: 설정·약속을 정하고 → 현관(api) → 두뇌(worker) → 화면(web) → 배포.

---

## 0. 루트 — 프로젝트 전체 설정

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `pyproject.toml` | **uv 워크스페이스 루트**. api·worker·libs를 한 묶음으로 묶어 공유 패키지를 연결. ruff 설정. | ✅ |
| `.env.example` | 필요한 환경변수 목록(견본). 복사해서 `.env`로 값 채움. | ✅ |
| `.env` | 실제 비밀값(Supabase·OAuth 등). **깃 제외.** | ⚠️ 값 채움 |
| `.gitignore` | `.env`·`.venv`·`node_modules` 등 깃에 안 올릴 것 지정. | ✅ |

---

## 1. `libs/contest_helper_core/` — 🔒 공용 계약 (모두가 의존)

> 모든 서비스가 import하는 "공통 약속". 여기가 흔들리면 전부 깨지므로 **출제자만 관리**.

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `pyproject.toml` | 이 공유 패키지의 의존성(SQLAlchemy·pydantic·pgvector) 정의. | 🔒✅ |
| `src/contest_helper_core/__init__.py` | 패키지 표식. | 🔒✅ |
| `config.py` | 모든 환경변수를 코드로 읽는 `Settings`. 하드코딩 방지의 단일 출처. | 🔒✅ |
| `db.py` | **App DB**(우리 것: 쓰기) 엔진/세션 생성. | 🔒✅ |
| `competition_db.py` | **공모전 DB**(Supabase: 읽기 전용) 엔진/세션. App과 분리. | 🔒✅ |
| `models.py` | App DB 테이블 정의(User·Workspace·AgentJob·Recommendation·Embedding·Task). | 🔒✅ |
| `schemas.py` | 서비스 간 통신 DTO(`RecommendJobPayload`·`CompetitionOut`·`RecommendationOut`·`JobResultOut`). | 🔒✅ |

---

## 2. `services/api/` — 🟩 현관 (FastAPI)

> 사용자 요청의 입구. 가벼운 건 즉시 응답, 무거운 추천은 큐로 던진다.

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `pyproject.toml` | api 서비스 의존성(fastapi·uvicorn·authlib·redis 등). | ✅ |
| `src/app/__init__.py` | 패키지 표식. | ✅ |
| `src/app/main.py` | **FastAPI 앱 본체.** `/health` + 모든 라우터 등록. 진입점. | ✅ |
| `src/app/deps.py` | 공통 의존성 주입(DB세션·로그인유저·redis). 테스트 교체 지점. | ✅ |
| `src/app/queue.py` | 추천 작업을 Redis 큐에 넣는 `enqueue_recommend`. api↔worker 연결고리. | ✅ |
| `src/app/auth/__init__.py` | 패키지 표식. | ✅ |
| `src/app/auth/oauth.py` | 구글 OAuth 코드↔토큰 교환·프로필 획득. | ✅ ⚠️OAuth키 |
| `src/app/auth/service.py` | 로그인 유저를 `users`에 저장(upsert)·세션 쿠키 발급. | ✅ |
| `src/app/auth/router.py` | `/auth/google/*`, `/me`(관심사·스킬) 엔드포인트. | ✅ |
| `src/app/competitions/__init__.py` | 패키지 표식. | ✅ |
| `src/app/competitions/repository.py` | **공모전 DB(`contests`) 읽기 SQL.** 진행중 공모전 목록. | ✅ |
| `src/app/competitions/router.py` | `GET /competitions` 엔드포인트. | ✅ |
| `src/app/recommend/__init__.py` | 패키지 표식. | ✅ |
| `src/app/recommend/router.py` | `POST /recommend`(접수→큐), `GET /recommend/{id}`(폴링). 🟩↔🟨 계약. | ✅ |
| `src/app/workspaces/__init__.py` | 패키지 표식. | ✅ |
| `src/app/workspaces/service.py` | 팀·멤버십 비즈니스 로직. | ✅ |
| `src/app/workspaces/router.py` | 팀 생성·초대·추천 공유 엔드포인트. | ✅ |
| `alembic.ini` | DB 마이그레이션 도구 설정. | ✅ |
| `migrations/env.py` | 마이그레이션이 모델(`Base`)·DB URL을 어디서 읽을지 연결. | ✅ |
| `migrations/script.py.mako` | 마이그레이션 파일 생성 템플릿. | ✅ |
| `migrations/versions/0001_init.py` | **첫 마이그레이션**: 전체 테이블 생성. | ✅ |
| `tests/__init__.py` | 테스트 패키지 표식. | ✅ |
| `tests/conftest.py` | 테스트 공용 픽스처(가짜 DB·의존성 override). | ✅ |
| `tests/test_health.py` | `/health` 동작 검증. | ✅ |
| `tests/test_competitions.py` | 공모전 목록 엔드포인트 검증(가짜 repo). | ✅ |
| `tests/test_recommend.py` | 추천 접수·폴링 흐름 검증. | ✅ |
| `tests/test_workspaces.py` | 팀·권한 검증. | ✅ |
| `Dockerfile` | api 이미지(개별). 표준은 `deploy/docker/api.Dockerfile`. | ✅ |

---

## 3. `services/worker/` — 🟨 두뇌 (agent-worker)

> 큐에서 작업을 꺼내 추천을 생성. **배관은 채워져 있고, AI 두뇌만 빈칸(과제).**

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `pyproject.toml` | worker 의존성(redis·google-genai 등). | ✅ |
| `src/worker/__init__.py` | 패키지 표식. | ✅ |
| `src/worker/main.py` | **배관:** 큐 소비 루프 + 작업 상태(running/done/failed) + 결과 DB 저장. `agent.run` 호출. | ✅ 🔒(고치지 말 것) |
| `src/worker/agent.py` | **추천 루프(머리):** 관심사→후보검색→이유생성→반환. | 🟨 과제 |
| `src/worker/llm.py` | LLM 추상화 + Gemini 구현(`generate`/`embed`). | 🟨 과제 |
| `src/worker/rag.py` | pgvector 의미 검색(`semantic_search`). | 🟨 과제 |
| `src/worker/embed_job.py` | 공모전 텍스트→임베딩 적재(검색 대상 준비). | 🟨 과제 |
| `src/worker/mcp_tools/__init__.py` | 도구 패키지 표식. | ✅ |
| `src/worker/mcp_tools/competitions.py` | `search_competitions`/`get_competition_detail`(공모전 DB 읽기 도구). | 🟨 과제 |
| `src/worker/mcp_tools/semantic.py` | `semantic_search` 도구 래퍼. | 🟨 과제 |
| `src/worker/mcp_tools/registry.py` | 도구들을 한데 등록(function calling용). | 🟨 과제 |
| `tests/__init__.py` | 테스트 패키지 표식. | ✅ |
| `tests/conftest.py` | 테스트 픽스처(SQLite·FakeRedis). | ✅ |
| `tests/test_main_loop.py` | **배관 테스트** — 이미 통과해야 정상. | ✅ |
| `tests/test_agent.py` | agent.run 과제의 정답지(현재 실패). | 🟨 과제 |
| `tests/test_rag.py` | semantic_search 과제의 정답지(현재 실패). | 🟨 과제 |
| `tests/test_mcp_tools.py` | 도구 과제의 정답지(현재 실패). | 🟨 과제 |
| `Dockerfile` | worker 이미지(개별). 표준은 `deploy/docker/worker.Dockerfile`. | ✅ |

---

## 4. `services/web/` — 🟦 화면 (React + Vite + TS)

> 사용자가 보는 UI. api를 호출하고 추천 결과를 폴링해 보여준다.

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `package.json` | 프론트 의존성(react·vite·vitest 등). | ✅ |
| `tsconfig.json` / `tsconfig.node.json` | TypeScript 컴파일 설정. | ✅ |
| `vite.config.ts` | 개발 서버·빌드·`/api` 프록시(→FastAPI)·vitest 설정. | ✅ |
| `index.html` | SPA 진입 HTML. | ✅ |
| `.env.example` | 프론트 환경변수 견본(`VITE_API_BASE`). | ✅ |
| `.gitignore` / `.dockerignore` | 빌드·의존성 제외. | ✅ |
| `src/main.tsx` | React 앱 부트스트랩. | ✅ |
| `src/App.tsx` | 라우팅 + 로그인 가드. | ✅ |
| `src/vite-env.d.ts` | Vite 타입 선언. | ✅ |
| `src/api/types.ts` | **BE 계약과 1:1 TS 타입.** 프론트-백 불일치 방지. | ✅ |
| `src/api/client.ts` | fetch 래퍼(공통 호출·에러 처리). | ✅ |
| `src/api/endpoints.ts` | 엔드포인트별 호출 함수(login·me·recommend…). | ✅ |
| `src/hooks/useAuth.ts` | 로그인 상태 훅. | ✅ |
| `src/hooks/useRecommendJob.ts` | **추천 폴링 훅**(2초마다 상태 조회). | ✅ |
| `src/pages/Login.tsx` | 구글 로그인 화면. | ✅ |
| `src/pages/Interests.tsx` | 관심사·스킬 입력. | ✅ |
| `src/pages/Recommend.tsx` | 추천 요청 + 결과 표시. | ✅ |
| `src/pages/Workspace.tsx` | 팀 생성·초대·공유. | ✅ |
| `src/components/Loading.tsx` | 로딩 표시. | ✅ |
| `src/components/ErrorBanner.tsx` | 에러 표시. | ✅ |
| `src/components/NavBar.tsx` | 상단 내비. | ✅ |
| `src/components/RecommendationCard.tsx` | 추천 1건 카드. | ✅ |
| `src/index.css` | 기본 스타일. | ✅ |
| `tests/setup.ts` | vitest 셋업. | ✅ |
| `tests/Recommend.test.tsx` | 추천 화면 렌더·폴링 검증. | ✅ |
| `nginx.conf` | 정적 빌드 SPA 서빙(라우팅 fallback). | ✅ |
| `Dockerfile` | web 이미지(개별). 표준은 `deploy/docker/web.Dockerfile`. | ✅ |

---

## 5. `deploy/` — 🟩 배포 환경

> 로컬(docker-compose/kind)부터 클라우드(GKE)까지 어떻게 띄울지.

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `docker-compose.yml` | **로컬 전체 기동:** api+worker+web+pgvector+redis 한 번에. | ✅ |
| `.dockerignore` | 이미지에 안 넣을 것 제외. | ✅ |
| `docker/api.Dockerfile` | api 이미지(빌드 컨텍스트=레포 루트, 워크스페이스 인식). | ✅ |
| `docker/worker.Dockerfile` | worker 이미지. | ✅ |
| `docker/web.Dockerfile` | web 빌드→nginx 서빙(멀티스테이지). | ✅ |
| `docker/nginx.conf` | web 컨테이너 nginx 설정. | ✅ |
| `helm/contest-helper/Chart.yaml` | Helm 차트 메타. | ✅ |
| `helm/contest-helper/values.yaml` | 이미지 태그·env·리소스·복제 수 값. | ✅ |
| `helm/contest-helper/templates/_helpers.tpl` | 이름·라벨 생성 공용 로직. | ✅ |
| `helm/.../api-deployment.yaml` / `api-service.yaml` | api Pod 배포 + 내부 접속. | ✅ |
| `helm/.../worker-deployment.yaml` | worker Pod 배포(포트 없음). | ✅ |
| `helm/.../web-deployment.yaml` / `web-service.yaml` | web Pod 배포 + 접속. | ✅ |
| `helm/.../ingress.yaml` | 외부 진입(`/`→web, `/api`→api). | ✅ |
| `helm/.../configmap.yaml` | 비밀 아닌 환경변수. | ✅ |
| `helm/.../secret.yaml` | 비밀 환경변수(키 등). | ✅ |
| `helm/.../redis.yaml` | 개발용 단일 Redis. | ✅ |
| `helm/README.md` | **초보자용:** kind 만들고 helm 배포하는 단계별 가이드. | ✅ |
| `terraform/main.tf` | 🟡 GCP 자원(GKE·Cloud SQL·Artifact Registry·VPC) 코드화. | ✅ |
| `terraform/variables.tf` / `outputs.tf` | Terraform 입력 변수 / 출력값. | ✅ |
| `terraform/README.md` | 🟡 apply/destroy·비용 절감 운영법(초보자용). | ✅ |

---

## 6. `.github/workflows/` — 🟩 CI/CD

| 파일 | 왜 필요한가 | 상태 |
|---|---|---|
| `ci.yml` | 푸시/PR마다 ruff 린트 + pytest(서비스별) + web 빌드 자동 실행. | ✅ |
| `cd.yml` | main 푸시 시 이미지 빌드→Artifact Registry 푸시→GKE 배포. | ✅ ⚠️GCP 시크릿 |

---

## 7. `docs/` — 문서

| 파일 | 왜 필요한가 |
|---|---|
| `PROJECT-OVERVIEW.md` | 구획·과제·마일스톤 큰 지도. |
| `PROJECT-STRUCTURE.md` | 폴더/파일 정의 + 역할 분담. |
| `TECH-SPEC.md` | 기술 스택·엔드포인트·데이터 계약·환경변수. |
| `AGENT-GUIDE.md` | 에이전트 구현 방법 + 참고 예시 코드. |
| `FILE-MAP.md` | (이 문서) 파일별 존재 이유. |
| `superpowers/` | 최초 설계 스펙·M1 계획(이력). |

---

## 한눈에: "동작에 꼭 필요한 최소"
1. `.env` 채우기(⚠️) → 2. `libs`(계약, 이미 됨) → 3. `api`(현관, 됨) → 4. `worker`의 🟨 6개 파일 구현(AI 과제) → 5. `docker-compose`로 기동.
나머지(web·helm·terraform·ci)는 이미 채워져 있어 값·시크릿만 넣으면 된다.
