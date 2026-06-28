// 모든 백엔드 호출이 통과하는 단일 fetch 래퍼.
// base = import.meta.env.VITE_API_BASE (기본 "/api"). 페이지는 절대 fetch 를 직접 쓰지 않는다.

const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

/** API 가 비-2xx 를 반환했을 때 던지는 에러. status 로 분기 가능(예: 401). */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: payload,
      credentials: "include", // 세션 쿠키 동봉
      signal,
    });
  } catch (err) {
    // 네트워크 단절 등 — status 0 으로 정규화.
    throw new ApiError(0, (err as Error).message || "네트워크 오류");
  }

  if (!res.ok) {
    const errBody = await safeParse(res);
    const detail =
      (isRecord(errBody) && typeof errBody.detail === "string"
        ? errBody.detail
        : undefined) ?? `요청 실패 (${res.status})`;
    throw new ApiError(res.status, detail, errBody);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await safeParse(res)) as T;
}

async function safeParse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export const apiClient = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: "POST", body, signal }),
  patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: "PATCH", body, signal }),
};
