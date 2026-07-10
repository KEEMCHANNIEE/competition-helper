import { FiCheck, FiMessageSquare } from "react-icons/fi";

function formatDate(dateStr) {
  const d = new Date(dateStr);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export default function Dashboard({ workspace, onMenuChange, onToggleTask, onStartTask }) {
  const { contest, tasks, schedules, meetings, insights } = workspace;

  const todayTasks = tasks.filter((t) => !t.completed).slice(0, 5);
  const upcomingSchedules = [...schedules]
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 5);
  const recentMeetings = [...meetings]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 3);

  const completedCount = tasks.filter((t) => t.completed).length;
  const dday = Math.ceil(
    (new Date(`${contest.end_date}T23:59:59`) - new Date()) / (1000 * 60 * 60 * 24)
  );

  return (
    <div>
      <div className="ws-section-title">Dashboard</div>

      {/* KPI */}
      <div className="ws-kpi-grid">
        <div className="ws-kpi-card">
          <div className="ws-kpi-label">Tasks</div>
          <div className="ws-kpi-value">{tasks.length}</div>
          <div className="ws-kpi-sub">{completedCount}개 완료</div>
        </div>
        <div className="ws-kpi-card">
          <div className="ws-kpi-label">Schedule</div>
          <div className="ws-kpi-value">{schedules.length}</div>
        </div>
        <div className="ws-kpi-card">
          <div className="ws-kpi-label">Meetings</div>
          <div className="ws-kpi-value">{meetings.length}</div>
        </div>
        <div className="ws-kpi-card">
          <div className="ws-kpi-label">D-Day</div>
          <div className="ws-kpi-value blue">D-{dday}</div>
        </div>
      </div>

      {/* Today Tasks + Upcoming Schedule */}
      <div className="ws-dashboard-grid">
        <div className="ws-card">
          <div className="ws-card-title">
            Today's Tasks
            <button className="ws-card-link" onClick={() => onMenuChange("tasks")}>전체 보기</button>
          </div>
          <div className="ws-task-list">
            {todayTasks.length === 0 && <div className="ws-empty">완료되지 않은 Task가 없어요 🎉</div>}
            {todayTasks.map((t) => (
              <div key={t.id} className="ws-task-row">
                <div
                  className={`ws-check-box${t.completed ? " done" : ""}`}
                  onClick={() => onToggleTask(t.id)}
                  style={{ cursor: "pointer" }}
                >
                  {t.completed && <FiCheck size={10} />}
                </div>
                <span
                  className={`ws-task-text${t.completed ? " done" : ""}`}
                  onClick={onStartTask ? () => onStartTask(t) : undefined}
                  title={onStartTask ? "AI에게 이 작업 시작 방법 물어보기" : undefined}
                  style={{
                    cursor: onStartTask ? "pointer" : "default",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                  onMouseEnter={(e) => onStartTask && (e.currentTarget.style.color = "#2563EB")}
                  onMouseLeave={(e) => onStartTask && (e.currentTarget.style.color = "")}
                >
                  {t.title}
                  {onStartTask && <FiMessageSquare size={11} style={{ opacity: 0.5, flexShrink: 0 }} />}
                </span>
                <span className="ws-task-due">{formatDate(t.dueDate)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="ws-card">
          <div className="ws-card-title">
            Upcoming Schedule
            <button className="ws-card-link" onClick={() => onMenuChange("schedule")}>전체 보기</button>
          </div>
          <div className="ws-schedule-list">
            {upcomingSchedules.map((s) => (
              <div key={s.id} className="ws-schedule-item">
                <span className="ws-schedule-date">{formatDate(s.date)}</span>
                <span className="ws-schedule-title">{s.title}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent Meetings + Contest Summary */}
      <div className="ws-dashboard-grid">
        <div className="ws-card">
          <div className="ws-card-title">
            Recent Meetings
            <button className="ws-card-link" onClick={() => onMenuChange("meetings")}>전체 보기</button>
          </div>
          <div className="ws-meeting-list">
            {recentMeetings.map((m) => (
              <div key={m.id} className="ws-meeting-item">
                <div className="ws-meeting-title">{m.title}</div>
                <div className="ws-meeting-date">{m.date.replace(/-/g, ".")}</div>
                <div className="ws-meeting-preview">{m.summary}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="ws-card">
          <div className="ws-card-title">
            Contest Summary
            <button className="ws-card-link" onClick={() => onMenuChange("contest-info")}>더 보기</button>
          </div>
          <div className="ws-contest-summary-list">
            <div className="ws-contest-summary-row">
              <span className="ws-contest-summary-label">주최</span>
              <span className="ws-contest-summary-value">{contest.host}</span>
            </div>
            <div className="ws-contest-summary-row">
              <span className="ws-contest-summary-label">분야</span>
              <div className="ws-chip-list">
                {contest.category.map((c) => <span key={c} className="ws-chip">{c}</span>)}
              </div>
            </div>
            <div className="ws-contest-summary-row">
              <span className="ws-contest-summary-label">참가 대상</span>
              <span className="ws-contest-summary-value">{contest.target}</span>
            </div>
            <div className="ws-contest-summary-row">
              <span className="ws-contest-summary-label">마감일</span>
              <span className="ws-contest-summary-value">{contest.end_date.replace(/-/g, ".")}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
