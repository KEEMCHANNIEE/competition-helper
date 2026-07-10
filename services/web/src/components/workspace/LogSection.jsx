import { FiActivity, FiUser } from "react-icons/fi";

// 실행 로그 content 는 "제목: ...\n요약: ...\n키워드: #a #b" 텍스트다(백엔드 _handle_log).
// 화면 표시용으로 파싱한다. 형식이 어긋나면 전체를 요약으로 보여준다(견고성).
function parseLog(content) {
  const lines = (content || "").split("\n");
  let title = "작업 기록";
  let summary = "";
  let keywords = [];
  let matchedFormat = false;
  for (const line of lines) {
    if (line.startsWith("제목:")) {
      title = line.slice(3).trim();
      matchedFormat = true;
    } else if (line.startsWith("요약:")) {
      summary = line.slice(3).trim();
      matchedFormat = true;
    } else if (line.startsWith("키워드:")) {
      keywords = line
        .slice(4)
        .trim()
        .split(/\s+/)
        .map((k) => k.replace(/^#/, ""))
        .filter(Boolean);
      matchedFormat = true;
    } else if (summary && line.trim()) {
      summary += " " + line.trim(); // 요약이 여러 줄로 이어질 때
    }
  }
  if (!matchedFormat) summary = content;
  return { title, summary, keywords };
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export default function LogSection({ logs }) {
  return (
    <div>
      <div className="ws-tasks-header">
        <div className="ws-section-title" style={{ marginBottom: 0 }}>실행 로그</div>
      </div>

      {(!logs || logs.length === 0) ? (
        <div className="ws-card" style={{ padding: 28, textAlign: "center", color: "#9CA3AF" }}>
          아직 기록된 실행 로그가 없어요.<br />
          채팅에서 <b>"오늘 작업한 거 워크스페이스에 저장해줘"</b> 라고 하면 자동으로 요약해 기록돼요.
        </div>
      ) : (
        <div className="ws-insights-list">
          {logs.map((log) => {
            const { title, summary, keywords } = parseLog(log.content);
            return (
              <div key={log.id} className="ws-insight-card" style={{ cursor: "default" }}>
                {/* 헤더: 작성자 · 날짜 · 할 일 제목 */}
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
                  <span className="ws-insight-author"><FiUser size={11} /> {log.author}</span>
                  <span style={{ color: "#D1D5DB", fontSize: 12 }}>·</span>
                  <span className="ws-insight-card-date">{formatDate(log.created_at)}</span>
                  <span style={{ color: "#D1D5DB", fontSize: 12 }}>·</span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 13, fontWeight: 700, color: "#2563EB" }}>
                    <FiActivity size={12} /> {title}
                  </span>
                </div>

                <div style={{ fontSize: 13.5, color: "#374151", lineHeight: 1.7 }}>{summary}</div>

                {keywords.length > 0 && (
                  <div className="ws-chip-list" style={{ marginTop: 10 }}>
                    {keywords.map((k) => (
                      <span key={k} className="ws-chip">#{k}</span>
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
