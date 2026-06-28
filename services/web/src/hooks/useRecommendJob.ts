import { useCallback, useEffect, useRef, useState } from "react";

import { getRecommendJob, requestRecommend } from "../api/endpoints";
import type { JobResult, Recommendation } from "../api/types";

const POLL_INTERVAL_MS = 2000;

export type RecommendPhase = "idle" | "requesting" | "polling" | "done" | "failed";

export interface UseRecommendJobResult {
  phase: RecommendPhase;
  jobId: string | null;
  results: Recommendation[];
  error: string | null;
  /** 추천 요청 시작: POST /recommend → 폴링 시작. */
  start: (limit?: number) => Promise<void>;
  /** 상태 초기화(폴링 중지). */
  reset: () => void;
}

/**
 * 추천 폴링 훅.
 * 1. requestRecommend() → {job_id}
 * 2. setInterval 로 getRecommendJob(job_id) 를 2초마다 조회
 * 3. status === 'done' → results 노출, 'failed' → error, 그 외 → 폴링 유지
 * 언마운트/리셋 시 interval 정리.
 */
export function useRecommendJob(): UseRecommendJobResult {
  const [phase, setPhase] = useState<RecommendPhase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [results, setResults] = useState<Recommendation[]>([]);
  const [error, setError] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 언마운트 후 setState 방지.
  const mountedRef = useRef(true);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const applyResult = useCallback(
    (job: JobResult) => {
      if (!mountedRef.current) return;
      if (job.status === "done") {
        setResults(job.results);
        setError(null);
        setPhase("done");
        clearTimer();
      } else if (job.status === "failed") {
        setError(job.error ?? "추천 생성에 실패했습니다.");
        setPhase("failed");
        clearTimer();
      } else {
        // queued / running → 계속 폴링.
        setPhase("polling");
      }
    },
    [clearTimer],
  );

  const poll = useCallback(
    async (id: string) => {
      try {
        const job = await getRecommendJob(id);
        applyResult(job);
      } catch (err) {
        if (!mountedRef.current) return;
        setError((err as Error).message || "상태 조회에 실패했습니다.");
        setPhase("failed");
        clearTimer();
      }
    },
    [applyResult, clearTimer],
  );

  const start = useCallback(
    async (limit = 5) => {
      clearTimer();
      setResults([]);
      setError(null);
      setJobId(null);
      setPhase("requesting");
      try {
        const accepted = await requestRecommend(limit);
        if (!mountedRef.current) return;
        setJobId(accepted.job_id);
        setPhase("polling");
        // 즉시 한 번 조회한 뒤 주기 폴링.
        await poll(accepted.job_id);
        if (!mountedRef.current) return;
        if (timerRef.current === null) {
          timerRef.current = setInterval(() => {
            void poll(accepted.job_id);
          }, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (!mountedRef.current) return;
        setError((err as Error).message || "추천 요청에 실패했습니다.");
        setPhase("failed");
      }
    },
    [clearTimer, poll],
  );

  const reset = useCallback(() => {
    clearTimer();
    setPhase("idle");
    setJobId(null);
    setResults([]);
    setError(null);
  }, [clearTimer]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer();
    };
  }, [clearTimer]);

  return { phase, jobId, results, error, start, reset };
}
