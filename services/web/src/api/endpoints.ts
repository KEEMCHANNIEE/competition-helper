// 엔드포인트별 타입드 함수. 페이지/훅은 여기만 호출한다.
import { apiClient } from "./client";
import type {
  Competition,
  JobResult,
  MeUpdate,
  Recommendation,
  RecommendAccepted,
  User,
  Workspace,
  WorkspaceDetail,
  WorkspaceMember,
} from "./types";

// --- 인증 ---

/** 구글 로그인 시작: 백엔드 리다이렉트 엔드포인트로 브라우저를 이동시킨다. */
export function login(): void {
  const base =
    (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";
  window.location.href = `${base}/auth/google/login`;
}

/** 내 정보. 미로그인 시 ApiError(status=401). */
export function getMe(signal?: AbortSignal): Promise<User> {
  return apiClient.get<User>("/me", signal);
}

/** 관심사·스킬 갱신. 빈 배열 허용. */
export function updateMe(update: MeUpdate): Promise<User> {
  return apiClient.patch<User>("/me", update);
}

// --- 공모전 ---

export function listCompetitions(limit = 20): Promise<Competition[]> {
  return apiClient.get<Competition[]>(`/competitions?limit=${limit}`);
}

// --- 추천 ---

/** 추천 요청 → 202 {job_id}. */
export function requestRecommend(limit = 5): Promise<RecommendAccepted> {
  return apiClient.post<RecommendAccepted>("/recommend", { limit });
}

/** 추천 작업 폴링. */
export function getRecommendJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobResult> {
  return apiClient.get<JobResult>(`/recommend/${jobId}`, signal);
}

// --- 워크스페이스 ---

export function createWorkspace(name: string): Promise<Workspace> {
  return apiClient.post<Workspace>("/workspaces", { name });
}

export function inviteMember(
  workspaceId: number,
  email: string,
  role = "member",
): Promise<WorkspaceMember> {
  return apiClient.post<WorkspaceMember>(`/workspaces/${workspaceId}/members`, {
    email,
    role,
  });
}

export function attachRecommendations(
  workspaceId: number,
  recommendationIds: number[],
): Promise<{ attached: number }> {
  return apiClient.post<{ attached: number }>(
    `/workspaces/${workspaceId}/recommendations`,
    { recommendation_ids: recommendationIds },
  );
}

export function getWorkspace(workspaceId: number): Promise<WorkspaceDetail> {
  return apiClient.get<WorkspaceDetail>(`/workspaces/${workspaceId}`);
}

// 재노출(편의용)
export type { Recommendation };
