import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { getMe, login as startLogin } from "../api/endpoints";
import type { User } from "../api/types";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export interface UseAuthResult {
  user: User | null;
  status: AuthStatus;
  /** 구글 로그인 시작(리다이렉트). */
  login: () => void;
  /** /me 재조회. */
  refresh: () => Promise<void>;
}

/**
 * 현재 로그인 사용자 상태를 관리.
 * - getMe() 성공 → authenticated
 * - 401(ApiError) → unauthenticated (인증 가드가 /login 으로 보냄)
 */
export function useAuth(): UseAuthResult {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const refresh = useCallback(async () => {
    setStatus("loading");
    try {
      const me = await getMe();
      setUser(me);
      setStatus("authenticated");
    } catch (err) {
      setUser(null);
      if (err instanceof ApiError && err.status === 401) {
        setStatus("unauthenticated");
      } else {
        // 네트워크 등 기타 오류도 비로그인으로 처리해 가드가 /login 으로 유도.
        setStatus("unauthenticated");
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { user, status, login: startLogin, refresh };
}
