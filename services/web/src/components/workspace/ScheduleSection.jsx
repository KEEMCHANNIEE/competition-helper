import { useState } from "react";
import { FiPlus, FiList, FiCalendar, FiChevronLeft, FiChevronRight } from "react-icons/fi";

function formatDate(dateStr) {
  return dateStr.replace(/-/g, ".");
}

function CalendarView({ schedules, year, month }) {
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();

  const cells = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const dateStr = (d) =>
    `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const eventsOn = (d) => schedules.filter((s) => s.date === dateStr(d));
  const isToday = (d) =>
    today.getFullYear() === year && today.getMonth() === month && today.getDate() === d;

  return (
    <div className="ws-calendar">
      <div className="ws-calendar-header-row">
        {["일", "월", "화", "수", "목", "금", "토"].map((d) => (
          <div key={d} className="ws-calendar-day-label">{d}</div>
        ))}
      </div>
      <div className="ws-calendar-grid">
        {cells.map((d, i) => (
          <div
            key={i}
            className={`ws-calendar-cell${d && isToday(d) ? " today" : ""}${!d ? " empty" : ""}`}
          >
            {d && (
              <>
                <div className="ws-calendar-date">{d}</div>
                {eventsOn(d).map((ev) => (
                  <div
                    key={ev.id}
                    className={`ws-calendar-event${ev.type === "contest" ? " contest" : ""}`}
                  >
                    {ev.title}
                  </div>
                ))}
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const MONTH_NAMES = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];

export default function ScheduleSection({ schedules, onAddSchedule }) {
  const [view, setView] = useState("list");
  const now = new Date();
  const [calYear, setCalYear] = useState(now.getFullYear());
  const [calMonth, setCalMonth] = useState(now.getMonth());
  const [showForm, setShowForm] = useState(false);
  const [newSchedule, setNewSchedule] = useState({ title: "", date: "" });

  const sorted = [...schedules].sort((a, b) => a.date.localeCompare(b.date));

  const prevMonth = () => {
    if (calMonth === 0) { setCalYear(calYear - 1); setCalMonth(11); }
    else setCalMonth(calMonth - 1);
  };

  const nextMonth = () => {
    if (calMonth === 11) { setCalYear(calYear + 1); setCalMonth(0); }
    else setCalMonth(calMonth + 1);
  };

  const handleAdd = () => {
    if (!newSchedule.title.trim() || !newSchedule.date) return;
    onAddSchedule({ ...newSchedule, type: "team" });
    setNewSchedule({ title: "", date: "" });
    setShowForm(false);
  };

  return (
    <div>
      <div className="ws-tasks-header">
        <div className="ws-section-title" style={{ marginBottom: 0 }}>Schedule</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div className="ws-view-toggle">
            <button className={`ws-view-btn${view === "list" ? " active" : ""}`} onClick={() => setView("list")}>
              <FiList size={14} /> 목록
            </button>
            <button className={`ws-view-btn${view === "calendar" ? " active" : ""}`} onClick={() => setView("calendar")}>
              <FiCalendar size={14} /> 달력
            </button>
          </div>
          <button className="ws-btn-primary" onClick={() => setShowForm((v) => !v)}>
            <FiPlus size={14} /> New Schedule
          </button>
        </div>
      </div>

      {/* 범례 */}
      <div className="ws-schedule-legend">
        <span className="ws-legend-item team">● 팀 일정</span>
        <span className="ws-legend-item contest">● 공모전 공식 일정</span>
      </div>

      {showForm && (
        <div className="ws-card ws-new-task-form">
          <div className="ws-form-row">
            <input
              className="ws-form-input"
              placeholder="일정 제목"
              value={newSchedule.title}
              onChange={(e) => setNewSchedule({ ...newSchedule, title: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            />
            <input
              className="ws-form-input"
              type="date"
              value={newSchedule.date}
              onChange={(e) => setNewSchedule({ ...newSchedule, date: e.target.value })}
              style={{ maxWidth: 160 }}
            />
            <button className="ws-btn-primary" onClick={handleAdd}>추가</button>
            <button className="ws-btn-ghost" onClick={() => setShowForm(false)}>취소</button>
          </div>
        </div>
      )}

      {view === "list" ? (
        <div className="ws-card">
          <div className="ws-schedule-section-list">
            {sorted.map((s, i) => (
              <div key={s.id} className="ws-schedule-section-item">
                <div className={`ws-schedule-dot${s.type === "contest" ? " contest" : ""}`} />
                {i < sorted.length - 1 && <div className="ws-schedule-line" />}
                <div className="ws-schedule-section-date">{formatDate(s.date)}</div>
                <div className="ws-schedule-section-title">{s.title}</div>
                {s.type === "contest" && (
                  <span className="ws-schedule-contest-badge">공식</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="ws-card">
          <div className="ws-calendar-nav">
            <button className="ws-cal-nav-btn" onClick={prevMonth}><FiChevronLeft size={16} /></button>
            <div className="ws-calendar-month-label">{calYear}년 {MONTH_NAMES[calMonth]}</div>
            <button className="ws-cal-nav-btn" onClick={nextMonth}><FiChevronRight size={16} /></button>
          </div>
          <CalendarView schedules={schedules} year={calYear} month={calMonth} />
        </div>
      )}
    </div>
  );
}
