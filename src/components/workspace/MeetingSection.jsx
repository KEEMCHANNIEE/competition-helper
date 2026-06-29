import { useState } from "react";
import { FiPlus, FiX } from "react-icons/fi";

function Modal({ meeting, onClose }) {
  if (!meeting) return null;
  return (
    <div className="ws-modal-overlay" onClick={onClose}>
      <div className="ws-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ws-modal-header">
          <div>
            <div className="ws-modal-title">{meeting.title}</div>
            <div className="ws-modal-date">{meeting.date.replace(/-/g, ".")}</div>
          </div>
          <button className="ws-modal-close" onClick={onClose}><FiX size={18} /></button>
        </div>
        <div className="ws-modal-body">
          {meeting.content.split("\n").map((line, i) => {
            if (line.startsWith("**") && line.endsWith("**"))
              return <p key={i} style={{ fontWeight: 700, color: "#111827", margin: "12px 0 6px" }}>{line.replace(/\*\*/g, "")}</p>;
            if (line.startsWith("- "))
              return <p key={i} style={{ paddingLeft: 16, color: "#374151", margin: "4px 0" }}>• {line.slice(2)}</p>;
            if (line === "") return <div key={i} style={{ height: 8 }} />;
            return <p key={i} style={{ color: "#374151", margin: "4px 0", lineHeight: 1.7 }}>{line}</p>;
          })}
        </div>
      </div>
    </div>
  );
}

export default function MeetingSection({ meetings, onAddMeeting }) {
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [newMeeting, setNewMeeting] = useState({ title: "", date: "", summary: "", content: "" });

  const sorted = [...meetings].sort((a, b) => b.date.localeCompare(a.date));

  const handleAdd = () => {
    if (!newMeeting.title.trim() || !newMeeting.date) return;
    onAddMeeting({
      ...newMeeting,
      summary: newMeeting.content.slice(0, 60) + (newMeeting.content.length > 60 ? "..." : ""),
    });
    setNewMeeting({ title: "", date: "", summary: "", content: "" });
    setShowForm(false);
  };

  return (
    <div>
      <div className="ws-tasks-header">
        <div className="ws-section-title" style={{ marginBottom: 0 }}>Meetings</div>
        <button className="ws-btn-primary" onClick={() => setShowForm((v) => !v)}>
          <FiPlus size={14} /> New Meeting
        </button>
      </div>

      {showForm && (
        <div className="ws-card ws-new-task-form">
          <div className="ws-form-row">
            <input
              className="ws-form-input"
              placeholder="회의 제목"
              value={newMeeting.title}
              onChange={(e) => setNewMeeting({ ...newMeeting, title: e.target.value })}
            />
            <input
              className="ws-form-input"
              type="date"
              value={newMeeting.date}
              onChange={(e) => setNewMeeting({ ...newMeeting, date: e.target.value })}
              style={{ maxWidth: 160 }}
            />
          </div>
          <textarea
            className="ws-form-textarea"
            placeholder="회의 내용을 입력하세요"
            value={newMeeting.content}
            onChange={(e) => setNewMeeting({ ...newMeeting, content: e.target.value })}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="ws-btn-ghost" onClick={() => setShowForm(false)}>취소</button>
            <button className="ws-btn-primary" onClick={handleAdd}>저장</button>
          </div>
        </div>
      )}

      <div className="ws-meeting-section-list">
        {sorted.map((m) => (
          <div key={m.id} className="ws-meeting-card" onClick={() => setSelected(m)}>
            <div className="ws-meeting-card-title">{m.title}</div>
            <div className="ws-meeting-card-date">{m.date.replace(/-/g, ".")}</div>
            <div className="ws-meeting-card-summary">{m.summary}</div>
            <div className="ws-meeting-card-link">전체 내용 보기 →</div>
          </div>
        ))}
      </div>
      <Modal meeting={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
