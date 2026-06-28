# 공모전 추천 에이전트 — MLOps 학습 프로젝트 설계

- 작성일: 2026-06-25
- 상태: 설계 합의 완료 (구현 계획 단계로 이행 예정)

## 1. 목적과 목표

### 1차 목표 (가장 중요)
**AI Engineer / MLOps Engineer 역량 학습.** 컨테이너화, Kubernetes, CI/CD, IaC,
서빙·관측까지 "배포·운영 풀 사이클"을 직접 손에 익히는 것이 핵심이다. 제품은 그
역량을 기르기 위한 무대(vehicle)다.

### 제품 (무대 위 콘텐츠)
공모전 DB(이미 배포된 적재 파이프라인이 주기적으로 채움) 위에 올리는 **"맞춤 공모전
추천 에이전트 + 팀 워크스페이스"** 서비스.

### 확정 결정
| 항목 | 결정 |
|---|---|
| 1차 목표 | MLOps/AI-Eng 학습 (제품은 무대) |
| 클라우드 | GCP / GKE |
| 백엔드 | Python + FastAPI |
| 인증 | 구글 OAuth 로그인 + 간단 관심사 입력 |
| 에이전트 | MCP 기반(처음부터) + pgvector RAG |
| LLM | Gemini (Vertex AI / GCP) |
| CI/CD | GitHub Actions |
| IaC | Terraform |
| 관측 | 시스템(Prometheus+Grafana) + LLM(Langfuse) |
| 인원 | 소규모 팀 (2~4) |
| 기간/리소스 | 3주, 파트타임(주 ~10h 이하, 총 ~30h) |

## 2. 아키텍처

GKE 클러스터 안에 4개 서비스가 돌고, GCP 매니지드 자원과 MLOps 도구가 감싼다.

```
   사용자 ─► [frontend]            ┌──────────── GKE 클러스터 ────────────┐
   (React SPA)                    │                                      │
                                  │  [api: FastAPI 모놀리식]  enqueue ┌─────────┐
                                  │   - 탐색/추천 모듈        ───────► │ Redis   │
                                  │   - 워크스페이스 모듈      ◄─────── │ (queue) │
                                  │   - (백로그) 업무관리      result  └─────────┘
                                  │   - 인증(구글 OAuth)              ▲       │ 소비
                                  │          │                       │  ┌──────────────┐
                                  │          │                       └─ │ agent-worker  │
                                  │          │                          │ (LLM 셰프)     │
                                  │          │                          └──────┬───────┘
                                  │          │                       (MCP 프로토콜)│
                                  │          │                          ┌──────────────┐
                                  │          │                          │ mcp-server   │
                                  │          │                          │ (도구 모음)    │
                                  └──────────┼──────────────────────────┴──────┬───────┘
                                             ▼                                  ▼
                              ┌────────────────────────┐        ┌────────────────────────┐
                              │ App DB (Cloud SQL       │        │ 공모전 DB (기존)          │
                              │  Postgres + pgvector)   │        │ ← 적재 파이프라인(배포됨)   │
                              │ users/workspaces/tasks/ │        │   (읽기 전용 소스)         │
                              │ agent_jobs/recos/embed  │        └────────────────────────┘
                              └────────────────────────┘

  감싸는 레이어: Terraform(IaC) · GitHub Actions(CI/CD) · Artifact Registry
               · Prometheus+Grafana(시스템 관측) · Langfuse(LLM 관측)
```

### 서비스 (K8s Deployment)
1. **`api`** (FastAPI 모듈러 모놀리식) — 동기 요청 처리. 기능은 모듈로 구성:
   탐색/추천, 워크스페이스, (백로그) 업무관리, 인증. 무거운 LLM 작업은 Redis 큐로 위임.
2. **`agent-worker`** — 큐에서 작업을 꺼내 LLM 에이전트 실행. MCP로 도구 사용.
   결과를 App DB에 기록. **상태 없음(stateless)** → 수평 복제(스케일) 가능.
3. **`mcp-server`** — 에이전트가 쓰는 도구(연장통)를 MCP 프로토콜로 노출.
4. **`frontend`** — React SPA.

