import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./hooks/useAuth";
import { NavBar } from "./components/NavBar";
import { Loading } from "./components/Loading";
import { Login } from "./pages/Login";
import { Interests } from "./pages/Interests";
import { Recommend } from "./pages/Recommend";
import { Workspace } from "./pages/Workspace";
import { Chat } from "./pages/Chat";
import { Plan } from "./pages/Plan";

export default function App() {
  const { user, status } = useAuth();

  if (status === "loading") {
    return (
      <div className="app-shell app-shell--center">
        <Loading label="로그인 상태 확인 중..." />
      </div>
    );
  }

  // 인증 가드: 미로그인 시 모든 보호 라우트를 /login 으로.
  if (status === "unauthenticated") {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <div className="app-shell">
      <NavBar user={user} />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/recommend" replace />} />
          <Route path="/login" element={<Navigate to="/recommend" replace />} />
          <Route path="/interests" element={<Interests />} />
          <Route path="/recommend" element={<Recommend />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/workspace/:id/plan" element={<Plan />} />
          <Route path="*" element={<Navigate to="/recommend" replace />} />
        </Routes>
      </main>
    </div>
  );
}
