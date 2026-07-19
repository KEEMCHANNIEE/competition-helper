import { useState, useEffect } from "react";
import { FiMessageCircle } from "react-icons/fi";
import { workspace as mockWorkspace } from "../data/mockWorkspace";
import Sidebar from "../components/workspace/Sidebar";
import Header from "../components/workspace/Header";
import Dashboard from "../components/workspace/Dashboard";
import TaskSection from "../components/workspace/TaskSection";
import LogSection from "../components/workspace/LogSection";
import ReportSection from "../components/workspace/ReportSection";
import ScheduleSection from "../components/workspace/ScheduleSection";
import MeetingSection from "../components/workspace/MeetingSection";
import InsightsSection from "../components/workspace/InsightsSection";
import ContestInfoSection from "../components/workspace/ContestInfoSection";
import "../styles/workspace.css";

// --- API 헬퍼 (Chat.jsx 와 동일 규약: 세션 쿠키 포함, 401 이면 로그인으로) ---
async function apiFetch(path) {
  const res = await fetch(path, { credentials: "include" });
  if (res.status === 401) {
    window.location.href = "/auth/google/login";
    return null;
  }
  if (!res.ok) return null;
  return res;
}

// --- 정규화: 백엔드 응답 → 프론트 컴포넌트가 기대하는 mock shape ---

// DB 의 category/target/keywords 는 어떤 행은 배열, 어떤 행은 JSON 문자열('["기타"]')로
// 들쭉날쭉하다. 컴포넌트가 .map() 을 쓰므로 항상 배열로 강제한다.
function toArray(v) {
  if (Array.isArray(v)) return v;
  if (typeof v === "string") {
    const s = v.trim();
    if (s.startsWith("[")) {
      try {
        const parsed = JSON.parse(s);
        return Array.isArray(parsed) ? parsed : [s];
      } catch {
        return [s];
      }
    }
    return s ? [s] : [];
  }
  return [];
}

// "시각화 결과와 해석 (30점)" → { item, score, point }
function parseEvalCriteria(list) {
  return (list || []).map((s) => {
    const str = String(s);
    const m = str.match(/\((\d+)\s*점\)/);
    return {
      item: str.replace(/\s*\(\d+\s*점\)\s*$/, "").trim(),
      score: m ? Number(m[1]) : 0,
      point: "",
    };
  });
}

// ContestInfoSection 이 JSON.parse(contest.description) 후 접근하는 키를 모두 보장한다.
function buildDetail(d, comp) {
  const content = d.content || {};
  const schedule = d.schedule || {};
  return {
    summary: d.summary || { catchphrase: comp.title, target_detail: "" },
    content: {
      topic: content.topic || "",
      requirements: content.requirements || [],
      evaluation_criteria: content.evaluation_criteria || [],
      submission_method: content.submission_method || "",
    },
    participation: d.participation || {
      team_config: "-",
      participation_type: comp.participation_type || "",
    },
    benefits: {
      prizes: (d.benefits && d.benefits.prizes) || [],
      extra_benefits: (d.benefits && d.benefits.extra_benefits) || [],
      is_career_benefit: (d.benefits && d.benefits.is_career_benefit) || false,
    },
    schedule: {
      result_announcement: schedule.result_announcement || { date: null, note: "" },
      award_ceremony: schedule.award_ceremony || { date: null, note: "" },
    },
    keywords: d.keywords || comp.keywords || [],
    optional: d.optional || { faq: "", notes: "" },
  };
}

// 백엔드 GET /competitions/{id} dict → 프론트 contest 오브젝트
function normalizeContest(comp) {
  const d = comp.description || {};
  const content = d.content || {};
  const detail = buildDetail(d, comp);
  const keywords = toArray(comp.keywords);
  return {
    id: comp.id,
    title: comp.title || "",
    host: comp.host || comp.organizer || "",
    category: toArray(comp.category),
    target: toArray(comp.target).join(", "),
    start_date: comp.start_date || "",
    end_date: comp.deadline || "",
    submission_method: content.submission_method || "",
    requirements: content.requirements || [],
    evaluation_criteria: parseEvalCriteria(content.evaluation_criteria),
    keywords: keywords.length ? keywords : toArray(d.keywords),
    description: JSON.stringify(detail),
  };
}

