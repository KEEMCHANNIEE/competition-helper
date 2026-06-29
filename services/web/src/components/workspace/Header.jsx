import { FiShare2, FiSettings } from "react-icons/fi";

export default function Header({ title, host, dday, progress }) {
  return (
    <header className="ws-header">
      <div className="ws-header-left">
        <div className="ws-header-title">{title}</div>
        <div className="ws-header-sub">
          <span style={{ color: "#6B7280" }}>{host}</span>
        </div>
      </div>
      <div className="ws-header-right">
        <div className="ws-header-dday">D-{dday}</div>
        <div className="ws-header-progress">
          <div className="ws-progress-bar">
            <div className="ws-progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <span>{progress}%</span>
        </div>
        <button className="ws-header-btn"><FiShare2 size={13} /> 공유</button>
        <button className="ws-header-btn"><FiSettings size={13} /> 설정</button>
      </div>
    </header>
  );
}
