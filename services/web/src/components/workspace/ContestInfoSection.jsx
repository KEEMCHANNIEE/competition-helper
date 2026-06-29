export default function ContestInfoSection({ contest }) {
  const detail = JSON.parse(contest.description);

  return (
    <div>
      <div className="ws-section-title">Contest Info</div>

      <div className="ws-contest-info-grid">
        {/* 기본 정보 */}
        <div className="ws-card">
          <div className="ws-card-title">기본 정보</div>
          <div>
            <div className="ws-info-row">
              <span className="ws-info-label">공모전명</span>
              <span className="ws-info-value">{contest.title}</span>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">주최</span>
              <span className="ws-info-value">{contest.host}</span>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">카테고리</span>
              <div className="ws-chip-list">
                {contest.category.map((c) => (
                  <span key={c} className="ws-chip">{c}</span>
                ))}
              </div>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">참가 대상</span>
              <span className="ws-info-value">{contest.target}</span>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">접수 기간</span>
              <span className="ws-info-value">{contest.start_date.replace(/-/g, ".")} ~ {contest.end_date.replace(/-/g, ".")}</span>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">결과 발표</span>
              <span className="ws-info-value">
                {detail.schedule.result_announcement.date?.replace(/-/g, ".") || "-"}
                {detail.schedule.result_announcement.note && (
                  <span style={{ color: "#9CA3AF", marginLeft: 6, fontSize: 12 }}>({detail.schedule.result_announcement.note})</span>
                )}
              </span>
            </div>
          </div>
        </div>

        {/* 주제 및 제출 방법 */}
        <div className="ws-card">
          <div className="ws-card-title">주제 및 제출 방법</div>
          <div>
            <div className="ws-info-row">
              <span className="ws-info-label">주제</span>
              <span className="ws-info-value">{detail.content.topic}</span>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">접수 방법</span>
              <span className="ws-info-value">{contest.submission_method}</span>
            </div>
            <div className="ws-info-row">
              <span className="ws-info-label">팀 구성</span>
              <span className="ws-info-value">{detail.participation.team_config}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="ws-contest-info-grid">
        {/* 제출 요구사항 */}
        <div className="ws-card">
          <div className="ws-card-title">제출 요구사항</div>
          <div className="ws-bullet-list">
            {contest.requirements.map((r, i) => (
              <div key={i} className="ws-bullet-item">{r}</div>
            ))}
          </div>
        </div>

        {/* 평가 기준 */}
        <div className="ws-card">
          <div className="ws-card-title">평가 기준</div>
          <div className="ws-eval-list">
            {contest.evaluation_criteria.map((c, i) => (
              <div key={i}>
                <div className="ws-eval-item-top">
                  <span className="ws-eval-name">{c.item}</span>
                  <span className="ws-eval-score">{c.score}점</span>
                </div>
                <div className="ws-eval-bar">
                  <div className="ws-eval-fill" style={{ width: `${c.score}%` }} />
                </div>
                <div className="ws-eval-point">{c.point}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 키워드 + 시상 + 주의사항 */}
      <div className="ws-card" style={{ marginBottom: 16 }}>
        <div className="ws-card-title">키워드</div>
        <div className="ws-chip-list">
          {contest.keywords.map((k) => (
            <span key={k} className="ws-chip">{k}</span>
          ))}
        </div>
      </div>

      {detail.benefits.prizes.length > 0 && (
        <div className="ws-card" style={{ marginBottom: 16 }}>
          <div className="ws-card-title">시상</div>
          <div className="ws-bullet-list">
            {detail.benefits.prizes.map((p, i) => (
              <div key={i} className="ws-bullet-item">{p}</div>
            ))}
          </div>
        </div>
      )}

      {detail.optional.notes && (
        <div className="ws-card">
          <div className="ws-card-title">주의사항</div>
          <div className="ws-notes-box">{detail.optional.notes}</div>
        </div>
      )}
    </div>
  );
}