### 데이터스토어
- **App DB** (Cloud SQL Postgres + `pgvector`): 우리가 만드는 데이터 + RAG 임베딩.
- **공모전 DB** (기존, 읽기 전용): 적재 파이프라인이 채우는 upstream 소스.
- **읽기 소스와 앱 데이터를 섞지 않는다** (남의 창고 ↔ 우리 장부 분리).

### 설계 원칙
- **동기/비동기 분리**: 가벼운 조회는 즉시, 무거운 LLM은 큐+워커 비동기.
- **에이전트 stateless**: 필요한 상태는 전부 DB. 워커 복제해도 안 꼬임.
- **모듈러 모놀리식**: 기능은 한 앱의 모듈로. 서비스 폭증(마이크로서비스 지옥) 회피.

## 3. 데이터 흐름

**가벼운 요청 (즉시 응답)**
```
사용자 → api → App DB / 공모전 DB 읽기 → 즉시 응답
예) 마감 임박 공모전 목록, 우리 팀 워크스페이스 보기
```

**무거운 AI 요청 (비동기)**
```
사용자 → api가 "작업 접수" 응답 + Redis에 작업 투입
       → agent-worker가 꺼냄 → mcp-server 도구로 검색·추론 → 결과를 App DB에 저장
       → 프론트가 폴링(또는 스트리밍)으로 결과 표시
예) 나한테 맞는 공모전 추천
```

### App DB 핵심 테이블
| 테이블 | 내용 |
|---|---|
| `users` | 구글 OAuth 회원, 관심분야·스킬(개인화용) |
| `workspaces` | 팀 단위 작업 공간 |
| `workspace_members` | 멤버십(역할 포함) |
| `agent_jobs` | AI 작업 요청·상태·결과(큐 추적) |
| `recommendations` | 추천 결과 이력(추후 eval에 사용), 워크스페이스에 연결 |
| `embeddings` (pgvector) | 공모전 텍스트 임베딩 → RAG 검색용 |
| `tasks` *(백로그)* | 업무관리용. 스키마는 미리 준비, 기능은 후순위 |

공모전 DB는 기존 스키마 그대로 읽기. `agent-worker`(또는 보조 잡)가 공모전 텍스트를
주기적으로 임베딩해 `embeddings`에 채워 RAG를 준비한다.

## 4. 에이전트 설계 (MCP 기반)

`agent-worker`가 "공모전 추천" 작업을 처리한다. MCP를 처음부터 도입해 도구 사용
(tool-use) 패턴을 학습한다.

**MCP 도구 (mcp-server가 노출하는 연장통)**
| 도구 | 하는 일 |
|---|---|
| `search_competitions` | 공모전 DB 조건/키워드/마감 검색 |
| `get_competition_detail` | 특정 공모전 상세 조회 |
| `semantic_search` | pgvector 의미 기반 유사 공모전 검색(RAG) |
| `web_search` | 외부 최신 정보 보강 (선택) |
| `create_tasks` | (백로그) 계획을 워크스페이스 태스크로 생성 |

**추천 처리 흐름**
```
유저 관심사·스킬 읽기 → semantic_search(RAG)로 후보 추림
  → Gemini가 "왜 이게 너한테 맞는지" 이유 생성 → recommendations 저장
```

- **LLM**: Gemini (Vertex AI). MCP 도구 사용은 Gemini function calling으로 연동.
  GCP 네이티브라 인증·과금·관측이 GKE/클라우드 스택과 자연스럽게 통합된다.
- **RAG**: 별도 벡터DB 없이 `pgvector`(App DB 내장). 임베딩도 Vertex AI 임베딩 모델
  사용. 학습 초반 단순성 확보.
- **eval(백로그)**: 유저의 추천 클릭/저장 로그 → "추천 적중률" 지표화(MLOps 학습 포인트).

## 5. MLOps / 배포 레이어 (핵심 학습 구간)

5단계로 쌓는다.

1. **포장 — Docker**: 서비스마다 `Dockerfile`. "내 컴퓨터선 됨" 문제 제거.
2. **보관 — Artifact Registry**: 이미지 저장소.
3. **올리기 — GKE + Helm**: K8s 핵심 개념 학습 —
   `Deployment`, `Service`, `Ingress`, `ConfigMap/Secret`, `HPA`(백로그). Helm으로 배포 템플릿화.
