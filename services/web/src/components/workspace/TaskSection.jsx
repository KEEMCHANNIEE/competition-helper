import { useState } from "react";
import { FiPlus, FiCheck, FiMessageSquare } from "react-icons/fi";

function formatDate(dateStr) {
  return dateStr.replace(/-/g, ".");
}

function PriorityBadge({ priority }) {
  const cls = priority === "High" ? "high" : priority === "Medium" ? "medium" : "low";
  return <span className={`ws-priority-badge ${cls}`}>{priority}</span>;
}

function getThisWeekRange() {
  const today = new Date();
  const day = today.getDay();
  const sun = new Date(today);
  sun.setDate(today.getDate() - day);
  sun.setHours(0, 0, 0, 0);
  const sat = new Date(sun);
  sat.setDate(sun.getDate() + 6);
  sat.setHours(23, 59, 59, 999);
  return { sun, sat };
}

function isThisWeek(dateStr) {
  const d = new Date(dateStr);
  const { sun, sat } = getThisWeekRange();
  return d >= sun && d <= sat;
}

function TaskRow({ task, onToggle, onStartTask }) {
  const clickable = !!onStartTask && !task.completed;
  return (
    <tr>
      <td>
        <div
          className={`ws-check-box${task.completed ? " done" : ""}`}
          onClick={() => onToggle(task.id)}
          style={{ cursor: "pointer" }}
        >
          {task.completed && <FiCheck size={10} />}
        </div>
      </td>
      <td>
        <span
          onClick={clickable ? () => onStartTask(task) : undefined}
          title={clickable ? "AI에게 이 작업 시작 방법 물어보기" : undefined}
          style={{
            color: task.completed ? "#9CA3AF" : "#111827",
            textDecoration: task.completed ? "line-through" : "none",
            fontWeight: 500,
            cursor: clickable ? "pointer" : "default",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
          onMouseEnter={(e) => clickable && (e.currentTarget.style.color = "#2563EB")}
          onMouseLeave={(e) =>
            clickable && (e.currentTarget.style.color = task.completed ? "#9CA3AF" : "#111827")
          }
        >
          {task.title}
          {clickable && <FiMessageSquare size={12} style={{ opacity: 0.5, flexShrink: 0 }} />}
        </span>
      </td>
      <td><span className="ws-assignee">{task.assignee}</span></td>
      <td><PriorityBadge priority={task.priority} /></td>
      <td><span className="ws-task-due">{formatDate(task.dueDate)}</span></td>
    </tr>
  );
}

function TaskTable({ tasks, onToggleTask, onStartTask, emptyText }) {
  if (tasks.length === 0) {
    return <div className="ws-empty" style={{ padding: "20px 0" }}>{emptyText}</div>;
  }
  return (
    <table className="ws-task-table">
      <thead>
        <tr>
          <th style={{ width: 40 }}></th>
          <th>제목</th>
          <th>담당자</th>
          <th>우선순위</th>
          <th>마감일</th>
        </tr>
      </thead>
      <tbody>
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} onToggle={onToggleTask} onStartTask={onStartTask} />
        ))}
      </tbody>
    </table>
  );
}

export default function TaskSection({ tasks, onToggleTask, onAddTask, onStartTask }) {
  const [showForm, setShowForm] = useState(false);
  const [newTask, setNewTask] = useState({ title: "", assignee: "", priority: "Medium", dueDate: "" });

  const handleAdd = () => {
    if (!newTask.title.trim()) return;
    onAddTask(newTask);
    setNewTask({ title: "", assignee: "", priority: "Medium", dueDate: "" });
    setShowForm(false);
  };

  const sortTasks = (list) =>
    [...list].sort((a, b) => {
      if (a.completed !== b.completed) return a.completed ? 1 : -1;
      return a.dueDate.localeCompare(b.dueDate);
    });

  const thisWeekTasks = sortTasks(tasks.filter((t) => isThisWeek(t.dueDate)));
  const allTasks = sortTasks(tasks);

  return (
    <div>
      <div className="ws-tasks-header">
        <div className="ws-section-title" style={{ marginBottom: 0 }}>Tasks</div>
        <button className="ws-btn-primary" onClick={() => setShowForm((v) => !v)}>
          <FiPlus size={14} /> New Task
        </button>
      </div>

      {showForm && (
        <div className="ws-card ws-new-task-form">
          <div className="ws-form-row">
            <input
              className="ws-form-input"
              placeholder="Task 제목"
              value={newTask.title}
              onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            />
            <input
              className="ws-form-input"
              placeholder="담당자"
              value={newTask.assignee}
              onChange={(e) => setNewTask({ ...newTask, assignee: e.target.value })}
            />
            <select
              className="ws-form-input"
              value={newTask.priority}
              onChange={(e) => setNewTask({ ...newTask, priority: e.target.value })}
              style={{ maxWidth: 110 }}
            >
              <option>High</option>
              <option>Medium</option>
              <option>Low</option>
            </select>
            <input
              className="ws-form-input"
              type="date"
              value={newTask.dueDate}
              onChange={(e) => setNewTask({ ...newTask, dueDate: e.target.value })}
              style={{ maxWidth: 150 }}
            />
            <button className="ws-btn-primary" onClick={handleAdd}>추가</button>
            <button className="ws-btn-ghost" onClick={() => setShowForm(false)}>취소</button>
          </div>
        </div>
      )}

      {/* 이번 주 섹션 */}
      <div className="ws-task-section-block">
        <div className="ws-task-section-label">
          이번 주 <span className="ws-task-section-count">{thisWeekTasks.filter(t => !t.completed).length}</span>
        </div>
        <div className="ws-card" style={{ padding: 0, overflow: "hidden" }}>
          <TaskTable
            tasks={thisWeekTasks}
            onToggleTask={onToggleTask}
            onStartTask={onStartTask}
            emptyText="이번 주 마감 Task가 없어요"
          />
        </div>
      </div>

      {/* 전체 섹션 */}
      <div className="ws-task-section-block">
        <div className="ws-task-section-label">
          전체 <span className="ws-task-section-count">{allTasks.filter(t => !t.completed).length}</span>
        </div>
        <div className="ws-card" style={{ padding: 0, overflow: "hidden" }}>
          <TaskTable
            tasks={allTasks}
            onToggleTask={onToggleTask}
            onStartTask={onStartTask}
            emptyText="Task가 없어요"
          />
        </div>
      </div>
    </div>
  );
}
