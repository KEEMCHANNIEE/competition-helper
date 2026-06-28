// keenee_core/schemas.py 의 DTO 와 1:1 로 일치시킨 TypeScript 타입.
// 필드 이름/널 허용 여부를 백엔드 계약과 정확히 맞춘다.

/** 추천 작업 상태. JobStatus(str, Enum) 과 동일. */
export type JobStatus = "queued" | "running" | "done" | "failed";

/** 공모전 1건 — CompetitionOut. */
export interface Competition {
  id: number;
  title: string;
  deadline: string | null; // date (ISO yyyy-mm-dd) | null
  organizer: string | null;
  url: string | null;
}

/** 추천 결과 1건 — RecommendationOut. */
export interface Recommendation {
  competition_id: number;
  title: string;
  reason: string;
  score: number | null;
}

/** 폴링 응답 — JobResultOut (GET /recommend/{job_id}). */
export interface JobResult {
  job_id: string;
  status: JobStatus;
  results: Recommendation[];
  error: string | null;
}

/** POST /recommend 의 202 응답. */
export interface RecommendAccepted {
  job_id: string;
}

/** 로그인 사용자 — UserOut (GET/PATCH /me). */
export interface User {
  id: number;
  email: string;
  name: string;
  interests: string[];
  skills: string[];
  created_at: string | null;
}

/** PATCH /me 입력. 둘 다 선택, 빈 배열 허용. */
export interface MeUpdate {
  interests?: string[];
  skills?: string[];
}

/** 워크스페이스 — WorkspaceOut. */
export interface Workspace {
  id: number;
  name: string;
  owner_id: number;
  created_at: string | null;
}

/** 워크스페이스 멤버 — MemberOut. */
export interface WorkspaceMember {
  id: number;
  workspace_id: number;
  user_id: number;
  role: string;
}

/** 워크스페이스에 저장된 추천 1건 — RecommendationItem. */
export interface WorkspaceRecommendation {
  id: number;
  competition_id: number;
  title: string;
  reason: string;
  score: number | null;
}

/** 워크스페이스 상세 — WorkspaceDetailOut. */
export interface WorkspaceDetail extends Workspace {
  recommendations: WorkspaceRecommendation[];
}
