# 팀 온보딩

공모전 추천 + 대화 기반 계획·워크스페이스 서비스.

---

## 1. 모두 먼저 읽기

1. `docs/BEGINNER-GUIDE.md` — 전체 구조 개요
2. `docs/DESIGN-V2-대화형에이전트.md` — 우리가 최종적으로 만들 것

## 2. 공통 규칙 (꼭 지킬 것)

- **`libs/contest_helper_core/` 는 건드리지 마라.** 모두가 공유하는 약속(데이터 모양·DB 연결)이라, 여기 바꾸면 전원이 깨진다.
- **자기 폴더만 작업한다.**
- 각 빈칸엔 `raise NotImplementedError` 와 **실패하는 테스트**가 있다. 그 테스트가 원하는 대로 코드를 채워서 **테스트를 통과(초록불)시키면 그 과제 완료.**

## 3. 역할별 안내

### 🟦 프론트 담당 — `services/web/`
- 읽을 것: `docs/FRONTEND-API.md` (이거 하나면 됨)
- 할 일: 화면 만들기 (로그인 / 관심사 입력 / 채팅 / 추천 / 계획)
- 핵심: 백엔드와는 **API(주소 + JSON)로만** 연결된다. 명세서대로 호출하면 붙는다. `services/web/` 는 참고용 예시(그대로 써도, 새로 만들어도 됨).

### 🟩 백엔드 + 배포 담당 — `services/api/`, `deploy/`, `.github/`
- 읽을 것: `docs/TECH-SPEC.md`, `docs/FILE-MAP.md`
- 할 일:
  - `services/api/` 마무리 — 구글 OAuth 실제 키 연동, 공모전 SQL이 실제 Supabase 스키마와 맞는지 확인
  - `deploy/` 로 띄우기 — `docker compose up` 으로 전체 기동, 이후 kind/Helm
- 핵심: 공모전 DB(Supabase) 연결은 `.env` 의 `COMPETITION_DB_URL`.

### 🟨 AI 담당 (2명) — `services/worker/`
- 읽을 것: `services/worker/src/worker/README.md` → `docs/AGENT-GUIDE.md`
- 할 일: `services/worker/` 의 **빈칸 채우기** (실패 테스트를 초록불로)
- 분담 제안:
  - A: `agent.py`(추천·대화) + `llm.py`(Gemini)
  - B: `rag.py`(검색) + `embed_job.py`(검색 데이터 준비) + `mcp_tools/`(도구들)

## 4. 시작 방법 (각자)

```bash
# 1. uv 설치 (한 번만)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 의존성 설치 (레포 루트에서)
uv sync

# 3. 자기 영역 테스트 확인
uv run pytest services/worker -v   # (AI 담당 예시)
```
- `.env.example` 를 `.env` 로 복사하고 필요한 값(구글 OAuth, 공모전 DB 등)을 채운다.
- 전체 기동: `docker compose -f deploy/docker-compose.yml up` (docker 설치 필요)

## 5. 한 장 요약

| 담당 | 폴더 | 먼저 읽을 문서 |
|---|---|---|
| 프론트 | `services/web` | `docs/FRONTEND-API.md` |
| 백엔드+배포 | `services/api`, `deploy` | `docs/TECH-SPEC.md`, `docs/FILE-MAP.md` |
| AI (2명) | `services/worker` | `worker/README.md`, `docs/AGENT-GUIDE.md` |
| 모두 | — | `docs/BEGINNER-GUIDE.md`, `DESIGN-V2` |

**기억할 것**: ① `libs/contest_helper_core` 는 건들지 마라 ② 자기 폴더만 ③ 빈칸 채워 테스트 통과시켜라

---

## 참고: 전체 문서 목록
- `docs/BEGINNER-GUIDE.md` — 전체 구조 개요
- `docs/DESIGN-V2-대화형에이전트.md` — 최신 비전(대화형 코파일럿)
- `docs/PROJECT-OVERVIEW.md` — 구획·과제·마일스톤
- `docs/PROJECT-STRUCTURE.md` — 폴더·역할 분담
- `docs/TECH-SPEC.md` — 기술 스택·엔드포인트·환경변수
- `docs/FILE-MAP.md` — 파일별 존재 이유
- `docs/AGENT-GUIDE.md` — 에이전트 구현 예시 코드
- `docs/FRONTEND-API.md` — 프론트 연동 API 명세
- `services/worker/src/worker/README.md` — worker 개괄·동작
