# 프론트엔드 API 연동 명세서

- 작성일: 2026-06-29
- 대상: **프론트엔드 담당자** (어떤 프레임워크/레포든 무관 — 이 명세대로 호출하면 백엔드에 붙는다)
- 백엔드: FastAPI. 기본 포트 `8000`.

---

## 0. 기본 규칙

- **Base URL**: 개발 시 프론트에서 `/api/*` 로 호출하고 `/api` → `http://localhost:8000` 로 프록시(예: Vite proxy)하거나, 직접 `http://localhost:8000` 사용.
- **데이터 형식**: 요청/응답 모두 JSON (단, 로그인은 리다이렉트).
- **인증**: **httponly 세션 쿠키**(`contest-helper_session`). 로그인 후 자동 설정됨.
  → 모든 API 호출 시 **쿠키 포함** 필요. 같은 도메인(프록시)이면 자동, 교차 도메인이면 `fetch(..., { credentials: "include" })`.
- **인증 실패**: 로그인 안 된 상태로 보호된 API 호출 시 **401**. → 로그인 페이지로 보내면 됨.
- **에러 형식**: FastAPI 표준 `{"detail": "메시지"}` + HTTP 상태코드(400/401/404 등).

---

## 1. 인증 (Auth)

| 메서드·경로 | 설명 |
|---|---|
| `GET /auth/google/login` | **구글 로그인 시작.** 브라우저를 이 주소로 이동시키면 됨: `window.location.href = "/api/auth/google/login"`. 구글 동의 후 자동으로 콜백→세션쿠키 설정→`/` 로 리다이렉트. |
| `GET /auth/google/callback` | (백엔드 내부용. 프론트가 직접 호출 안 함) |
| `GET /me` | 로그인 사용자 정보. 미로그인 시 401. |
| `PATCH /me` | 관심사·스킬 수정. |

**`GET /me` 응답 (UserOut)**
```json
{ "id": 1, "email": "a@b.com", "name": "민지",
  "interests": ["AI","데이터"], "skills": ["python"],
  "created_at": "2026-06-29T..." }
```
**`PATCH /me` 요청** (둘 다 선택, 빈 배열 허용)
```json
{ "interests": ["AI","데이터"], "skills": ["python"] }
```

> 로그인 여부 판단: 앱 시작 시 `GET /me` 호출 → 200이면 로그인, 401이면 로그인 페이지.

---

## 2. 공모전 목록 (Competitions)

| 메서드·경로 | 설명 |
|---|---|
| `GET /competitions?limit=20` | 진행중 공모전 목록(마감 임박순). limit 1~100. |

**응답: `CompetitionOut[]`**
```json
[{
  "id": 12, "title": "○○ AI 해커톤",
  "organizer": "GC", "host": "○○재단",
  "category": ["AI"], "target": ["대학생"], "keywords": ["해커톤"],
  "start_date": "2026-07-01", "deadline": "2026-07-20",
  "url": "https://...", "poster_url": "https://...",
  "total_prize_amount": 5000000, "participation_type": "팀",
  "status": "진행중"
}]
```
> `deadline` = 마감일, `url` = 외부 홈페이지 링크. 날짜는 `YYYY-MM-DD` 문자열 또는 null.

---

## 3. 추천 (Recommend) — ⭐ 폴링 패턴

추천은 **오래 걸려서** "요청 접수 → 나중에 결과 폴링" 방식이다.

**① 요청: `POST /recommend`**
```json
{ "limit": 5 }
```
**응답 (202)**: `{ "job_id": "abc123" }`

**② 결과 폴링: `GET /recommend/{job_id}`** (status가 `done`/`failed` 될 때까지 ~2초 간격 반복)
```json
{ "job_id": "abc123", "status": "running",
  "results": [], "error": null }
```
`status` = `queued` | `running` | `done` | `failed`.
`done` 이면 `results` 에 추천 목록(`RecommendationOut[]`):
```json
{ "status": "done", "results": [
  { "competition_id": 12, "title": "○○ AI 해커톤",
    "reason": "당신의 AI 관심사와 잘 맞아요...", "score": 0.92 }
]}
```

**프론트 로직**:
```
POST /recommend → job_id 받기
setInterval 2s: GET /recommend/{job_id}
  status==="done"  → results 표시, 폴링 중지
  status==="failed"→ error 표시, 폴링 중지
  그 외           → 로딩 유지
언마운트 시 interval 정리
```

---

## 4. 대화 (Chat) — ⭐ 폴링 패턴 (추천·공부·계획 모두 여기서)

