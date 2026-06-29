# contest-helper

공모전 추천 + 대화 기반 계획·워크스페이스 서비스. (학습 목적: 컨테이너·K8s·CI/CD·IaC·관측)

## 구성

```
contest-helper/
├── libs/contest_helper_core/   공유 계약 (모델·DB·스키마·설정)
├── services/
│   ├── api/      FastAPI — 인증·공모전·추천·채팅·워크스페이스
│   ├── worker/   에이전트 — 추천·대화·계획 생성 (큐 소비)
│   └── web/      React SPA
├── deploy/       docker-compose · Helm · Terraform
├── .github/      CI/CD
└── docs/         문서
```

## 현재 상태 (1차 = 틀 작업 완료)

- 전체 골격(서비스·DB·큐·배포·CI) 구성 완료.
- 공모전 DB(Supabase, `contests`) 연결 코드 반영 완료.
- 대화형 에이전트(추천/공부/계획) 구조 반영 완료.
- 미구현(다음 단계): `services/worker/` 의 에이전트 로직(빈칸 + 실패 테스트), 실행/검증.

## 로컬 실행

```bash
# 1) 의존성
uv sync                       # (uv 설치: curl -LsSf https://astral.sh/uv/install.sh | sh)

# 2) 환경변수
cp .env.example .env          # COMPETITION_DB_URL(Supabase), GEMINI_API_KEY, 구글 OAuth 등 채우기

# 3) 테스트
uv run pytest -v

# 4) 전체 기동 (Docker 필요)
docker compose -f deploy/docker-compose.yml up
```

접속: api `http://localhost:8000` (`/health`, `/competitions`), web `http://localhost:8080`(또는 compose 설정 포트)

## 역할 분담

| 담당 | 폴더 | 문서 |
|---|---|---|
| 프론트 | `services/web` | `docs/FRONTEND-API.md` |
| 백엔드+배포 | `services/api`, `deploy` | `docs/TECH-SPEC.md`, `docs/FILE-MAP.md` |
| AI (2명) | `services/worker` | `services/worker/src/worker/README.md`, `docs/AGENT-GUIDE.md` |

## 문서

- `docs/TEAM-ONBOARDING.md` — 팀 시작점
- `docs/BEGINNER-GUIDE.md` — 구조 개요
- `docs/DESIGN-V2-대화형에이전트.md` — 설계(비전)
- `docs/PROJECT-OVERVIEW.md` / `docs/PROJECT-STRUCTURE.md` — 구획·역할
- `docs/TECH-SPEC.md` — 기술·엔드포인트·환경변수
- `docs/FILE-MAP.md` — 파일별 역할
- `docs/AGENT-GUIDE.md` — 에이전트 구현 예시
- `docs/FRONTEND-API.md` — 프론트 API 명세
- `docs/GITHUB-PUSH.md` — 깃허브 업로드 방법

## 규칙

- `libs/contest_helper_core/` 는 공유 계약 — 임의 변경 금지.
- App DB / 공모전 DB(읽기 전용) 엔진은 분리.
- 비밀값은 `.env`/Secret 으로만 (`.env` 는 깃에 올리지 않음).
