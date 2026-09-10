import { useRef, useState } from "react";
import "./App.css";
import LogoMark from "./components/LogoMark";
import GeocodeField from "./components/GeocodeField";
import RouteMap from "./components/RouteMap";
import LogSheet from "./components/LogSheet";
import HoursCluster from "./components/HoursCluster";
import StopTimeline from "./components/StopTimeline";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export default function App() {
  const [form, setForm] = useState({
    current_location: "",
    pickup_location: "",
    dropoff_location: "",
    current_cycle_used: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const canvasRef = useRef(null);

  const valid =
    form.current_location.trim() &&
    form.pickup_location.trim() &&
    form.dropoff_location.trim() &&
    form.current_cycle_used !== "";

  const onField = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/api/trip/plan/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, current_cycle_used: Number(form.current_cycle_used) }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        if (typeof data === "object" && data.error) throw new Error(data.error);
        const detail = Object.entries(data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`)
          .join("; ");
        throw new Error(detail || "Invalid request");
      }
      setResult(data);
      canvasRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      setError(err.message || "Something went wrong. Try different locations.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-brand">
          <LogoMark />
        </div>
        <span className="topbar-label">trip planner</span>
      </header>

      <div className="shell">
        <aside className="rail">
          <TripForm
            form={form}
            onField={onField}
            onSubmit={submit}
            loading={loading}
            valid={valid}
          />
          {error && (
            <div className="panel-error" role="alert">
              <p className="panel-error-title">Could not plan that trip.</p>
              <p>{error}</p>
            </div>
          )}
        </aside>

        <main className="canvas" ref={canvasRef}>
          {!result && !loading && <EmptyState />}

          {loading && <LoadingState />}

          {result && (
            <div className="results">
              <RouteSummary
                route={result.route}
                pickup={form.pickup_location.trim()}
                dropoff={form.dropoff_location.trim()}
              />

              <RouteMap geometry={result.route.geometry} stops={result.stops} />

              <HoursCluster usage={result.usage} />

              <StopTimeline stops={result.stops} />

              <h2 className="section-head">Daily logs</h2>
              <div className="logs">
                {result.daily_logs.map((day, i) => (
                  <div key={i} className="sheet-stagger" style={{ animationDelay: `${i * 150}ms` }}>
                    <LogSheet day={day} index={i} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function TripForm({ form, onField, onSubmit, loading, valid }) {
  return (
    <form className="trip-form" onSubmit={onSubmit}>
      <h2 className="rail-title">Plan a trip</h2>
      <GeocodeField
        label="Current location"
        value={form.current_location}
        onChange={onField("current_location")}
        placeholder="Dallas, TX"
      />
      <GeocodeField
        label="Pickup location"
        value={form.pickup_location}
        onChange={onField("pickup_location")}
        placeholder="Memphis, TN"
      />
      <GeocodeField
        label="Dropoff location"
        value={form.dropoff_location}
        onChange={onField("dropoff_location")}
        placeholder="Chicago, IL"
      />
      <label className="field">
        <span className="field-label">Cycle used</span>
        <span className="field-input-wrap cycle-wrap">
          <input
            className="num"
            type="number"
            min="0"
            max="70"
            step="0.5"
            value={form.current_cycle_used}
            onChange={(e) => onField("current_cycle_used")(e.target.value)}
            placeholder="30"
            required
          />
          <span className="cycle-unit">hrs</span>
        </span>
      </label>
      <button
        type="submit"
        className="btn-plan"
        disabled={!valid || loading}
      >
        {loading ? "Planning…" : "Plan trip"}
      </button>
    </form>
  );
}

function RouteSummary({ route, pickup, dropoff }) {
  return (
    <div className="route-summary">
      <span>{pickup}</span>
      <span className="route-arrow">→</span>
      <span>{dropoff}</span>
      <span className="route-sep">·</span>
      <span className="num route-miles">{route.distance_miles}</span>
      <span className="route-unit">mi</span>
      {route.highways?.length > 0 && (
        <>
          <span className="route-sep">·</span>
          <span className="roadshield">{route.highways.join(" / ")}</span>
        </>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty">
      <EmptyGrid />
      <p className="empty-copy">enter a trip to generate the route and logs.</p>
    </div>
  );
}

/** faint, unfilled version of the log grid as the empty-state placeholder */
function EmptyGrid() {
  const rows = [4, 0, 1, 3]; // off duty / sleeper / driving / on duty row lines
  return (
    <svg className="empty-grid" viewBox="0 0 560 200" aria-hidden="true">
      {rows.map((y) => (
        <line key={y} x1="0" x2="560" y1={40 + y * 32} y2={40 + y * 32} stroke="#0a4e61" strokeWidth="1" />
      ))}
      {Array.from({ length: 25 }, (_, h) => (
        <line key={h} x1={(h / 24) * 520 + 20} x2={(h / 24) * 520 + 20} y1="40" y2="170" stroke="#043b4c" />
      ))}
    </svg>
  );
}

function LoadingState() {
  return (
    <div className="loading">
      <div className="sk-map" />
      <div className="sk-row">
        <div className="sk-gauge" />
        <div className="sk-gauge" />
        <div className="sk-gauge" />
      </div>
      <div className="sk-log" />
    </div>
  );
}