**① 메시지 전송: `POST /chat`**
```json
{ "conversation_id": null, "message": "AI 공모전 추천해줘", "workspace_id": null }
```
- `conversation_id`: 첫 메시지면 `null`(새 대화 생성), 이어가면 받은 id.
- `workspace_id`: 특정 워크스페이스 안에서의 대화면 그 id(선택).

**응답 (202)**: `{ "conversation_id": 7, "job_id": "xyz" }`
→ 이후 호출엔 받은 `conversation_id` 를 계속 사용.

**② 대화 폴링: `GET /chat/{conversation_id}`** (`pending` 이 false 될 때까지 ~2초 간격)
```json
{ "conversation_id": 7, "pending": true,
  "messages": [
    { "role": "user", "content": "AI 공모전 추천해줘" }
  ], "error": null }
```
- `pending: true` = 에이전트가 아직 답하는 중(마지막이 user 메시지).
- `pending: false` = 답 완료. `messages` 맨 끝에 `role: "assistant"` 답이 들어있음.

**프론트 로직**:
```
send(text):
  POST /chat {conversation_id, message:text} → conversation_id 저장
  setInterval 2s: GET /chat/{conversation_id}
    pending===false → messages 갱신(assistant 답 표시), 폴링 중지
화면: user(오른쪽) / assistant(왼쪽) 말풍선
```

---

## 5. 워크스페이스 & 계획(할 일)

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /workspaces` | `{ "name":"○○ 해커톤팀", "contest_id": 12 }` | 201 `WorkspaceOut` |
| `POST /workspaces/{id}/members` | `{ "email":"a@b.com", "role":"member" }` | 201 `MemberOut` |
| `POST /workspaces/{id}/recommendations` | `{ "recommendation_ids":[1,2] }` | `{ "attached": 2 }` |
| `GET /workspaces/{id}` | — | `WorkspaceDetailOut` (워크스페이스 + 저장된 추천) |
| `GET /workspaces/{id}/tasks` | — | `TaskOut[]` (계획·할 일, week_no 순) |
| `POST /workspaces/{id}/tasks` | `TaskIn` | 201 `TaskOut` (수동 추가) |

**`WorkspaceOut`** `{ "id":3, "name":"...", "owner_id":1, "contest_id":12, "created_at":"..." }`
**`WorkspaceDetailOut`** = WorkspaceOut + `"recommendations": [{id, competition_id, title, reason, score}]`
**`TaskOut`** (계획 화면용)
```json
{ "id":1, "title":"자료조사", "description":"논문 5개 읽기",
  "status":"todo", "assignee_id":2, "week_no":1 }
```
**`TaskIn`** (수동 추가) `{ "title":"...", "description":"...", "assignee_id":2, "week_no":1 }`

> 계획 화면은 `GET /workspaces/{id}/tasks` 를 받아 **week_no 별로 묶어** 표시하면 됨(주차별 할 일 + 담당자).

---

## 6. 타입 정의 (TypeScript, 복붙용)

```typescript
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface User {
  id: number; email: string; name: string;
  interests: string[]; skills: string[]; created_at: string | null;
}
export interface Competition {
  id: number; title: string;
  organizer: string | null; host: string | null;
  category: string[]; target: string[]; keywords: string[];
  start_date: string | null; deadline: string | null;
  url: string | null; poster_url: string | null;
  total_prize_amount: number | null;
  participation_type: string | null; status: string | null;
}
export interface Recommendation {
  competition_id: number; title: string; reason: string; score: number | null;
}
export interface JobResult {
  job_id: string; status: JobStatus;
  results: Recommendation[]; error: string | null;
}
export interface Message { role: "user" | "assistant"; content: string; }
export interface ChatState {
  conversation_id: number; pending: boolean;
  messages: Message[]; error: string | null;
}
export interface Workspace {
  id: number; name: string; owner_id: number;
  contest_id: number | null; created_at: string | null;
}
export interface Task {
  id: number; title: string; description: string | null;
  status: string; assignee_id: number | null; week_no: number | null;
}
```

---

## 7. 핵심 요약 (프론트가 기억할 것)
1. **인증** = 쿠키 자동. 로그인은 `/api/auth/google/login` 으로 브라우저 이동. 상태는 `GET /me`.
2. **추천·채팅** = "POST로 시작 → GET으로 폴링"(2초 간격). 즉시 안 나옴.
3. **계획** = `GET /workspaces/{id}/tasks` 를 week_no 별로 묶어 표시.
4. 데이터 모양은 위 TS 타입과 1:1. (백엔드 계약 = `contest_helper_core/schemas.py`)

> 참고용 예시 구현: `services/web/`(우리가 만든 React 화면). 그대로 쓰거나 참고만 해도 됨.