4. **자동화 — GitHub Actions**: `푸시 → 테스트 → 빌드 → Artifact Registry 푸시 → GKE 배포`.
   `.github/workflows/`에 작성.
5. **인프라 코드화 — Terraform**: GKE·Cloud SQL·네트워크를 코드로 생성/삭제.
   "쓸 때만 켜고 끄기"로 비용 절감 + IaC 학습.

**관측 (두 종류)**
| 종류 | 도구 | 관측 대상 |
|---|---|---|
| 시스템 | Prometheus + Grafana | CPU·메모리·요청수·에러율·워커 스케일 |
| LLM | Langfuse | 프롬프트·응답·토큰비용·지연·추천 품질 |

LLM 관측이 AI Engineer를 일반 백엔드와 가르는 지점이다.

## 6. 비용

- **GCP 신규 무료 크레딧 $300(90일)**로 학습 기간 GKE 비용 대부분 커버.
- **평소 로컬 kind(무료) 개발 → GKE는 클라우드 실습 시에만 `terraform apply/destroy`**.
- Spot 노드 + 최소 머신(e2-small)으로 노드값 ~70% 절감.
- 변동비는 사실상 Gemini(Vertex AI) 토큰비뿐 (개발 수준이면 미미, 크레딧 내 커버).
- **결론: 월 1~2만원 안쪽, 크레딧 활용 시 사실상 0원.**

## 7. 범위 (3주 / 파트타임 ~30h 기준)

> 시간이 고정이므로 기능을 넣으면 다른 게 밀린다. 1차 목표(MLOps 학습)를 지키되
> 제품은 "추천 + 최소 워크스페이스"로 좁힌다. 잘라낸 기능은 구조상 나중에 붙이기
> 쉽도록 모듈·테이블을 미리 설계한다.

### 🔴 반드시 (Must)
1. 뼈대: FastAPI `api` + Postgres + 구글 OAuth 로그인 + 관심사 입력
2. 공모전 추천 기능 (pgvector RAG + Gemini/Vertex AI)
3. `agent-worker` + `mcp-server` + Redis 큐
4. 최소 워크스페이스 (팀 생성·멤버 초대·추천을 팀에 저장)
5. Docker 컨테이너화 → 로컬 kind K8s + Helm
6. GitHub Actions CI/CD (푸시→테스트→빌드→배포)

### 🟡 되면 보너스 (3주차 여유 시)
7. Terraform → GKE 실제 클라우드 배포
8. 기본 관측 (Grafana 대시보드 1개 + Langfuse LLM 추적)

### ⚪ 4주차 이후 백로그 (구조는 미리 준비)
- 업무관리(태스크) · 계획 에이전트 · HPA 오토스케일 · eval 파이프라인

### 주차별 로드맵
- **1주차**: 뼈대 + 추천(RAG+LLM) + Docker + 로컬 kind/Helm
- **2주차**: agent-worker + mcp-server + Redis + 최소 워크스페이스 + GitHub Actions CI/CD
- **3주차**: (보너스) Terraform+GKE 배포 + 기본 관측 / 또는 1~2주차 마무리·QA 버퍼

### 리소스/리스크
- 파트타임 ~30h 기준 🔴(로컬까지 풀 루프)가 현실적 완성 목표.
- 🟡(GKE+관측)는 **클라우드 디버깅 시간**(IAM 권한 등)에 따라 3주차에 될 수도/밀릴 수도.
- 🔴만 완성해도 "컨테이너→K8s→CI/CD→돌아가는 AI 에이전트 + 팀 워크스페이스"라
  MLOps 포트폴리오로 충분히 강하다.

## 8. 테스트 / 에러 처리 (요지)
- **단위/통합 테스트**: 추천 로직·MCP 도구·API 엔드포인트. CI에서 자동 실행.
- **에이전트 작업 실패 처리**: `agent_jobs` 상태(`queued/running/done/failed`)로 추적,
  실패 시 재시도/백오프, 사용자에게 명확한 상태 노출.
- **외부 의존성(LLM/공모전 DB)**: 타임아웃·재시도·폴백, Langfuse로 실패 추적.
