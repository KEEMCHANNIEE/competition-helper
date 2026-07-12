import { useEffect, useState } from "react";
import { FiBell, FiX } from "react-icons/fi";

// 입장 시 미확인 알림을 조회해 상단 토스트로 보여준다(S-03 STEP03).
// 팀장이 계획을 조정하면 대상 팀원에게 알림이 발송되고, 그 팀원이 입장하면 여기서 뜬다.
export default function NotificationToast() {
  const [items, setItems] = useState([]);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/notifications", { credentials: "include" });
        if (res.ok) setItems(await res.json());
      } catch { /* 무시 */ }
    })();
  }, []);

  async function dismissAll() {
    setItems([]);
    try {
      await fetch("/notifications/read", { method: "POST", credentials: "include" });
    } catch { /* 무시 */ }
  }

  if (!items.length) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 16,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        width: "min(520px, calc(100vw - 32px))",
      }}
    >
      {items.map((n) => (
        <div
          key={n.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "#111827",
            color: "#fff",
            borderRadius: 10,
            padding: "12px 14px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
          }}
        >
          <span
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              background: "#4F46E5",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <FiBell size={15} />
          </span>
          <span style={{ fontSize: 13.5, fontWeight: 500, flex: 1, lineHeight: 1.5 }}>
            {n.text}
          </span>
          <button
            onClick={dismissAll}
            title="확인"
            style={{
              background: "transparent",
              border: "none",
              color: "#9CA3AF",
              cursor: "pointer",
              display: "flex",
              padding: 4,
            }}
          >
            <FiX size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
