import { useCallback, useEffect, useRef, useState } from "react";

import { getChat, sendChat } from "../api/endpoints";
import type { ChatState, Message } from "../api/types";

const POLL_INTERVAL_MS = 2000;

export interface UseChatOptions {
  /** 대화가 묶일 워크스페이스(공모전 공간). 없으면 일반 대화. */
  workspaceId?: number | null;
}

export interface UseChatResult {
  conversationId: number | null;
  messages: Message[];
  /** 에이전트가 답을 만드는 중이면 true. */
  pending: boolean;
  error: string | null;
  /** 메시지 전송: POST /chat → getChat 폴링으로 답변 수신. */
  send: (text: string) => Promise<void>;
  /** 대화 초기화(폴링 중지). */
  reset: () => void;
}

/**
 * 채팅 폴링 훅 (useRecommendJob 의 폴링 패턴을 그대로 따른다).
 * 1. sendChat() → {conversation_id, job_id}
 * 2. setInterval 로 getChat(conversation_id) 를 2초마다 조회
 * 3. pending === false → 서버의 전체 메시지(어시스턴트 답변 포함)로 갱신, 폴링 종료
 * 4. error 가 오면 노출하고 폴링 종료
 * 언마운트/리셋 시 interval 정리.
 */
export function useChat(options: UseChatOptions = {}): UseChatResult {
  const { workspaceId = null } = options;

  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 언마운트 후 setState 방지.
  const mountedRef = useRef(true);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  /**
   * 폴링 응답을 상태에 반영. 더 폴링해야 하면 true 를 돌려준다.
   * (서버가 전체 대화 기록을 돌려준다고 가정 → 그대로 신뢰.)
   */
  const applyState = useCallback((state: ChatState): boolean => {
    if (!mountedRef.current) return false;
    setConversationId(state.conversation_id);
    if (state.messages.length > 0) {
      setMessages(state.messages);
    }
    if (state.error) {
      setError(state.error);
      setPending(false);
      return false;
    }
    if (!state.pending) {
      // 처리 완료 — 어시스턴트 답변 포함.
      setPending(false);
      return false;
    }
    // 아직 처리 중 → 계속 폴링.
    setPending(true);
    return true;
  }, []);

  const poll = useCallback(
    async (id: number): Promise<boolean> => {
      try {
        const state = await getChat(id);
        return applyState(state);
      } catch (err) {
        if (!mountedRef.current) return false;
        setError((err as Error).message || "대화 상태 조회에 실패했습니다.");
        setPending(false);
        return false;
      }
    },
    [applyState],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || pending) return;

      clearTimer();
      setError(null);
      setPending(true);
      // 사용자 메시지를 즉시 화면에 표시(낙관적 갱신).
      setMessages((prev) => [...prev, { role: "user", content: trimmed }]);

      try {
        const accepted = await sendChat({
          conversation_id: conversationId,
          message: trimmed,
          workspace_id: workspaceId,
        });
        if (!mountedRef.current) return;
        setConversationId(accepted.conversation_id);
        // 즉시 한 번 조회 후, 아직 처리 중이면 주기 폴링.
        const keepPolling = await poll(accepted.conversation_id);
        if (!mountedRef.current || !keepPolling) return;
        if (timerRef.current === null) {
          timerRef.current = setInterval(() => {
            void (async () => {
              const more = await poll(accepted.conversation_id);
              if (!more) clearTimer();
            })();
          }, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (!mountedRef.current) return;
        setError((err as Error).message || "메시지 전송에 실패했습니다.");
        setPending(false);
        clearTimer();
      }
    },
    [clearTimer, conversationId, pending, poll, workspaceId],
  );

  const reset = useCallback(() => {
    clearTimer();
    setConversationId(null);
    setMessages([]);
    setPending(false);
    setError(null);
  }, [clearTimer]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer();
    };
  }, [clearTimer]);

  return { conversationId, messages, pending, error, send, reset };
}
