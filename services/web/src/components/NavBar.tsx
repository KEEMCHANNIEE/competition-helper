import { NavLink } from "react-router-dom";

import type { User } from "../api/types";

interface NavBarProps {
  user: User | null;
}

export function NavBar({ user }: NavBarProps) {
  return (
    <nav className="navbar">
      <NavLink to="/recommend" className="navbar__brand">
        contest-helper
      </NavLink>
      <div className="navbar__links">
        <NavLink to="/chat">대화</NavLink>
        <NavLink to="/recommend">추천</NavLink>
        <NavLink to="/interests">관심사</NavLink>
        <NavLink to="/workspace">워크스페이스</NavLink>
      </div>
      {user && <span className="navbar__user">{user.name || user.email}</span>}
    </nav>
  );
}
