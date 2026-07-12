import { useState } from "react";
import Chat from "./pages/Chat";
import Workspace from "./pages/Workspace";
import MemberSelect from "./pages/MemberSelect";
import NotificationToast from "./components/NotificationToast";

export default function App() {
  // 현재 페이지도 sessionStorage 에 저장한다. 팀원 전환(reload) 후에도 워크스페이스에
  // 있었으면 워크스페이스로 복원되도록(채팅으로 튕기지 않게).
  const [page, setPageState] = useState(
    () => sessionStorage.getItem("cm_page") || "chat"
  );
  const setPage = (p) => {
    sessionStorage.setItem("cm_page", p);
    setPageState(p);
  };
  // 시작 화면 통과 여부. sessionStorage 에 저장해, 팀원 전환(reload) 시 다시 시작화면으로
  // 튕기지 않게 한다(새 브라우저 세션에서만 시작화면 표시).
  const [entered, setEntered] = useState(
    () => sessionStorage.getItem("cm_entered") === "1"
  );
  const enter = () => {
    sessionStorage.setItem("cm_entered", "1");
    setEntered(true);
  };

  // 워크스페이스에서 할 일을 클릭하면(S-02 STEP01) 그 할 일을 어떻게 시작할지
  // 묻는 메시지를 채팅으로 넘긴다. nonce 로 매번 새 요청임을 구분한다.
  const [pendingChat, setPendingChat] = useState(null);
  const startTaskChat = (text, workspaceId) => {
    setPendingChat({ text, workspaceId, nonce: Date.now() });
    setPage("chat");
  };

  // 시작 화면: 네 명 중 한 명(시점)을 고른다. 선택 시 세션이 그 사람으로 전환된다.
  if (!entered) {
    return <MemberSelect onEnter={enter} />;
  }

  // 두 페이지를 항상 마운트해두고 화면만 전환한다(display 토글).
  // 이렇게 해야 채팅 <-> 워크스페이스를 오가도 Chat 의 대화 내용이 유지된다.
  // display: contents 는 래퍼 박스를 없애 각 페이지의 전체화면 레이아웃을 그대로 살린다.
  return (
    <>
      <NotificationToast />
      <div style={{ display: page === "chat" ? "contents" : "none" }}>
        <Chat
          onGoToWorkspace={() => setPage("workspace")}
          pendingChat={pendingChat}
          onPendingConsumed={() => setPendingChat(null)}
        />
      </div>
      <div style={{ display: page === "workspace" ? "contents" : "none" }}>
        <Workspace
          active={page === "workspace"}
          onGoToChat={() => setPage("chat")}
          onStartTaskChat={startTaskChat}
        />
      </div>
    </>
  );
}
