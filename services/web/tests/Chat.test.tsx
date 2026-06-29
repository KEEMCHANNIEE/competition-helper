import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { Chat } from "../src/pages/Chat";
import type { ChatAccepted, ChatState } from "../src/api/types";

// 엔드포인트 모듈 전체를 모킹 — 페이지/훅은 이 함수들만 호출한다.
vi.mock("../src/api/endpoints", () => ({
  sendChat: vi.fn(),
  getChat: vi.fn(),
}));

import { sendChat, getChat } from "../src/api/endpoints";

const sendChatMock = vi.mocked(sendChat);
const getChatMock = vi.mocked(getChat);

describe("Chat page", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sendChatMock.mockReset();
    getChatMock.mockReset();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("초기에는 보내기 버튼과 입력창을 보여준다", () => {
    render(<Chat />);
    expect(screen.getByRole("button", { name: "보내기" })).toBeInTheDocument();
    expect(screen.getByLabelText("메시지 입력")).toBeInTheDocument();
  });

  it("메시지를 보내면 폴링 후 어시스턴트 답변을 보여준다", async () => {
    const accepted: ChatAccepted = { conversation_id: 1, job_id: "j1" };
    sendChatMock.mockResolvedValue(accepted);

    const pendingState: ChatState = {
      conversation_id: 1,
      pending: true,
      messages: [{ role: "user", content: "안녕 추천해줘" }],
      error: null,
    };
    const doneState: ChatState = {
      conversation_id: 1,
      pending: false,
      messages: [
        { role: "user", content: "안녕 추천해줘" },
        { role: "assistant", content: "AI 해커톤 2026 을 추천해요." },
      ],
      error: null,
    };
    // 첫 즉시 폴링 → pending, 이후 인터벌 폴링 → done
    getChatMock.mockResolvedValueOnce(pendingState).mockResolvedValue(doneState);

    render(<Chat />);

    const input = screen.getByLabelText("메시지 입력");
    fireEvent.change(input, { target: { value: "안녕 추천해줘" } });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));

    // sendChat + 첫 즉시 폴링(pending) 처리 → 사용자 메시지 표시 + 로딩 표시
    await vi.advanceTimersByTimeAsync(0);
    expect(sendChatMock).toHaveBeenCalledTimes(1);
    expect(sendChatMock).toHaveBeenCalledWith({
      conversation_id: null,
      message: "안녕 추천해줘",
      workspace_id: null,
    });
    expect(screen.getByText("안녕 추천해줘")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();

    // 2초 경과 → 인터벌 폴링이 done 반환
    await vi.advanceTimersByTimeAsync(2000);

    await waitFor(() => {
      expect(
        screen.getByText("AI 해커톤 2026 을 추천해요."),
      ).toBeInTheDocument();
    });
    expect(getChatMock).toHaveBeenCalledWith(1);
  });

  it("에러가 오면 에러 배너를 표시한다", async () => {
    sendChatMock.mockResolvedValue({ conversation_id: 2, job_id: "j2" });
    getChatMock.mockResolvedValue({
      conversation_id: 2,
      pending: false,
      messages: [{ role: "user", content: "계획 짜줘" }],
      error: "에이전트 호출 실패",
    });

    render(<Chat />);
    fireEvent.change(screen.getByLabelText("메시지 입력"), {
      target: { value: "계획 짜줘" },
    });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));

    await vi.advanceTimersByTimeAsync(0);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("에이전트 호출 실패");
    });
  });
});
