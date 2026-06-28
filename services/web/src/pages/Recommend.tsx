import { useState } from "react";

import { useRecommendJob } from "../hooks/useRecommendJob";
import { Loading } from "../components/Loading";
import { ErrorBanner } from "../components/ErrorBanner";
import { RecommendationCard } from "../components/RecommendationCard";

export function Recommend() {
  const { phase, jobId, results, error, start, reset } = useRecommendJob();
  const [limit, setLimit] = useState(5);

  const busy = phase === "requesting" || phase === "polling";

  return (
    <section className="page">
      <h1>공모전 추천</h1>
      <p className="muted">
        관심사·스킬을 기반으로 AI 가 어울리는 공모전을 찾아드려요. 결과 생성에는
        잠시 시간이 걸립니다.
      </p>

      <div className="toolbar">
        <label className="field field--inline">
          <span>추천 개수</span>
          <input
            type="number"
            min={1}
            max={50}
            value={limit}
            disabled={busy}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          className="btn btn--primary"
          disabled={busy}
          onClick={() => void start(limit)}
        >
          {busy ? "생성 중..." : "추천 받기"}
        </button>
        {(phase === "done" || phase === "failed") && (
          <button type="button" className="btn" onClick={reset}>
            초기화
          </button>
        )}
      </div>

      {phase === "requesting" && <Loading label="요청을 보내는 중..." />}
      {phase === "polling" && (
        <Loading
          label={`추천을 생성하고 있어요${jobId ? ` (job: ${jobId})` : ""}...`}
        />
      )}

      {phase === "failed" && error && (
        <ErrorBanner message={error} onRetry={() => void start(limit)} />
      )}

      {phase === "done" && results.length === 0 && (
        <p className="muted">조건에 맞는 추천 결과가 없습니다.</p>
      )}

      {results.length > 0 && (
        <div className="reco-list">
          {results.map((r) => (
            <RecommendationCard key={r.competition_id} recommendation={r} />
          ))}
        </div>
      )}
    </section>
  );
}
