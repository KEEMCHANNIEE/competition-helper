import { useState, useRef, useEffect } from "react";
import { FiSend, FiExternalLink, FiPlus } from "react-icons/fi";
import "../styles/chat.css";

const SUGGESTED = [
  { label: "공모전 추천해줘", sub: "내 관심사에 맞는 공모전 찾기" },
  { label: "아이디어 브레인스토밍", sub: "공모전 주제로 아이디어 발굴" },
  { label: "제출 전략 짜줘", sub: "마감일 기준 일정 계획" },
  { label: "Workspace 만들어줘", sub: "공모전 준비 공간 생성" },
];

async function apiFetch(path, options = {}) {
  const res = await fetch(path, { credentials: "include", ...options });
  if (res.status === 401) {
    window.location.href = "/auth/google/login";
    return null;
  }
  return res;
}

async function pollChatState(conversationId, maxRetries = 30) {
  for (let i = 0; i < maxRetries; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    const res = await apiFetch(`/chat/${conversationId}`);
    if (!res) return null;
    const data = await res.json();
    if (!data.pending) return data;
  }
  return null;
}

function AIIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#EFF6FF" />
      <circle cx="16" cy="16" r="10" fill="#DBEAFE" />
      <circle cx="12" cy="15" r="2" fill="#2563EB" />
      <circle cx="20" cy="15" r="2" fill="#2563EB" />
      <path d="M12 20 Q16 23 20 20" stroke="#2563EB" strokeWidth="1.5" strokeLinecap="round" fill="none" />
    </svg>
  );
}

function renderMarkdown(text) {
  return text
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
    .replace(/^---$/gm, "<hr/>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

export default function Chat({ onGoToWorkspace }) {
  // history 항목: { id, title, messages, serverConvId }
  const [history, setHistory] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [input, setInput] = useState("");
  const [isPending, setIsPending] = useState(false);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const activeChat = history.find((h) => h.id === activeId);
  const messages = activeChat?.messages || [];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  const handleSend = async (text) => {
    const content = text || input.trim();
    if (!content || isPending) return;
    setInput("");
    setIsPending(true);

    // 로컬 채팅 항목 확정
    let chatLocalId = activeId;
    let serverConvId = history.find((h) => h.id === activeId)?.serverConvId ?? null;

    if (!chatLocalId) {
      chatLocalId = Date.now();
      setActiveId(chatLocalId);
      setHistory((prev) => [
        { id: chatLocalId, title: content.slice(0, 20), messages: [], serverConvId: null },
        ...prev,
      ]);
    }

    // 사용자 메시지 즉시 표시
    const userMsg = { id: Date.now(), role: "user", content };
    const loadingMsg = { id: "loading", role: "assistant", content: "...", isLoading: true };
    setHistory((prev) =>
      prev.map((h) =>
        h.id === chatLocalId
          ? { ...h, messages: [...h.messages, userMsg, loadingMsg] }
          : h
      )
    );

    // POST /chat
    const res = await apiFetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: content, conversation_id: serverConvId }),
    });

    if (!res) {
      setIsPending(false);
      return;
    }

    const { conversation_id } = await res.json();

    // serverConvId 저장
    setHistory((prev) =>
      prev.map((h) =>
        h.id === chatLocalId ? { ...h, serverConvId: conversation_id } : h
      )
    );

    // 답변 폴링
    const state = await pollChatState(conversation_id);
    setIsPending(false);

    if (state) {
      const serverMessages = state.messages.map((m, i) => ({
        id: i,
        role: m.role,
        content: m.content,
        ...(m.role === "assistant" && m.content.includes("Workspace")
          ? { showWorkspaceButton: true }
          : {}),
      }));
      setHistory((prev) =>
        prev.map((h) =>
          h.id === chatLocalId ? { ...h, messages: serverMessages } : h
        )
      );
    } else {
      const errMsg = {
        id: Date.now(),
        role: "assistant",
        content: "응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.",
      };
      setHistory((prev) =>
        prev.map((h) =>
          h.id === chatLocalId
            ? { ...h, messages: h.messages.filter((m) => m.id !== "loading").concat(errMsg) }
            : h
        )
      );
    }
  };

  const handleNewChat = () => {
    setActiveId(null);
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isEmpty = !activeId || messages.length === 0;

  return (
    <div className="chat-layout">
      {/* Sidebar */}
      <aside className="chat-sidebar">
        <div className="chat-sidebar-logo">ConMate</div>
        <button className="chat-new-btn" onClick={handleNewChat}>
          <FiPlus size={14} /> New Chat
        </button>
        <div className="chat-sidebar-divider" />
        <div className="chat-history-label">History</div>
        <div className="chat-history-list">
          {history.map((h) => (
            <button
              key={h.id}
              className={`chat-history-item${activeId === h.id ? " active" : ""}`}
              onClick={() => setActiveId(h.id)}
            >
              {h.title}
            </button>
          ))}
        </div>
      </aside>

      {/* Main */}
      <div className="chat-main">
        {/* Header */}
        <header className="chat-header">
          <div className="chat-header-logo">ConMate</div>
          <button className="chat-header-btn" onClick={onGoToWorkspace}>
            <FiExternalLink size={13} /> Workspace
          </button>
        </header>

        {/* Messages */}
        <div className="chat-messages">
          {isEmpty ? (
            <div className="chat-empty">
              <div className="chat-empty-icon"><AIIcon /></div>
              <div className="chat-empty-title">공모전 준비를 시작해 보세요.</div>
              <div className="chat-suggested-grid">
                {SUGGESTED.map((s) => (
                  <button
                    key={s.label}
                    className="chat-suggested-card"
                    onClick={() => handleSend(s.label)}
                  >
                    <div className="chat-suggested-label">{s.label}</div>
                    <div className="chat-suggested-sub">{s.sub}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-message-list">
              {messages.map((msg) => (
                <div key={msg.id} className={`chat-msg-row ${msg.role}`}>
                  {msg.role === "assistant" && (
                    <div className="chat-ai-icon"><AIIcon /></div>
                  )}
                  <div>
                    {msg.role === "user" ? (
                      <div className="chat-bubble user">{msg.content}</div>
                    ) : msg.isLoading ? (
                      <div className="chat-bubble assistant chat-loading">
                        <span>.</span><span>.</span><span>.</span>
                      </div>
                    ) : (
                      <div
                        className="chat-bubble assistant"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                      />
                    )}
                    {msg.showWorkspaceButton && (
                      <button className="chat-workspace-btn" onClick={onGoToWorkspace}>
                        <FiExternalLink size={13} /> Workspace 열기
                      </button>
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="chat-input-area">
          <div className="chat-input-inner">
            <div className="chat-input-box">
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={isPending ? "답변을 기다리는 중..." : "메시지를 입력하세요..."}
                rows={1}
                disabled={isPending}
              />
              <button
                className={`chat-send-btn ${input.trim() && !isPending ? "active" : "inactive"}`}
                onClick={() => handleSend()}
                disabled={!input.trim() || isPending}
              >
                <FiSend size={15} />
              </button>
            </div>
            <div className="chat-input-hint">Enter로 전송 · Shift+Enter로 줄바꿈</div>
          </div>
        </div>
      </div>
    </div>
  );
}
