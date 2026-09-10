import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import LogoMark from "../components/LogoMark";

export default function LoginView() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await login(username.trim(), password);
      navigate(user.role === "Dispatcher" ? "/dispatch" : "/", { replace: true });
    } catch (err) {
      setError(err.message || "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <header className="topbar login-topbar">
        <div className="topbar-brand">
          <LogoMark />
        </div>
        <span className="topbar-label">fleet · dispatch · logs</span>
      </header>
      <main className="login-main">
        <div className="login-card">
          <h1 className="login-title">Sign in to Spotter</h1>
          <p className="login-sub">
            the same planner, now with your fleet behind it.
          </p>
          <form onSubmit={submit} className="login-form">
            <label className="field">
              <span className="field-label">Username</span>
              <input
                className="num"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                required
              />
            </label>
            <label className="field">
              <span className="field-label">Password</span>
              <input
                className="num"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            {error && (
              <div className="panel-error" role="alert">
                <p className="panel-error-title">Could not sign in.</p>
                <p>{error}</p>
              </div>
            )}
            <button type="submit" className="btn-plan" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <a className="login-explore" href="/explore">
            just exploring? use the public planner →
          </a>
        </div>
        <div className="login-foot">
          dispatchers · drivers · hours of service
        </div>
      </main>
    </div>
  );
}