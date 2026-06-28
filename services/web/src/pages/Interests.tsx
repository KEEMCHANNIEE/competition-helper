import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getMe, updateMe } from "../api/endpoints";
import { Loading } from "../components/Loading";
import { ErrorBanner } from "../components/ErrorBanner";

/** 쉼표/줄바꿈으로 구분된 문자열 ↔ 배열 변환. */
function toList(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function Interests() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [interests, setInterests] = useState("");
  const [skills, setSkills] = useState("");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const me = await getMe();
        if (!active) return;
        setInterests(me.interests.join(", "));
        setSkills(me.skills.join(", "));
      } catch (err) {
        if (active) setError((err as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await updateMe({ interests: toList(interests), skills: toList(skills) });
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Loading label="내 정보를 불러오는 중..." />;

  return (
    <section className="page">
      <h1>관심사 & 스킬</h1>
      <p className="muted">
        쉼표(,) 또는 줄바꿈으로 구분해 입력하세요. 빈 값도 저장할 수 있어요.
      </p>

      {error && <ErrorBanner message={error} />}

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>관심사</span>
          <textarea
            value={interests}
            onChange={(e) => setInterests(e.target.value)}
            placeholder="예: AI, 데이터 분석, 핀테크"
            rows={3}
          />
        </label>

        <label className="field">
          <span>스킬</span>
          <textarea
            value={skills}
            onChange={(e) => setSkills(e.target.value)}
            placeholder="예: Python, React, SQL"
            rows={3}
          />
        </label>

        <div className="form__actions">
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? "저장 중..." : "저장"}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => navigate("/recommend")}
          >
            추천 받으러 가기
          </button>
        </div>

        {saved && <p className="success">저장되었습니다.</p>}
      </form>
    </section>
  );
}
