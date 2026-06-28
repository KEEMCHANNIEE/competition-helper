import { useState } from "react";

import {
  attachRecommendations,
  createWorkspace,
  getWorkspace,
  inviteMember,
} from "../api/endpoints";
import type { WorkspaceDetail } from "../api/types";
import { Loading } from "../components/Loading";
import { ErrorBanner } from "../components/ErrorBanner";

export function Workspace() {
  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 폼 상태
  const [newName, setNewName] = useState("");
  const [openId, setOpenId] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [attachIds, setAttachIds] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  async function refresh(id: number) {
    setLoading(true);
    setError(null);
    try {
      const ws = await getWorkspace(id);
      setWorkspace(ws);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      const ws = await createWorkspace(newName.trim());
      setNewName("");
      setNotice(`워크스페이스 #${ws.id} 생성됨`);
      await refresh(ws.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleOpen(e: React.FormEvent) {
    e.preventDefault();
    const id = Number(openId);
    if (!Number.isFinite(id) || id <= 0) {
      setError("올바른 워크스페이스 ID 를 입력하세요.");
      return;
    }
    await refresh(id);
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!workspace) return;
    setError(null);
    setNotice(null);
    try {
      const member = await inviteMember(
        workspace.id,
        inviteEmail.trim(),
        inviteRole,
      );
      setInviteEmail("");
      setNotice(`멤버 초대됨 (user #${member.user_id}, ${member.role})`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleAttach(e: React.FormEvent) {
    e.preventDefault();
    if (!workspace) return;
    setError(null);
    setNotice(null);
    const ids = attachIds
      .split(/[,\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0);
    if (ids.length === 0) {
      setError("추천 ID 를 하나 이상 입력하세요.");
      return;
    }
    try {
      const res = await attachRecommendations(workspace.id, ids);
      setAttachIds("");
      setNotice(`${res.attached}건의 추천을 팀에 저장했습니다.`);
      await refresh(workspace.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="page">
      <h1>워크스페이스</h1>

      {error && <ErrorBanner message={error} />}
      {notice && <p className="success">{notice}</p>}

      <div className="grid-2">
        <form className="form card" onSubmit={handleCreate}>
          <h2>팀 생성</h2>
          <label className="field">
            <span>팀 이름</span>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="예: AI 공모전 스터디"
              required
            />
          </label>
          <button type="submit" className="btn btn--primary">
            생성
          </button>
        </form>

        <form className="form card" onSubmit={handleOpen}>
          <h2>팀 열기</h2>
          <label className="field">
            <span>워크스페이스 ID</span>
            <input
              value={openId}
              onChange={(e) => setOpenId(e.target.value)}
              placeholder="예: 1"
              inputMode="numeric"
            />
          </label>
          <button type="submit" className="btn">
            불러오기
          </button>
        </form>
      </div>

      {loading && <Loading label="워크스페이스를 불러오는 중..." />}

      {workspace && (
        <div className="card workspace-detail">
          <header className="workspace-detail__head">
            <h2>
              {workspace.name}{" "}
              <span className="muted">#{workspace.id}</span>
            </h2>
            <span className="muted">owner: user #{workspace.owner_id}</span>
          </header>

          <div className="grid-2">
            <form className="form" onSubmit={handleInvite}>
              <h3>멤버 초대</h3>
              <label className="field">
                <span>이메일</span>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="teammate@example.com"
                  required
                />
              </label>
              <label className="field">
                <span>역할</span>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                >
                  <option value="member">member</option>
                  <option value="owner">owner</option>
                </select>
              </label>
              <button type="submit" className="btn btn--primary">
                초대
              </button>
            </form>

            <form className="form" onSubmit={handleAttach}>
              <h3>추천 공유</h3>
              <label className="field">
                <span>추천 ID (쉼표/공백 구분)</span>
                <input
                  value={attachIds}
                  onChange={(e) => setAttachIds(e.target.value)}
                  placeholder="예: 12, 34, 56"
                />
              </label>
              <button type="submit" className="btn btn--primary">
                팀에 저장
              </button>
            </form>
          </div>

          <h3>공유된 추천</h3>
          {workspace.recommendations.length === 0 ? (
            <p className="muted">아직 공유된 추천이 없습니다.</p>
          ) : (
            <ul className="shared-list">
              {workspace.recommendations.map((r) => (
                <li key={r.id} className="shared-list__item">
                  <strong>{r.title}</strong>
                  <span className="muted"> · 공모전 #{r.competition_id}</span>
                  <p>{r.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
