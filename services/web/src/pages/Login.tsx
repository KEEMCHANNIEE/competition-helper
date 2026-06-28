import { login } from "../api/endpoints";

export function Login() {
  return (
    <main className="auth-page">
      <div className="card auth-card">
        <h1 className="auth-card__title">contest-helper</h1>
        <p className="auth-card__subtitle">
          관심사에 맞는 공모전을 AI 가 추천해 드려요.
        </p>
        <button
          type="button"
          className="btn btn--google"
          onClick={() => login()}
        >
          Google로 로그인
        </button>
      </div>
    </main>
  );
}
