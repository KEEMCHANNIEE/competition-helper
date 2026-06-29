import { useState } from "react";
import { FiPlus, FiX, FiUser } from "react-icons/fi";

function Modal({ insight, onClose }) {
  if (!insight) return null;
  return (
    <div className="ws-modal-overlay" onClick={onClose}>
      <div className="ws-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ws-modal-header">
          <div>
            <div className="ws-modal-title">{insight.title}</div>
            <div className="ws-modal-date" style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span>{insight.createdAt.replace(/-/g, ".")}</span>
              <span style={{ color: "#D1D5DB" }}>·</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <FiUser size={11} />{insight.author}
              </span>
            </div>
          </div>
          <button className="ws-modal-close" onClick={onClose}><FiX size={18} /></button>
        </div>
        <div className="ws-modal-body">
          {insight.content.split("\n").map((line, i) => {
            if (line.startsWith("# ")) return <h2 key={i} style={{ fontSize: 16, fontWeight: 800, color: "#111827", margin: "0 0 14px" }}>{line.slice(2)}</h2>;
            if (line.startsWith("## ")) return <h3 key={i} style={{ fontSize: 14, fontWeight: 700, color: "#374151", margin: "16px 0 8px" }}>{line.slice(3)}</h3>;
            if (line.startsWith("- [ ] ")) return <p key={i} style={{ display: "flex", gap: 8, alignItems: "center", margin: "4px 0", color: "#374151" }}><span style={{ width: 14, height: 14, border: "1.5px solid #D1D5DB", borderRadius: 3, display: "inline-block", flexShrink: 0 }} />{line.slice(6)}</p>;
            if (line.startsWith("- ")) return <p key={i} style={{ paddingLeft: 16, color: "#374151", margin: "4px 0" }}>• {line.slice(2)}</p>;
            if (line === "") return <div key={i} style={{ height: 8 }} />;
            return <p key={i} style={{ color: "#374151", margin: "4px 0", lineHeight: 1.7 }}>{line}</p>;
          })}
        </div>
      </div>
    </div>
  );
}

export default function InsightsSection({ insights, onAddInsight }) {
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [newInsight, setNewInsight] = useState({ title: "", author: "", content: "" });

  const sorted = [...insights].sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  const handleAdd = () => {
    if (!newInsight.title.trim() || !newInsight.content.trim()) return;
    onAddInsight({
      ...newInsight,
      preview: newInsight.content.slice(0, 80) + (newInsight.content.length > 80 ? "..." : ""),
      createdAt: new Date().toISOString().slice(0, 10),
    });
    setNewInsight({ title: "", author: "", content: "" });
    setShowForm(false);
  };

  return (
    <div>
      <div className="ws-tasks-header">
        <div className="ws-section-title" style={{ marginBottom: 0 }}>Insights</div>
        <button className="ws-btn-primary" onClick={() => setShowForm((v) => !v)}>
          <FiPlus size={14} /> New Insight
        </button>
      </div>

      {showForm && (
        <div className="ws-card ws-new-task-form">
          <div className="ws-form-row">
            <input
              className="ws-form-input"
              placeholder="제목"
              value={newInsight.title}
              onChange={(e) => setNewInsight({ ...newInsight, title: e.target.value })}
            />
            <input
              className="ws-form-input"
              placeholder="작성자"
              value={newInsight.author}
              onChange={(e) => setNewInsight({ ...newInsight, author: e.target.value })}
              style={{ maxWidth: 120 }}
            />
          </div>
          <textarea
            className="ws-form-textarea"
            placeholder="내용을 입력하세요 (마크다운 지원: # 제목, ## 소제목, - 목록)"
            value={newInsight.content}
            onChange={(e) => setNewInsight({ ...newInsight, content: e.target.value })}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="ws-btn-ghost" onClick={() => setShowForm(false)}>취소</button>
            <button className="ws-btn-primary" onClick={handleAdd}>저장</button>
          </div>
        </div>
      )}

      <div className="ws-insights-list">
        {sorted.map((ins) => (
          <div key={ins.id} className="ws-insight-card" onClick={() => setSelected(ins)}>
            <div className="ws-insight-card-title">{ins.title}</div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
              <span className="ws-insight-card-date">{ins.createdAt.replace(/-/g, ".")}</span>
              <span style={{ color: "#D1D5DB", fontSize: 12 }}>·</span>
              <span className="ws-insight-author"><FiUser size={11} /> {ins.author}</span>
            </div>
            <div className="ws-insight-card-preview">{ins.preview}</div>
            <div className="ws-meeting-card-link" style={{ marginTop: 10 }}>전체 내용 보기 →</div>
          </div>
        ))}
      </div>
      <Modal insight={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
