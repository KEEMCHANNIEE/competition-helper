import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { Recommend } from "../src/pages/Recommend";
import type { JobResult, RecommendAccepted } from "../src/api/types";

// 엔드포인트 모듈 전체를 모킹 — 페이지/훅은 이 함수들만 호출한다.
vi.mock("../src/api/endpoints", () => ({
  requestRecommend: vi.fn(),
  getRecommendJob: vi.fn(),
}));

import { requestRecommend, getRecommendJob } from "../src/api/endpoints";

const requestRecommendMock = vi.mocked(requestRecommend);
const getRecommendJobMock = vi.mocked(getRecommendJob);

describe("Recommend page", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    requestRecommendMock.mockReset();
    getRecommendJobMock.mockReset();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("초기에는 추천 받기 버튼을 보여준다", () => {
    render(<Recommend />);
    expect(
      screen.getByRole("button", { name: "추천 받기" }),
    ).toBeInTheDocument();
  });

  it("요청 후 로딩을 표시하고, 폴링이 done 되면 결과를 보여준다", async () => {
    const accepted: RecommendAccepted = { job_id: "job-123" };
    requestRecommendMock.mockResolvedValue(accepted);

    const running: JobResult = {
      job_id: "job-123",
      status: "running",
      results: [],
      error: null,
    };
    const done: JobResult = {
      job_id: "job-123",
      status: "done",
      results: [
        {
          competition_id: 42,
          title: "AI 해커톤 2026",
          reason: "당신의 Python·AI 관심사와 잘 맞습니다.",
          score: 0.91,
        },
      ],
      error: null,
    };
    // 첫 즉시 폴링 → running, 이후 인터벌 폴링 → done
    getRecommendJobMock
      .mockResolvedValueOnce(running)
      .mockResolvedValue(done);

    render(<Recommend />);

    fireEvent.click(screen.getByRole("button", { name: "추천 받기" }));

    // requestRecommend + 첫 즉시 폴링(running) 처리 → 로딩 표시
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(requestRecommendMock).toHaveBeenCalledTimes(1);

    // 2초 경과 → 인터벌 폴링이 done 반환
    await vi.advanceTimersByTimeAsync(2000);

    await waitFor(() => {
      expect(screen.getByText("AI 해커톤 2026")).toBeInTheDocument();
    });
    expect(
      screen.getByText("당신의 Python·AI 관심사와 잘 맞습니다."),
    ).toBeInTheDocument();
    expect(getRecommendJobMock).toHaveBeenCalledWith("job-123");
  });

  it("작업이 failed 면 에러를 표시한다", async () => {
    requestRecommendMock.mockResolvedValue({ job_id: "job-err" });
    getRecommendJobMock.mockResolvedValue({
      job_id: "job-err",
      status: "failed",
      results: [],
      error: "LLM 호출 실패",
    });

    render(<Recommend />);
    fireEvent.click(screen.getByRole("button", { name: "추천 받기" }));

    await vi.advanceTimersByTimeAsync(0);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("LLM 호출 실패");
    });
  });
});
