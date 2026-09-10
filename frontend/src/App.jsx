import { useRef, useState } from "react";
import "./App.css";
import RouteMap from "./components/RouteMap";
import LogSheet from "./components/LogSheet";

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
  const resultsRef = useRef(null);

  const onField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
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
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth" }), 80);
    } catch (err) {
      setError(err.message || "Something went wrong. Try different locations.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">◆</div>
          <h1>
            Spotter <span>trip planner</span>
          </h1>
        </div>
        <p className="tagline">
          Plan a load, see the route, and get the federal hours-of-service log
          sheets — computed against the 11/14/8/70 rules of 49&nbsp;CFR&nbsp;§395.
        </p>
      </header>

      <section className="panel form-panel">
        <TripForm form={form} onField={onField} onSubmit={submit} loading={loading} />
        {error && (
          <div className="banner banner-error">
            <strong>Could not plan that trip.</strong> {error}
          </div>
        )}
      </section>

      {loading && (
        <section className="panel loading-panel">
          <div className="spinner" />
          <p>Geocoding locations, fetching the route from OSRM, and walking the HOS timeline minute-by-minute…</p>
        </section>
      )}

      {result && (
        <section ref={resultsRef} className="results">
          <TripSummary
            route={result.route}
            stops={result.stops}
            totalLogs={result.daily_logs.length}
          />

          <div className="results-grid">
            <RouteMap geometry={result.route.geometry} stops={result.stops} />
            <div className="panel stops-panel">
              <h3>Stops along the way</h3>
              <p className="muted-copy">
                Pickup and dropoff include 1&nbsp;hr of on-duty-not-driving each. Fuel
                stops are forced every 1,000 miles; 30-min breaks land after 8 hrs
                of cumulative driving.
              </p>
              <ol className="stops-list">
                {result.stops.map((s, i) => (
                  <li key={i}>
                    <span className={`stop-dot stop-dot-${s.status}`} />
                    <div className="stop-info">
                      <strong>{s.label}</strong>
                      <span className="muted">
                        {s.kind} · {s.time} · {s.duration_min} min · {s.location}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>

          <h2 className="section-title">Daily driver's logs</h2>
          <div className="logs-list">
            {result.daily_logs.map((day, i) => (
              <LogSheet key={i} day={day} index={i} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function TripForm({ form, onField, onSubmit, loading }) {
  return (
    <form className="trip-form" onSubmit={onSubmit}>
      <label>
        Current location
        <input
          type="text"
          value={form.current_location}
          onChange={onField("current_location")}
          placeholder="e.g. Dallas, TX"
          required
        />
      </label>
      <label>
        Pickup location
        <input
          type="text"
          value={form.pickup_location}
          onChange={onField("pickup_location")}
          placeholder="e.g. Memphis, TN"
          required
        />
      </label>
      <label>
        Dropoff location
        <input
          type="text"
          value={form.dropoff_location}
          onChange={onField("dropoff_location")}
          placeholder="e.g. Chicago, IL"
          required
        />
      </label>
      <label className="cycle-field">
        Cycle used (hrs)
        <input
          type="number"
          min="0"
          max="70"
          step="0.5"
          value={form.current_cycle_used}
          onChange={onField("current_cycle_used")}
          placeholder="e.g. 30"
          required
        />
        <small>of your 70-hr / 8-day window</small>
      </label>
      <button type="submit" className="btn-primary" disabled={loading}>
        {loading ? "Planning…" : "Plan trip"}
      </button>
    </form>
  );
}

function TripSummary({ route, stops, totalLogs }) {
  const driveHrs = (route.driving_minutes / 60).toFixed(1);
  return (
    <div className="trip-summary">
      <SummaryItem num={route.distance_miles} label="miles" />
      <SummaryItem num={driveHrs} label="hours driving" />
      <SummaryItem num={stops.length} label="stops" />
      <SummaryItem num={totalLogs} label="log sheets" />
    </div>
  );
}

function SummaryItem({ num, label }) {
  return (
    <div className="summary-item">
      <span className="summary-num">{num}</span>
      <span className="summary-label">{label}</span>
    </div>
  );
}