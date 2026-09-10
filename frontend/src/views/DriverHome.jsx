import { useEffect, useState } from "react";
import { apiJson } from "../api";
import PlannerForm from "../components/PlannerForm";
import PlanResults from "../components/PlanResults";
import { useAuth } from "../auth";

export default function DriverHome() {
  const { user } = useAuth();
  const [me, setMe] = useState(null);
  const [trips, setTrips] = useState([]);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiJson("/api/me/").then(({ ok, data }) => ok && setMe(data));
    async function initialFetch() {
      const { ok, data } = await apiJson("/api/trips/");
      if (ok) setTrips(data);
    }
    initialFetch();
  }, []);

  async function refreshTrips() {
    const { ok, data } = await apiJson("/api/trips/");
    if (ok) setTrips(data);
  }

  async function plan(payload) {
    setBusy(true);
    setError(null);
    setSelected(null);
    try {
      const { ok, data } = await apiJson("/api/trips/plan/", {
        method: "POST",
        body: { ...payload, driver_id: me?.driver?.id, vehicle_id: me?.driver?.vehicle_id ?? null },
      });
      if (ok) {
        setResult(data);
        refreshTrips();
      } else {
        setError(data?.error || "Could not plan that trip.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function openTrip(tripId) {
    const { ok, data } = await apiJson(`/api/trips/${tripId}/`);
    if (ok) {
      setResult(null);
      setSelected(data);
    }
  }

  const activeTrip = selected;

  return (
    <div className="shell driver-shell">
      <aside className="rail">
        <p className="rail-hello">
          {user.first_name || user.username}
          {activeTrip ? " · trip view" : " · plan view"}
        </p>
        {me?.driver && (
          <section className="hos-card">
            <div className="hos-card-row">
              <span>cycle used</span>
              <span className="num">
                {me.driver.cycle_used}
                <small> / 70</small>
              </span>
            </div>
            <div className="hos-card-row">
              <span>vehicle</span>
              <span className="num">{me.driver.vehicle_unit || "—"}</span>
            </div>
            {me.alerts?.length > 0 && (
              <div className="hos-alerts">
                <p className="hos-alerts-title">watchdog flags</p>
                {me.alerts.map((a) => (
                  <p key={a.id} className="hos-alert">
                    {a.rule.replace("_", " ")} · {a.detail || "check hours"}
                  </p>
                ))}
              </div>
            )}
          </section>
        )}

        <div className={`rail-block ${!activeTrip ? "rail-active" : ""}`}>
          <button className="rail-link" onClick={() => { setSelected(null); setResult(null); }} disabled={!activeTrip && !result}>
            ← plan a trip
          </button>
        </div>

        <section>
          <h3 className="rail-sub">my trips</h3>
          <div className="trip-list">
            {trips.length === 0 && (
              <p className="trip-empty">no trips yet — the plan form starts one.</p>
            )}
            {trips.slice(0, 15).map((t) => (
              <button
                key={t.id}
                className={`trip-row ${activeTrip?.id === t.id ? "trip-active" : ""}`}
                onClick={() => openTrip(t.id)}
              >
                <span className="trip-row-main">
                  <span className="trip-id">#{t.id}</span>
                  <span className="trip-route">
                    {t.pickup_location} → {t.dropoff_location}
                  </span>
                </span>
                <span className={`badge badge-${t.status}`}>{t.status_label}</span>
              </button>
            ))}
          </div>
        </section>
      </aside>

      <main className="canvas">
        {error && (
          <div className="panel-error" role="alert">
            <p className="panel-error-title">Could not plan that trip.</p>
            <p>{error}</p>
          </div>
        )}

        {!activeTrip && (
          <div className="plan-layout">
            <div className="plan-form-col">
              <PlannerForm onSubmit={plan} submitting={busy} submitLabel="Plan my trip" />
            </div>
            <div className="plan-result-col">
              {result && (
                <>
                  <p className="plan-saved">planner generated · trip saved as #{result.trip?.id}</p>
                  <PlanResults result={result} pickup={result.trip?.pickup_location ?? "Pickup"} dropoff={result.trip?.dropoff_location ?? "Dropoff"} />
                </>
              )}
              {!result && !busy && (
                <div className="empty">
                  <p className="empty-copy">the route, gauges and logs land here once you plan.</p>
                </div>
              )}
              {!result && busy && <p className="plan-busy">planning…</p>}
            </div>
          </div>
        )}

        {activeTrip && (
          <PlanResults
            result={activeTrip}
            pickup={activeTrip.pickup_location}
            dropoff={activeTrip.dropoff_location}
          />
        )}
      </main>
    </div>
  );
}