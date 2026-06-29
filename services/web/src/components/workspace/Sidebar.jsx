import { FiGrid, FiCheckSquare, FiCalendar, FiMessageSquare, FiBookOpen, FiInfo } from "react-icons/fi";

const MENU_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: FiGrid },
  { key: "tasks", label: "Tasks", icon: FiCheckSquare },
  { key: "schedule", label: "Schedule", icon: FiCalendar },
  { key: "meetings", label: "Meetings", icon: FiMessageSquare },
  { key: "insights", label: "Insights", icon: FiBookOpen },
  { key: "contest-info", label: "Contest Info", icon: FiInfo },
];

export default function Sidebar({ activeMenu, onMenuChange }) {
  return (
    <aside className="ws-sidebar">
      <div className="ws-sidebar-logo">ConMate</div>
      <div className="ws-sidebar-divider" />
      <nav className="ws-sidebar-menu">
        {MENU_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              className={`ws-sidebar-item${activeMenu === item.key ? " active" : ""}`}
              onClick={() => onMenuChange(item.key)}
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
