import { useState } from "react";
import Chat from "./pages/Chat";
import Workspace from "./pages/Workspace";

export default function App() {
  const [page, setPage] = useState("chat");

  return page === "chat" ? (
    <Chat onGoToWorkspace={() => setPage("workspace")} />
  ) : (
    <Workspace onGoToChat={() => setPage("chat")} />
  );
}
