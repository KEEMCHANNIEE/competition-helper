import { useState, useEffect } from "react";

// 401 이면 구글 로그인으로. (Chat/Workspace 와 동일 규약)
async function apiFetch(path, options = {}) {
  const res = await fetch(path, { credentials: "include", ...options });
  if (res.status === 401) {
    window.location.href = "/auth/google/login";
    return null;
  }
  if (!res.ok) return null;
  return res;
}

async function postJSON(path, body) {
  return fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// 역할별 아바타 색.
const AVATAR = {
  owner: { bg: "#DBEAFE", fg: "#2563EB" },
  "데이터 분석": { bg: "#DCFCE7", fg: "#16A34A" },
  기획: { bg: "#FEF3C7", fg: "#D97706" },
  디자인: { bg: "#FCE7F3", fg: "#DB2777" },
};

function initial(name) {
  return (name || "?").trim().charAt(0);
}

export default function MemberSelect({ onEnter }) {
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [entering, setEntering] = useState(null); // 선택 중인 user_id

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // 1) 워크스페이스 확보(없으면 생성).
        const wsRes = await apiFetch("/workspaces");
        if (!wsRes) return; // 401 → 로그인 이동
        let list = await wsRes.json();
        let wsId;
        if (!list.length) {
          const cr = await postJSON("/workspaces", { name: "우리 팀 워크스페이스" });
          wsId = (await cr.json()).id;
        } else {
          wsId = list[0].id;
        }
        // 2) 멤버 확보(4명 미만이면 데모 팀 구성).
        let mres = await apiFetch(`/workspaces/${wsId}/members`);
        let ms = mres ? await mres.json() : [];
        if (ms.length < 4) {
          const dres = await postJSON(`/workspaces/${wsId}/demo-team`);
          ms = await dres.json();
        }
        if (!cancelled) setMembers(ms);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function pick(m) {
    setEntering(m.user_id);
    await postJSON("/auth/dev/switch", { user_id: m.user_id });
    onEnter();
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#F8FAFC",
        color: "#111827",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: -0.2, marginBottom: 8 }}>
        ConMate
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, marginBottom: 6 }}>
        누구로 시작할까요?
      </div>
      <div style={{ fontSize: 14, color: "#6B7280", marginBottom: 32 }}>
        팀원을 선택하면 그 사람 시점으로 워크스페이스에 들어갑니다.
      </div>

      {loading ? (
        <div style={{ color: "#9CA3AF", fontSize: 14 }}>팀 정보를 불러오는 중…</div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(220px, 260px))",
            gap: 16,
          }}
        >
          {members.map((m) => {
            const color = AVATAR[m.is_owner ? "owner" : m.role] || AVATAR.owner;
            return (
              <button
                key={m.user_id}
                onClick={() => pick(m)}
                disabled={entering !== null}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "18px 20px",
                  background: "#fff",
                  border: "1px solid #E5E7EB",
                  borderRadius: 12,
                  cursor: entering !== null ? "default" : "pointer",
                  textAlign: "left",
                  boxShadow: "0 1px 2px rgba(0,0,0,0.03)",
                  opacity: entering !== null && entering !== m.user_id ? 0.5 : 1,
                  transition: "border-color .15s, box-shadow .15s",
                }}
                onMouseEnter={(e) => {
                  if (entering === null) {
                    e.currentTarget.style.borderColor = "#2563EB";
                    e.currentTarget.style.boxShadow = "0 4px 12px rgba(37,99,235,0.12)";
                  }
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "#E5E7EB";
                  e.currentTarget.style.boxShadow = "0 1px 2px rgba(0,0,0,0.03)";
                }}
              >
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: "50%",
                    background: color.bg,
                    color: color.fg,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 18,
                    fontWeight: 700,
                    flexShrink: 0,
                  }}
                >
                  {initial(m.name)}
                </div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>
                    {m.name}
                    {m.is_owner && (
                      <span
                        style={{
                          marginLeft: 6,
                          fontSize: 11,
                          color: "#2563EB",
                          background: "#EFF6FF",
                          padding: "2px 6px",
                          borderRadius: 6,
                        }}
                      >
                        나
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: "#6B7280", marginTop: 2 }}>
                    {m.is_owner ? "팀장" : m.role}
                  </div>
                </div>
                {entering === m.user_id && (
                  <span style={{ marginLeft: "auto", fontSize: 12, color: "#9CA3AF" }}>
                    입장 중…
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
