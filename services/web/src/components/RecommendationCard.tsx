import type { Recommendation } from "../api/types";

interface RecommendationCardProps {
  recommendation: Recommendation;
  /** 선택 토글(워크스페이스 공유용). 미지정 시 선택 UI 숨김. */
  selected?: boolean;
  onToggle?: (competitionId: number) => void;
}

export function RecommendationCard({
  recommendation,
  selected,
  onToggle,
}: RecommendationCardProps) {
  const { competition_id, title, reason, score } = recommendation;
  return (
    <article className="card reco-card">
      <header className="reco-card__head">
        <h3 className="reco-card__title">{title}</h3>
        {typeof score === "number" && (
          <span className="badge" title="유사도 점수">
            {score.toFixed(2)}
          </span>
        )}
      </header>
      <p className="reco-card__reason">{reason}</p>
      {onToggle && (
        <label className="reco-card__select">
          <input
            type="checkbox"
            checked={Boolean(selected)}
            onChange={() => onToggle(competition_id)}
          />
          팀에 공유 선택
        </label>
      )}
    </article>
  );
}
