import { useEffect, useState } from "react";
import { apiJson } from "../api";
import PlannerForm from "../components/PlannerForm";
import PlanResults from "../components/PlanResults";

const STATUSES = ["draft", "assigned", "en_route", "stopped", "delivered", "cancelled"];

export default function DispatchBoard() {
  const [tab, setTab] = useState("trips");
  const [trips, setTrips] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [planning, setPlanning] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const initialFetch = async () => {
      const [t, d, v, a] = await Promise.all([
        apiJson("/api/trips/"),
        apiJson("/api/drivers/"),
        apiJson("/api/vehicles/"),
        apiJson("/api/alerts/"),
      ]);
      if (t.ok) setTrips(t.data);
      if (d.ok) setDrivers(d.data);
      if (v.ok) setVehicles(v.data);
      if (a.ok) setAlerts(a.data);
    };
    initialFetch();
  }, []);

  async function loadAll() {
    const [t, d, v, a] = await Promise.all([
      apiJson("/api/trips/"),
      apiJson("/api/drivers/"),
      apiJson("/api/vehicles/"),
      apiJson("/api/alerts/"),
    ]);
    if (t.ok) setTrips(t.data);
    if (d.ok) setDrivers(d.data);
    if (v.ok) setVehicles(v.data);
    if (a.ok) setAlerts(a.data);
  }

  async function plan(payload) {
    setBusy(true);
    setError(null);
    try {
      const { ok, data } = await apiJson("/api/trips/plan/", {
        method: "POST",
        body: payload,
      });
      if (ok) {
        setResult(data);
        loadAll();
      } else {
        setError(data?.error || "Could not plan that trip.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function advance(trip, next) {
    const { ok, data } = await apiJson(`/api/trips/${trip.id}/`, {
      method: "PATCH",
      body: { status: next },
    });
    if (ok) {
      setTrips((ts) => ts.map((t) => (t.id === data.id ? data : t)));
      setExpanded((e) => (e && e.id === data.id ? data : e));
    }
  }

  async function resolveAlert(id) {
    await apiJson(`/api/alerts/${id}/resolve/`, { method: "POST" });
    setAlerts((al) => al.filter((x) => x.id !== id));
  }

  async function resetCycle(id) {
    const { ok } = await apiJson(`/api/drivers/${id}/reset-cycle/`, { method: "POST", body: {} });
    if (ok) loadAll();
  }

  const nextStatus = {
    draft: ["assigned", "cancelled"],
    assigned: ["en_route", "cancelled"],
    en_route: ["stopped", "delivered"],
    stopped: ["en_route", "delivered"],
    delivered: [],
    cancelled: [],
  };

  const visible = statusFilter === "all"
    ? trips
    : trips.filter((t) => t.status === statusFilter);

  return (
    <div className="shell board-shell">
      <aside className="rail">
        <div className="rail-block">
          <button className="btn-plan btn-plan-wide" onClick={() => setPlanning((p) => !p)}>
            {planning ? "‹ close planner" : "+ plan new trip"}
          </button>
        </div>

        <section className="alerts-mini">
          <h3 className="rail-sub">watchdog</h3>
          {alerts.length === 0 && <p className="trip-empty">no open flags.</p>}
          {alerts.map((a) => (
            <div key={a.id} className="alert-row">
              <span className="alert-msg">
                <strong>{a.driver_name}</strong> · {a.rule.replace("_", " ")}
              </span>
              <button className="btn-mini" onClick={() => resolveAlert(a.id)}>
                clear
              </button>
            </div>
          ))}
        </section>

        <section>
          <h3 className="rail-sub">fleet</h3>
          <div className="fleet-mini">
            <p className="fleet-line"><span>drivers</span><span className="num">{drivers.length}</span></p>
            <p className="fleet-line"><span>vehicles</span><span className="num">{vehicles.length}</span></p>
          </div>
        </section>
      </aside>

      <main className="canvas board-canvas">
        {error && (
          <div className="panel-error" role="alert">
            <p className="panel-error-title">Could not plan that trip.</p>
            <p>{error}</p>
          </div>
        )}

        <div className="board-filters">
          <button className={`chip ${tab === "trips" ? "chip-on" : ""}`} onClick={() => setTab("trips")}>
            trips
          </button>
          <button className={`chip ${tab === "drivers" ? "chip-on" : ""}`} onClick={() => setTab("drivers")}>
            drivers <span className="num">{drivers.length}</span>
          </button>
          <button className={`chip ${tab === "vehicles" ? "chip-on" : ""}`} onClick={() => setTab("vehicles")}>
            vehicles <span className="num">{vehicles.length}</span>
          </button>
        </div>

        {tab === "drivers" && (
          <div className="board-list">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>driver</th><th>role</th><th>truck</th><th>cycle</th><th>hours today</th><th>status</th><th />
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => (
                  <tr key={d.id}>
                    <td className="num">{d.user.username}<br /><span className="muted">{d.user.first_name} {d.user.last_name}</span></td>
                    <td>{d.user.role.toLowerCase()}</td>
                    <td className="num">{d.vehicle_unit || "—"}</td>
                    <td className="num">{d.cycle_used.toFixed(1)}h</td>
                    <td className="num">{d.today_driving_hours.toFixed(1)}h</td>
                    <td>{d.active ? "active" : "off"}</td>
                    <td className="table-actions">
                      <button className="btn-mini" onClick={() => resetCycle(d.id)}>reset cycle</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "vehicles" && (
          <div className="board-list">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>unit</th><th>type</th><th>vin</th><th>odometer</th><th>assigned to</th><th>status</th>
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v) => (
                  <tr key={v.id}>
                    <td className="num">{v.unit_no}</td>
                    <td>{v.vehicle_type}</td>
                    <td className="num">{v.vin || "—"}</td>
                    <td className="num">{v.current_odometer ? v.current_odometer.toLocaleString() : "—"}</td>
                    <td className="num">{v.assigned_driver || "—"}</td>
                    <td>{v.active ? "active" : "off"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "trips" && planning && (
          <div className="plan-layout">
            <div className="plan-form-col">
              <PlannerForm
                onSubmit={plan}
                submitting={busy}
                assignable
                drivers={drivers}
                vehicles={vehicles}
                submitLabel="Plan + assign"
              />
            </div>
            <div className="plan-result-col">
              {result && (
                <>
                  <p className="plan-saved">trip #{result.trip?.id} saved · {result.trip?.status_label}</p>
                  <PlanResults
                    result={result}
                    pickup={result.trip?.pickup_location ?? "Pickup"}
                    dropoff={result.trip?.dropoff_location ?? "Dropoff"}
                  />
                </>
              )}
              {!result && <div className="empty"><p className="empty-copy">the planned trip, gauges and logs land here.</p></div>}
            </div>
          </div>
        )}

        {tab === "trips" && !planning && (
          <>
            <div className="board-filters">
              <button className={`chip ${statusFilter === "all" ? "chip-on" : ""}`} onClick={() => setStatusFilter("all")}>
                all <span className="num">{trips.length}</span>
              </button>
              {STATUSES.map((s) => (
                <button key={s} className={`chip ${statusFilter === s ? "chip-on" : ""}`} onClick={() => setStatusFilter(s)}>
                  {s} <span className="num">{trips.filter((t) => t.status === s).length}</span>
                </button>
              ))}
            </div>

            <div className="board-list">
              {visible.length === 0 && (
                <p className="trip-empty">nothing here — plan the next load.</p>
              )}
              {visible.map((t) => {
                const open = expanded?.id === t.id;
                return (
                  <article key={t.id} className={`board-card ${open ? "board-open" : ""}`}>
                    <div className="board-card-head" onClick={() => { setExpanded(open ? null : t); setResult(null); }}>
                      <span className={`badge badge-${t.status}`}>{t.status_label}</span>
                      <span className="board-card-route">
                        <strong>#{t.id}</strong> {t.pickup_location} → {t.dropoff_location}
                      </span>
                      <span className="board-card-meta num">
                        {t.driver ? `${t.driver.user.username}` : "unstaffed"} · {t.vehicle ? t.vehicle.unit_no : "no unit"} · {t.distance_miles} mi
                      </span>
                      <span className="board-expand">{open ? "▲" : "▼"}</span>
                    </div>

                    {open && (
                      <div className="board-card-body">
                        <div className="board-actions">
                          {(nextStatus[t.status] || []).map((n) => (
                            <button key={n} className="btn-mini" onClick={() => advance(t, n)}>
                              mark {n.replace("_", " ")}
                            </button>
                          ))}
                          {t.status === "draft" && !t.driver && (
                            <button className="btn-mini" onClick={() => setPlanning(true)}>
                              plan + assign
                            </button>
                          )}
                        </div>
                        {t.daily_logs?.length > 0 && (
                          <PlanResults result={t} pickup={t.pickup_location} dropoff={t.dropoff_location} />
                        )}
                        {!t.daily_logs?.length && (
                          <p className="trip-empty">draft — not planned yet.</p>
                        )}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </>
        )}
      </main>
    </div>
  );
}