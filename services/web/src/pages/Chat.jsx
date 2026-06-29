import { useState, useRef, useEffect } from "react";
import { FiSend, FiExternalLink, FiPlus } from "react-icons/fi";
import { mockMessages } from "../data/mockChat";
import "../styles/chat.css";

const MOCK_HISTORY = [
  { id: 1, title: "직지 콘텐츠 공모전", messages: mockMessages },
];

const SUGGESTED = [
  { label: "공모전 추천해줘", sub: "내 관심사에 맞는 공모전 찾기" },
  { label: "아이디어 브레인스토밍", sub: "공모전 주제로 아이디어 발굴" },
  { label: "제출 전략 짜줘", sub: "마감일 기준 일정 계획" },
  { label: "Workspace 만들어줘", sub: "공모전 준비 공간 생성" },
];

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
  const [history, setHistory] = useState(MOCK_HISTORY);
  const [activeId, setActiveId] = useState(null);
  const [input, setInput] = useState("");
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

  const handleSend = (text) => {
    const content = text || input.trim();
    if (!content) return;

    // 새 채팅이면 히스토리에 추가
    if (!activeId) {
      const newChat = {
        id: Date.now(),
        title: content.slice(0, 20),
        messages: [],
      };
      setHistory((prev) => [newChat, ...prev]);
      setActiveId(newChat.id);

      setTimeout(() => {
        const userMsg = { id: Date.now(), role: "user", content };
        const aiMsg = {
          id: Date.now() + 1,
          role: "assistant",
          content: "네, 확인했습니다. 추가로 궁금한 점이 있으시면 말씀해 주세요.",
          ...(content.includes("Workspace") ? { showWorkspaceButton: true } : {}),
        };
        setHistory((prev) =>
          prev.map((h) =>
            h.id === newChat.id ? { ...h, messages: [userMsg, aiMsg] } : h
          )
        );
      }, 0);

      setInput("");
      return;
    }

    const userMsg = { id: Date.now(), role: "user", content };
    setHistory((prev) =>
      prev.map((h) =>
        h.id === activeId ? { ...h, messages: [...h.messages, userMsg] } : h
      )
    );
    setInput("");

    setTimeout(() => {
      const aiMsg = {
        id: Date.now() + 1,
        role: "assistant",
        content: "네, 확인했습니다. 추가로 궁금한 점이 있으시면 말씀해 주세요.",
        ...(content.includes("Workspace") ? { showWorkspaceButton: true } : {}),
      };
      setHistory((prev) =>
        prev.map((h) =>
          h.id === activeId ? { ...h, messages: [...h.messages, aiMsg] } : h
        )
      );
    }, 800);
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
                placeholder="메시지를 입력하세요..."
                rows={1}
              />
              <button
                className={`chat-send-btn ${input.trim() ? "active" : "inactive"}`}
                onClick={() => handleSend()}
                disabled={!input.trim()}
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
