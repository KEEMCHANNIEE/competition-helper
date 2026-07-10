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

export default function Chat({ onGoToWorkspace, pendingChat, onPendingConsumed }) {
  // history 항목: { id, title, messages, serverConvId }
  const [history, setHistory] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [input, setInput] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [me, setMe] = useState(null); // 현재 로그인 사용자(팀장 여부 판별용)
  const [approving, setApproving] = useState(false);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const lastPendingNonce = useRef(null); // 같은 할 일-클릭이 중복 전송되지 않도록

  const activeChat = history.find((h) => h.id === activeId);
  const messages = activeChat?.messages || [];

  // 현재 사용자 정보(팀장 여부 판별용).
  useEffect(() => {
    (async () => {
      const res = await apiFetch("/me");
      if (res && res.ok) setMe(await res.json());
    })();
  }, []);

  // 마운트 시 서버에서 대화를 복원한다(새로고침·팀원 전환 후에도 대화 유지).
  useEffect(() => {
    (async () => {
      const res = await apiFetch("/chat");
      if (!res) return;
      const convos = await res.json();
      if (!convos.length) return;
      const loaded = convos.map((c) => ({
        id: `srv-${c.conversation_id}`,
        title: c.title,
        serverConvId: c.conversation_id,
        messages: c.messages.map((m, i) => ({
          id: `${c.conversation_id}-${i}`,
          role: m.role,
          content: m.content,
        })),
      }));
      setHistory(loaded);
      setActiveId(loaded[0].id); // 가장 최근 대화를 활성화
    })();
  }, []);

  // 워크스페이스에서 할 일을 클릭하면(S-02 STEP01) 그 할 일을 어떻게 시작할지 묻는
  // 메시지를 새 대화로 자동 전송한다. workspace_id 를 실어 대화를 워크스페이스에 연결해,
  // 백엔드가 공모전 맥락으로 작업 방향을 답하도록 한다.
  useEffect(() => {
    if (!pendingChat || pendingChat.nonce === lastPendingNonce.current) return;
    lastPendingNonce.current = pendingChat.nonce;
    handleSend(pendingChat.text, {
      workspaceId: pendingChat.workspaceId,
      forceNew: true,
    });
    onPendingConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingChat]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    // 숨겨진 상태(워크스페이스 탭이라 display:none 조상)에서는 scrollHeight 가 0 이라
    // 높이를 0px 로 만들어 입력칸이 먹통이 된다 → 보일 때만 높이를 조절한다.
    if (!el || el.offsetParent === null) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  // opts.workspaceId: 이 대화를 워크스페이스에 연결(할 일 조언은 공모전 맥락이 필요).
  // opts.forceNew: 항상 새 대화로 시작(할 일 클릭 시).
  const handleSend = async (text, opts = {}) => {
    const content = text || input.trim();
    if (!content || isPending) return;
    setInput("");
    setIsPending(true);

    // 로컬 채팅 항목 확정
    let chatLocalId = opts.forceNew ? null : activeId;
    let serverConvId = opts.forceNew
      ? null
      : history.find((h) => h.id === activeId)?.serverConvId ?? null;

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
      body: JSON.stringify({
        message: content,
        conversation_id: serverConvId,
        ...(opts.workspaceId ? { workspace_id: opts.workspaceId } : {}),
      }),
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
      // user/assistant 만 말풍선으로. role="proposal"(계획 변경 제안, JSON)은 승인 카드로 뽑아낸다.
      // log/topic/report 등 내부 기록은 채팅에 노출하지 않는다.
      const bubbles = [];
      let proposal = null;
      for (const m of state.messages) {
        if (m.role === "proposal") {
          try {
            const p = JSON.parse(m.content);
            if (!p.applied) proposal = p;
          } catch { /* 파싱 실패 무시 */ }
          continue;
        }
        if (m.role !== "user" && m.role !== "assistant") continue;
        bubbles.push({
          id: bubbles.length,
          role: m.role,
          content: m.content,
          ...(m.role === "assistant" && m.content.includes("Workspace")
            ? { showWorkspaceButton: true }
            : {}),
        });
      }
      setHistory((prev) =>
        prev.map((h) =>
          h.id === chatLocalId ? { ...h, messages: bubbles, proposal } : h
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

  // 팀장이 AI 제안(계획 변경)을 승인 → 백엔드가 실제 계획에 반영(팀장만 허용). (S-03 STEP02)
  const handleApprove = async (proposal) => {
    if (approving || !proposal) return;
    setApproving(true);
    try {
      const res = await apiFetch(
        `/workspaces/${proposal.workspace_id}/proposals/approve`,
        { method: "POST" }
      );
      if (!res) return;
      let msg;
      if (!res.ok) {
        msg = "승인에 실패했어요. 이 조치는 팀장만 승인할 수 있어요.";
      } else {
        const data = await res.json();
        msg = data.already_applied
          ? `이미 반영된 제안이에요 — ${data.label}`
          : `✅ 계획에 반영했어요 — ${data.label} (과제 ${data.moved}건을 다음 주로 이동).`;
      }
      setHistory((prev) =>
        prev.map((h) =>
          h.id === activeId
            ? {
                ...h,
                proposal: res.ok ? null : h.proposal,
                messages: [
                  ...h.messages,
                  { id: `appr-${Date.now()}`, role: "assistant", content: msg },
                ],
              }
            : h
        )
      );
    } finally {
      setApproving(false);
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

              {/* AI 계획 변경 제안 → 팀장 승인 카드 (S-03 STEP02) */}
              {activeChat?.proposal && (
                <div className="chat-msg-row assistant">
                  <div className="chat-ai-icon"><AIIcon /></div>
                  <div
                    style={{
                      border: "1px solid #C7D2FE",
                      background: "#EEF2FF",
                      borderRadius: 12,
                      padding: "14px 16px",
                      maxWidth: "82%",
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#3730A3", marginBottom: 4 }}>
                      📌 AI 제안
                    </div>
                    <div style={{ fontSize: 14, color: "#374151", marginBottom: 12 }}>
                      {activeChat.proposal.label}
                    </div>
                    {me && me.id === activeChat.proposal.owner_id ? (
                      <button
                        onClick={() => handleApprove(activeChat.proposal)}
                        disabled={approving}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "8px 16px",
                          background: approving ? "#9CA3AF" : "#4F46E5",
                          color: "#fff",
                          border: "none",
                          borderRadius: 8,
                          fontSize: 13,
                          fontWeight: 700,
                          cursor: approving ? "default" : "pointer",
                        }}
                      >
                        {approving ? "반영 중..." : "✅ 승인 (계획에 반영)"}
                      </button>
                    ) : (
                      <div style={{ fontSize: 12.5, color: "#6B7280" }}>
                        🔒 이 조치는 <b>팀장</b>만 승인할 수 있어요.
                      </div>
                    )}
                  </div>
                </div>
              )}

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
