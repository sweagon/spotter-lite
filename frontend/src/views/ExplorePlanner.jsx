import { useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../api";
import PlannerForm from "../components/PlannerForm";
import PlanResults from "../components/PlanResults";
import LogoMark from "../components/LogoMark";
import Board from "../components/Board";

/** public, stateless planner — the original assessment demo. no login, no
 * persistence; the full tools live behind the org screens. */
export default function ExplorePlanner() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [routeLabels, setRouteLabels] = useState({ pickup: "", dropoff: "" });

  async function plan(payload) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/api/trip/plan/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data?.error || Object.values(data || {}).join("; "));
      setRouteLabels({
        pickup: payload.pickup_location,
        dropoff: payload.dropoff_location,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Something went wrong. Try different locations.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-brand">
          <LogoMark />
        </div>
        <span className="topbar-label">trip planner</span>
        <Link className="topbar-login" to="/login">sign in →</Link>
      </header>

      <Board className="planner-shell"
        rail={
          <>
            <p className="rail-hello">public planner</p>
            <PlannerForm onSubmit={plan} submitting={busy} />
          </>
        }
      >
        {error && (
          <div className="panel-error" role="alert" style={{ marginBottom: 16 }}>
            <p className="panel-error-title">We couldn't plan that trip.</p>
            <p>{error}</p>
          </div>
        )}
        {!result && !busy && (
          <div className="empty">
            <p className="empty-copy">Enter a pickup and drop-off to generate the route, hours and log sheets.</p>
          </div>
        )}
        {busy && <p className="plan-busy">planning…</p>}
        {result && (
          <PlanResults
            result={result}
            pickup={routeLabels.pickup}
            dropoff={routeLabels.dropoff}
          />
        )}
      </Board>
    </div>
  );
}