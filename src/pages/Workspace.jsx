import { useState } from "react";
import { FiMessageCircle } from "react-icons/fi";
import { workspace as initialWorkspace } from "../data/mockWorkspace";
import Sidebar from "../components/workspace/Sidebar";
import Header from "../components/workspace/Header";
import Dashboard from "../components/workspace/Dashboard";
import TaskSection from "../components/workspace/TaskSection";
import ScheduleSection from "../components/workspace/ScheduleSection";
import MeetingSection from "../components/workspace/MeetingSection";
import InsightsSection from "../components/workspace/InsightsSection";
import ContestInfoSection from "../components/workspace/ContestInfoSection";
import "../styles/workspace.css";

export default function Workspace({ onGoToChat }) {
  const [activeMenu, setActiveMenu] = useState("dashboard");
  const [tasks, setTasks] = useState(initialWorkspace.tasks);
  const [schedules, setSchedules] = useState(initialWorkspace.schedules);
  const [meetings, setMeetings] = useState(initialWorkspace.meetings);
  const [insights, setInsights] = useState(initialWorkspace.insights);

  const completedCount = tasks.filter((t) => t.completed).length;
  const progress = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0;
  const dday = Math.ceil(
    (new Date(`${initialWorkspace.contest.end_date}T23:59:59`) - new Date()) / (1000 * 60 * 60 * 24)
  );

  const handleToggleTask = (id) =>
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, completed: !t.completed } : t)));

  const handleAddTask = (newTask) =>
    setTasks((prev) => [...prev, { id: Date.now(), completed: false, ...newTask }]);

  const handleAddSchedule = (newSchedule) =>
    setSchedules((prev) =>
      [...prev, { id: Date.now(), ...newSchedule }].sort((a, b) => a.date.localeCompare(b.date))
    );

  const handleAddMeeting = (newMeeting) =>
    setMeetings((prev) => [{ id: Date.now(), ...newMeeting }, ...prev]);

  const handleAddInsight = (newInsight) =>
    setInsights((prev) => [{ id: Date.now(), ...newInsight }, ...prev]);

  const workspace = { ...initialWorkspace, tasks, schedules, meetings, insights };

  return (
    <div className="ws-layout">
      <Header
        title={workspace.contest.title}
        host={workspace.contest.host}
        dday={dday}
        progress={progress}
      />
      <div className="ws-body">
        <Sidebar activeMenu={activeMenu} onMenuChange={setActiveMenu} />
        <main className="ws-main">
          {activeMenu === "dashboard" && (
            <Dashboard
              workspace={workspace}
              progress={progress}
              onMenuChange={setActiveMenu}
              onToggleTask={handleToggleTask}
            />
          )}
          {activeMenu === "tasks" && (
            <TaskSection
              tasks={tasks}
              onToggleTask={handleToggleTask}
              onAddTask={handleAddTask}
            />
          )}
          {activeMenu === "schedule" && (
            <ScheduleSection
              schedules={schedules}
              onAddSchedule={handleAddSchedule}
            />
          )}
          {activeMenu === "meetings" && (
            <MeetingSection
              meetings={meetings}
              onAddMeeting={handleAddMeeting}
            />
          )}
          {activeMenu === "insights" && (
            <InsightsSection
              insights={insights}
              onAddInsight={handleAddInsight}
            />
          )}
          {activeMenu === "contest-info" && (
            <ContestInfoSection contest={workspace.contest} />
          )}
        </main>
      </div>
      <button className="ws-ai-float" onClick={onGoToChat}>
        <FiMessageCircle size={15} />
        AI Assistant
      </button>
    </div>
  );
}