// 백엔드 TaskOut[] → 프론트 task[] (백엔드에 없는 필드는 안전한 기본값)
// memberMap: { user_id: 이름 } — 담당자 이름 표시용.
function normalizeTasks(apiTasks, memberMap = {}) {
  return (apiTasks || []).map((t) => ({
    id: t.id,
    title: t.title,
    completed: t.status === "done",
    assignee: t.assignee_id ? memberMap[t.assignee_id] || `멤버 ${t.assignee_id}` : "미배정",
    priority: "Medium",
    dueDate: "",
  }));
}

export default function Workspace({ onGoToChat, onStartTaskChat, active = true }) {
  const [activeMenu, setActiveMenu] = useState("dashboard");
  const [loading, setLoading] = useState(true);

  // 실제 연결 데이터. 실패/미연결 시 mock 으로 폴백.
  const [contest, setContest] = useState(mockWorkspace.contest);
  const [tasks, setTasks] = useState(mockWorkspace.tasks);
  const [isReal, setIsReal] = useState(false);

  // 백엔드 모델이 없는 섹션은 계속 mock 사용.
  const [schedules, setSchedules] = useState(mockWorkspace.schedules);
  const [meetings, setMeetings] = useState(mockWorkspace.meetings);
  const [insights, setInsights] = useState(mockWorkspace.insights);

  // 팀원 전환 스위치용.
  const [wsId, setWsId] = useState(null);
  const [members, setMembers] = useState([]);
  const [me, setMe] = useState(null);

  // 워크스페이스가 여러 개일 때 전환용. null 이면 최신 워크스페이스를 보여준다.
  const [wsList, setWsList] = useState([]);
  const [selectedWsId, setSelectedWsId] = useState(null);

  // 실행 로그(S-02 STEP02). 워크스페이스에 연결된 대화의 role="log" 요약들.
  const [logs, setLogs] = useState([]);
  // 주간 리포트(S-03 STEP01). role="report" 로 저장된 집계 리포트들.
  const [reports, setReports] = useState([]);
  const [generatingReport, setGeneratingReport] = useState(false);

  async function handleSwitch(userId) {
    await fetch("/auth/dev/switch", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: Number(userId) }),
    });
    window.location.reload(); // 세션이 바뀌었으니 전체를 새 시점으로 다시 로드
  }

  // 할 일을 클릭하면(S-02 STEP01) 그 할 일을 어떻게 시작할지 묻는 메시지를 채팅으로 넘긴다.
  function handleStartTask(task) {
    const text = `${task.title} 해야 하는데 어떻게 시작하면 좋을까?`;
    onStartTaskChat?.(text, wsId);
  }

  // 주간 리포트 생성(S-03 STEP01): 지금 집계해 role="report" 로 저장 후 목록 갱신.
  async function handleGenerateReport() {
    if (!wsId || generatingReport) return;
    setGeneratingReport(true);
    try {
      await fetch(`/workspaces/${wsId}/weekly-report`, {
        method: "POST",
        credentials: "include",
      });
      const res = await apiFetch(`/workspaces/${wsId}/reports`);
      if (res) setReports(await res.json());
    } finally {
      setGeneratingReport(false);
    }
  }

  async function handleSetupDemo() {
    if (!wsId) return;
    await fetch(`/workspaces/${wsId}/demo-team`, {
      method: "POST",
      credentials: "include",
    });
    window.location.reload();
  }

  useEffect(() => {
    // 워크스페이스 화면이 열릴 때마다 최신 데이터로 새로고침한다
    // (채팅에서 새 워크스페이스를 만들고 돌아와도 반영되도록).
    if (!active) return;
    let cancelled = false;
    (async () => {
      try {
        const wsRes = await apiFetch("/workspaces");
        if (!wsRes) return; // 401 처리됨 or 실패 → mock 유지
        const workspaces = await wsRes.json();
        if (!workspaces.length) return; // 아직 워크스페이스 없음 → mock 유지

        setWsList(workspaces);
        // 사용자가 고른 워크스페이스가 있으면 그걸, 없으면 최신 것을 보여준다.
        const ws = workspaces.find((w) => w.id === selectedWsId) || workspaces[0];
        const [taskRes, compRes, memRes, meRes, logRes, repRes] = await Promise.all([
          apiFetch(`/workspaces/${ws.id}/tasks`),
          ws.contest_id ? apiFetch(`/competitions/${ws.contest_id}`) : Promise.resolve(null),
          apiFetch(`/workspaces/${ws.id}/members`),
          apiFetch("/me"),
          apiFetch(`/workspaces/${ws.id}/logs`),
          apiFetch(`/workspaces/${ws.id}/reports`),
        ]);

        if (cancelled) return;

        setWsId(ws.id);
        const memJson = memRes ? await memRes.json() : [];
        const memberMap = Object.fromEntries(memJson.map((m) => [m.user_id, m.name]));
        if (taskRes) setTasks(normalizeTasks(await taskRes.json(), memberMap));
        if (compRes) {
          const c = normalizeContest(await compRes.json());
          setContest(c);
          // 공식 일정(type: "contest")은 목데이터 대신 연결된 공모전의 실제
          // 접수 기간으로 만든다. 팀 일정(type: "team")은 백엔드 모델이 없어
          // 목업/수동 추가를 유지한다.
          setSchedules((prev) => [
            ...prev.filter((s) => s.type !== "contest"),
            ...(c.start_date
              ? [{ id: "official-start", title: "접수 시작 (공식)", date: c.start_date, type: "contest" }]
              : []),
            ...(c.end_date
              ? [{ id: "official-end", title: "접수 마감 (공식)", date: c.end_date, type: "contest" }]
              : []),
          ]);
        }
        setMembers(memJson);
        if (meRes) setMe(await meRes.json());
        if (logRes) setLogs(await logRes.json());
        if (repRes) setReports(await repRes.json());
        // 공모전 미연결이면 contest 는 mock 유지(화면 깨짐 방지).
        setIsReal(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, selectedWsId]);

  const completedCount = tasks.filter((t) => t.completed).length;
  const progress = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0;
  const dday = Math.ceil(
    (new Date(`${contest.end_date}T23:59:59`) - new Date()) / (1000 * 60 * 60 * 24)
  );

  // 완료 체크: 실제 워크스페이스면 서버에 저장하고(낙관적 업데이트), 실패하면 되돌린다.
  const handleToggleTask = async (id) => {
    const target = tasks.find((t) => t.id === id);
    if (!target) return;
    const nextCompleted = !target.completed;
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, completed: nextCompleted } : t)));

    if (!isReal || !wsId) return; // mock 워크스페이스는 화면 상태만 바꾸고 끝.
    try {
      const res = await fetch(`/workspaces/${wsId}/tasks/${id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextCompleted ? "done" : "todo" }),
      });
      if (!res.ok) throw new Error("저장 실패");
    } catch {
      // 저장 실패 시 화면 상태를 원래대로.
      setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, completed: !nextCompleted } : t)));
    }
  };

  // 할 일 추가: 실제 워크스페이스면 서버에 만들고, 응답으로 받은 진짜 id로 화면을 갱신한다.
  // 담당자는 이름으로 입력받아 members 목록에서 user_id를 찾는다(없으면 미배정).
  // priority/dueDate는 백엔드 Task 모델에 없는 필드라 이번 저장에서는 화면 표시로만 남는다.
  const handleAddTask = async (newTask) => {
    if (!isReal || !wsId) {
      setTasks((prev) => [...prev, { id: Date.now(), completed: false, ...newTask }]);
      return;
    }
    const matchedMember = members.find((m) => m.name === newTask.assignee);
    try {
      const res = await fetch(`/workspaces/${wsId}/tasks`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: newTask.title,
          assignee_id: matchedMember ? matchedMember.user_id : null,
        }),
      });
      if (!res.ok) throw new Error("저장 실패");
      const saved = await res.json();
      setTasks((prev) => [
        ...prev,
        {
          id: saved.id,
          completed: saved.status === "done",
          title: saved.title,
          assignee: newTask.assignee || "미배정",
          priority: newTask.priority,
          dueDate: newTask.dueDate,
        },
      ]);
    } catch {
      // 저장 실패해도 사용자가 입력한 내용은 잃지 않도록 로컬에만 추가.
      setTasks((prev) => [...prev, { id: Date.now(), completed: false, ...newTask }]);
    }
  };

  const handleAddSchedule = (newSchedule) =>
    setSchedules((prev) =>
      [...prev, { id: Date.now(), ...newSchedule }].sort((a, b) => a.date.localeCompare(b.date))
    );

  const handleAddMeeting = (newMeeting) =>
    setMeetings((prev) => [{ id: Date.now(), ...newMeeting }, ...prev]);

  const handleAddInsight = (newInsight) =>
    setInsights((prev) => [{ id: Date.now(), ...newInsight }, ...prev]);

  const workspace = { ...mockWorkspace, contest, tasks, schedules, meetings, insights };

  return (
    <div className="ws-layout">
      <Header title={contest.title} host={contest.host} dday={dday} progress={progress} />
      {isReal && (
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            padding: "8px 20px",
            background: "#EEF2FF",
            fontSize: 13,
            borderBottom: "1px solid #E5E7EB",
          }}
        >
          <span>👥 현재 시점: <b>{me?.name || "-"}</b></span>
          {wsList.length > 1 && (
            <>
              <span style={{ color: "#6B7280" }}>워크스페이스:</span>
              <select
                value={wsId ?? ""}
                onChange={(e) => setSelectedWsId(Number(e.target.value))}
                style={{ padding: "4px 8px", borderRadius: 6, maxWidth: 220 }}
              >
                {wsList.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </>
          )}
          {members.length > 1 && (
            <>
              <span style={{ color: "#6B7280" }}>팀원 전환:</span>
              <select
                value={me?.id ?? ""}
                onChange={(e) => handleSwitch(e.target.value)}
                style={{ padding: "4px 8px", borderRadius: 6 }}
              >
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.is_owner ? m.name : `${m.name} · ${m.role}`}
                  </option>
                ))}
              </select>
            </>
          )}
          <button
            onClick={handleSetupDemo}
            title="팀원 완료율을 예시(동영100·유진50·채원100·채은0)로 채웁니다"
            style={{
              marginLeft: "auto",
              padding: "4px 10px",
              borderRadius: 6,
              cursor: "pointer",
              border: "1px solid #C7D2FE",
              background: "#fff",
              color: "#4338CA",
            }}
          >
            진행 현황 시뮬레이션 (데모)
          </button>
        </div>
      )}
      {!isReal && !loading && (
        <div
          style={{
            background: "#FEF3C7",
            color: "#92400E",
            fontSize: 12,
            padding: "6px 20px",
          }}
        >
          아직 연결된 워크스페이스가 없어 예시 데이터를 보여주고 있어요. 채팅에서 "워크스페이스 만들어줘"로 시작해 보세요.
        </div>
      )}
      <div className="ws-body">
        <Sidebar activeMenu={activeMenu} onMenuChange={setActiveMenu} />
        <main className="ws-main">
          {activeMenu === "dashboard" && (
            <Dashboard
              workspace={workspace}
              progress={progress}
              onMenuChange={setActiveMenu}
              onToggleTask={handleToggleTask}
              onStartTask={isReal ? handleStartTask : undefined}
            />
          )}
          {activeMenu === "tasks" && (
            <TaskSection
              tasks={tasks}
              onToggleTask={handleToggleTask}
              onAddTask={handleAddTask}
              onStartTask={isReal ? handleStartTask : undefined}
            />
          )}
          {activeMenu === "logs" && <LogSection logs={logs} />}
          {activeMenu === "reports" && (
            <ReportSection
              reports={reports}
              onGenerate={handleGenerateReport}
              generating={generatingReport}
            />
          )}
          {activeMenu === "schedule" && (
            <ScheduleSection schedules={schedules} onAddSchedule={handleAddSchedule} />
          )}
          {activeMenu === "meetings" && (
            <MeetingSection meetings={meetings} onAddMeeting={handleAddMeeting} />
          )}
          {activeMenu === "insights" && (
            <InsightsSection insights={insights} onAddInsight={handleAddInsight} />
          )}
          {activeMenu === "contest-info" && (
            <ContestInfoSection contest={workspace.contest} />
          )}
        </main>
      </div>
      <button className="ws-ai-float" onClick={onGoToChat}>
        <FiMessageCircle size={15} />
        AI Assistant
      </button>
    </div>
  );
}
