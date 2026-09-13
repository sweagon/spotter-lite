import { useEffect, useState } from "react";
import { api, apiJson } from "../api";
import PlanResults from "../components/PlanResults";

/** the auditor's read-only compliance view: fleet posture, open HOS
 * watchdog flags, live trip board and a one-click compliance packet
 * (every drawn log sheet as a single PDF). no mutations anywhere. */
const humanize = (s) =>
  s
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");

export default function SafetyView() {
  const [drivers, setDrivers] = useState([]);
  const [trips, setTrips] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);

  async function loadAll() {
    const [d, t, a, v] = await Promise.all([
      apiJson("/api/drivers/"),
      apiJson("/api/trips/"),
      apiJson("/api/alerts/"),
      apiJson("/api/vehicles/"),
    ]);
    if (d.ok) setDrivers(d.data);
    if (t.ok) setTrips(t.data);
    if (a.ok) setAlerts(a.data);
    if (v.ok) setVehicles(v.data);
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function exportPdf() {
    setExporting(true);
    setExportError(null);
    try {
      const resp = await api("/api/export/logs.pdf");
      if (!resp.ok) {
        setExportError("No log sheets to export yet. Plan and save a trip first.");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "spotter_hos_packet.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  const openAlerts = alerts.filter((a) => !a.cleared);
  const liveTrips = trips.filter((t) => ["assigned", "en_route", "stopped"].includes(t.status));

  return (
    <div className="safety-view">
      <div className="safety-head">
        <div>
          <h1 className="page-title">Safety &amp; compliance</h1>
          <p className="page-sub">Read-only fleet posture — HOS watchdog, live loads, and the daily-log packet.</p>
        </div>
        <button className="btn-export" onClick={exportPdf} disabled={exporting}>
          {exporting ? "Processing…" : "⤓ Download compliance packet (PDF)"}
        </button>
      </div>

      {exportError && (
        <div className="panel-error" role="alert">
          <p>{exportError}</p>
        </div>
      )}

      <div className="kpi-strip">
        <div className="kpi-card">
          <span className="num kpi-num">{openAlerts.length}</span>
          <span className="kpi-label">Open HOS flags</span>
        </div>
        <div className="kpi-card">
          <span className="num kpi-num">{liveTrips.length}</span>
          <span className="kpi-label">Live loads</span>
        </div>
        <div className="kpi-card">
          <span className="num kpi-num">{drivers.length}</span>
          <span className="kpi-label">Active drivers</span>
        </div>
        <div className="kpi-card">
          <span className="num kpi-num">{vehicles.length}</span>
          <span className="kpi-label">Active vehicles</span>
        </div>
      </div>

      <section className="safety-section">
        <h2 className="rail-sub">Watchdog flags</h2>
        {openAlerts.length === 0 && <p className="trip-empty">No open HOS flags. Every driver is inside the planning guardrails.</p>}
        {openAlerts.map((a) => (
          <div key={a.id} className="alert-row">
            <span className="alert-msg">
              <strong>{a.driver_name}</strong> · {humanize(a.rule)}
            </span>
            <span className="alert-detail">{a.detail}</span>
          </div>
        ))}
      </section>

      <section className="safety-section">
        <h2 className="rail-sub">Fleet posture</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Driver</th>
              <th>Truck</th>
              <th className="num">Cycle used</th>
              <th className="num">/ 70</th>
            </tr>
          </thead>
          <tbody>
            {drivers.length === 0 && (
              <tr><td className="trip-empty" colSpan={4}>No active drivers yet.</td></tr>
            )}
            {drivers.map((d) => (
              <tr key={d.id}>
                <td>{d.user.first_name} {d.user.last_name} <span className="muted">@{d.user.username}</span></td>
                <td data-label="Truck">{d.vehicle_unit || "—"}</td>
                <td data-label="Cycle used" className="num">{d.cycle_used}</td>
                <td data-label="/ 70" className="num">
                  <span className={`cycle-fill ${d.cycle_used >= 65 ? "cycle-hot" : ""}`}>
                    {d.cycle_used >= 65 ? "High" : d.cycle_used >= 45 ? "Watch" : "Ok"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="safety-section">
        <h2 className="rail-sub">Live loads &amp; logs</h2>
        {trips.length === 0 && <p className="trip-empty">No trips saved yet.</p>}
        {trips.slice(0, 30).map((t) => {
          const open = expanded?.id === t.id;
          return (
            <article key={t.id} className={`board-card ${open ? "board-open" : ""}`}>
              <button className="board-card-head safety-head-btn" onClick={() => setExpanded(open ? null : t)}>
                <span className={`badge badge-${t.status}`}>{t.status_label}</span>
                <span className="board-card-route">
                  <strong>#{t.id}</strong> {t.pickup_location} → {t.dropoff_location}
                </span>
                <span className="board-card-meta num">
                  {t.driver ? t.driver.user.username : "Unstaffed"} · {t.distance_miles} mi · {t.created_by_username}
                </span>
                <span className="board-expand">{open ? "▲" : "▼"}</span>
              </button>
              {open && (
                <div className="board-card-body">
                  {t.daily_logs?.length > 0 ? (
                    <PlanResults result={t} pickup={t.pickup_location} dropoff={t.dropoff_location} />
                  ) : (
                    <p className="trip-empty">Draft — not planned yet.</p>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}