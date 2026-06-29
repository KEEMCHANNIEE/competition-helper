import { useEffect, useRef, useState } from "react";

import { useChat } from "../hooks/useChat";
import { ErrorBanner } from "../components/ErrorBanner";

/**
 * 대화형 에이전트 화면.
 * 추천·공부·계획이 모두 이 한 대화창에서 이루어진다.
 * (메시지 전송 → 폴링으로 어시스턴트 답변 수신)
 */
export function Chat() {
  const { messages, pending, error, send, reset } = useChat();
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  // 새 메시지/로딩 표시가 생기면 항상 맨 아래로 스크롤.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, pending]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setDraft("");
    await send(text);
  }

  const empty = messages.length === 0;

  return (
    <section className="page chat-page">
      <header className="chat-page__head">
        <div>
          <h1>대화</h1>
          <p className="muted">
            공모전 추천부터 공부, 계획까지 — 편하게 물어보세요.
          </p>
        </div>
        {!empty && (
          <button type="button" className="btn btn--ghost" onClick={reset}>
            새 대화
          </button>
        )}
      </header>

      {error && <ErrorBanner message={error} />}

      <div className="chat-thread" ref={listRef}>
        {empty && !pending && (
          <div className="chat-empty muted">
            <p>예: “나 AI 공모전 찾고 있어”</p>
            <p>예: “이 공모전 평가 기준이 뭐야?”</p>
            <p>예: “마감까지 계획 짜줘. 우리 3명이야”</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={`${i}-${m.role}`}
            className={
              m.role === "user"
                ? "chat-bubble chat-bubble--user"
                : "chat-bubble chat-bubble--assistant"
            }
          >
            {m.content}
          </div>
        ))}

        {pending && (
          <div
            className="chat-bubble chat-bubble--assistant chat-bubble--typing"
            role="status"
            aria-live="polite"
          >
            <span className="chat-typing">
              <span />
              <span />
              <span />
            </span>
          </div>
        )}
      </div>

      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="메시지를 입력하세요..."
          aria-label="메시지 입력"
          disabled={pending}
        />
        <button
          type="submit"
          className="btn btn--primary"
          disabled={pending || draft.trim().length === 0}
        >
          {pending ? "전송 중..." : "보내기"}
        </button>
      </form>
    </section>
  );
}
