import { FiBarChart2, FiPlus, FiAlertCircle } from "react-icons/fi";

// 주간 리포트 content 형식(백엔드 규약):
//   N주차 주간 리포트
//   전체 진행률: 63% (5/8 완료)
//   [팀원별 진행률]
//   - 동영 (팀장): 100% (2/2)
//   [미완료]
//   - 유진: 데이터 정리
function parseReport(content) {
  const lines = (content || "").split("\n");
  const title = lines[0] || "주간 리포트";
  let overall = null;
  const members = [];
  const incomplete = [];
  let section = null;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("전체 진행률:")) {
      const m = line.match(/(\d+)%\s*\((\d+)\/(\d+)/);
      if (m) overall = { percent: +m[1], done: +m[2], total: +m[3] };
    } else if (line.startsWith("[팀원별")) {
      section = "members";
    } else if (line.startsWith("[미완료")) {
      section = "incomplete";
    } else if (line.startsWith("- ") && section === "members") {
      const m = line.match(/^- (.+): (\d+)% \((\d+)\/(\d+)\)/);
      if (m) members.push({ name: m[1], percent: +m[2], done: +m[3], total: +m[4] });
    } else if (line.startsWith("- ") && section === "incomplete") {
      const idx = line.indexOf(": ");
      if (idx > 0) incomplete.push({ name: line.slice(2, idx), detail: line.slice(idx + 2) });
      else incomplete.push({ name: "", detail: line.slice(2) });
    }
  }
  return { title, overall, members, incomplete };
}

function barColor(p) {
  if (p >= 100) return "#16A34A";
  if (p >= 50) return "#2563EB";
  if (p > 0) return "#D97706";
  return "#DC2626";
}

function ProgressBar({ percent }) {
  return (
    <div style={{ flex: 1, height: 8, background: "#EEF2F7", borderRadius: 999, overflow: "hidden" }}>
      <div style={{ width: `${percent}%`, height: "100%", background: barColor(percent), borderRadius: 999, transition: "width .3s" }} />
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export default function ReportSection({ reports, onGenerate, generating }) {
  return (
    <div>
      <div className="ws-tasks-header">
        <div className="ws-section-title" style={{ marginBottom: 0 }}>주간 리포트</div>
        <button className="ws-btn-primary" onClick={onGenerate} disabled={generating}>
          <FiPlus size={14} /> {generating ? "생성 중..." : "주간 리포트 생성"}
        </button>
      </div>

      {(!reports || reports.length === 0) ? (
        <div className="ws-card" style={{ padding: 28, textAlign: "center", color: "#9CA3AF" }}>
          아직 생성된 주간 리포트가 없어요.<br />
          위 <b>주간 리포트 생성</b> 버튼을 누르거나, 채팅에서 <b>"주간 리포트 생성해줘"</b> 라고 하면 만들어져요.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {reports.map((r) => {
            const { title, overall, members, incomplete } = parseReport(r.content);
            return (
              <div key={r.id} className="ws-card" style={{ padding: 20 }}>
                {/* 헤더 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
                  <FiBarChart2 size={16} color="#2563EB" />
                  <span style={{ fontSize: 15, fontWeight: 800, color: "#111827" }}>{title}</span>
                  <span style={{ marginLeft: "auto", fontSize: 12, color: "#9CA3AF" }}>{formatDate(r.created_at)} 생성</span>
                </div>

                {/* 전체 진행률 */}
                {overall && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                      <span style={{ fontWeight: 600, color: "#374151" }}>전체 진행률</span>
                      <span style={{ fontWeight: 700, color: barColor(overall.percent) }}>
                        {overall.percent}% ({overall.done}/{overall.total})
                      </span>
                    </div>
                    <ProgressBar percent={overall.percent} />
                  </div>
                )}

                {/* 팀원별 진행률 */}
                {members.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: incomplete.length ? 16 : 0 }}>
                    {members.map((m) => (
                      <div key={m.name} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <span style={{ width: 120, fontSize: 13, color: "#374151", flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
                        <ProgressBar percent={m.percent} />
                        <span style={{ width: 64, textAlign: "right", fontSize: 12.5, fontWeight: 600, color: barColor(m.percent), flexShrink: 0 }}>
                          {m.percent}% ({m.done}/{m.total})
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* 미완료 */}
                {incomplete.length > 0 && (
                  <div style={{ background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 8, padding: "10px 14px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 700, color: "#B91C1C", marginBottom: 6 }}>
                      <FiAlertCircle size={13} /> 미완료
                    </div>
                    {incomplete.map((it, i) => (
                      <div key={i} style={{ fontSize: 13, color: "#7F1D1D", margin: "2px 0" }}>
                        {it.name && <b>{it.name}</b>}{it.name ? " — " : ""}{it.detail}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
