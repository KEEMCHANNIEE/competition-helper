import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getWorkspaceTasks } from "../api/endpoints";
import type { Task } from "../api/types";
import { Loading } from "../components/Loading";
import { ErrorBanner } from "../components/ErrorBanner";

/** week_no(null 은 "미지정") 기준으로 그룹핑하고 주차 오름차순 정렬. */
function groupByWeek(tasks: Task[]): { week: number | null; tasks: Task[] }[] {
  const map = new Map<number | null, Task[]>();
  for (const t of tasks) {
    const key = t.week_no ?? null;
    const arr = map.get(key);
    if (arr) arr.push(t);
    else map.set(key, [t]);
  }
  return Array.from(map.entries())
    .sort((a, b) => {
      // null(미지정)은 항상 맨 뒤로.
      if (a[0] === null) return 1;
      if (b[0] === null) return -1;
      return a[0] - b[0];
    })
    .map(([week, group]) => ({ week, tasks: group }));
}

const STATUS_LABEL: Record<string, string> = {
  todo: "할 일",
  in_progress: "진행 중",
  doing: "진행 중",
  done: "완료",
};

/**
 * 워크스페이스 계획 화면 — 생성된 할 일을 주차별로 보여준다.
 * 라우트: /workspace/:id/plan
 */
export function Plan() {
  const params = useParams<{ id: string }>();
  const workspaceId = Number(params.id);

  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(workspaceId) || workspaceId <= 0) {
      setError("올바른 워크스페이스 ID 가 아닙니다.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getWorkspaceTasks(workspaceId);
      setTasks(data);
    } catch (err) {
      setError((err as Error).message || "할 일을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = groupByWeek(tasks);

  return (
    <section className="page">
      <header className="chat-page__head">
        <div>
          <h1>계획 · 할 일</h1>
          <p className="muted">워크스페이스 #{params.id} 의 주차별 계획입니다.</p>
        </div>
        <button type="button" className="btn" onClick={() => void load()}>
          새로고침
        </button>
      </header>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading && <Loading label="할 일을 불러오는 중..." />}

      {!loading && !error && tasks.length === 0 && (
        <p className="muted">
          아직 생성된 할 일이 없습니다. 대화에서 “계획 짜줘”라고 요청해 보세요.
        </p>
      )}

      {!loading && groups.length > 0 && (
        <div className="plan-weeks">
          {groups.map(({ week, tasks: weekTasks }) => (
            <div className="plan-week card" key={week ?? "none"}>
              <h2 className="plan-week__title">
                {week === null ? "주차 미지정" : `${week}주차`}
              </h2>
              <ul className="plan-task-list">
                {weekTasks.map((t) => (
                  <li className="plan-task" key={t.id}>
                    <div className="plan-task__head">
                      <strong>{t.title}</strong>
                      <span className={`badge badge--status status-${t.status}`}>
                        {STATUS_LABEL[t.status] ?? t.status}
                      </span>
                    </div>
                    {t.description && (
                      <p className="plan-task__desc">{t.description}</p>
                    )}
                    <p className="plan-task__meta muted">
                      담당:{" "}
                      {t.assignee_id !== null
                        ? `user #${t.assignee_id}`
                        : "미배정"}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
