import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import LogoMark from "../components/LogoMark";

const DEMO_USERS = [
  { label: "admin", user: "admin" },
  { label: "dispatch", user: "dispatch" },
  { label: "auditor", user: "auditor" },
  { label: "driver", user: "danton" },
];

export default function LoginView() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
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

  function pickDemo(u) {
    setUsername(u);
    setPassword("spotter123");
    setError(null);
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
        <div className="login-hero">
          <h1>
            your fleet,<br />planned down to the <em>minute</em>.
          </h1>
          <p>
            Plan loads against the 11 / 14 / 70 HOS rules before anyone leaves
            the yard, keep live duty status in the cab, and let the watchdog
            flag risky hours for safety.
          </p>
          <div className="hero-card">
            <div className="hero-kpis">
              <div className="hero-kpi">
                <span className="num">11h</span>
                <span>driving limit</span>
              </div>
              <div className="hero-kpi">
                <span className="num">70h</span>
                <span>cycle window</span>
              </div>
              <div className="hero-kpi">
                <span className="num">24/7</span>
                <span>duty tracking</span>
              </div>
            </div>
          </div>
        </div>

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
              <div className="input-reveal">
                <input
                  className="num"
                  type={show ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="input-reveal-btn"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {show ? "hide" : "show"}
                </button>
              </div>
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

          <div className="login-demo">
            <span className="login-demo-title">demo accounts</span>
            <div className="demo-chips">
              {DEMO_USERS.map((d) => (
                <button
                  key={d.user}
                  type="button"
                  className="chip"
                  onClick={() => pickDemo(d.user)}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          <a className="login-explore" href="/explore">
            just exploring? use the public planner →
          </a>
        </div>
      </main>
      <footer className="login-foot">
        dispatchers · drivers · hours of service
      </footer>
    </div>
  );
}