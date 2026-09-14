import { useEffect, useRef, useState } from "react";
import { apiJson } from "../api";
import PlannerForm from "../components/PlannerForm";
import PlanResults from "../components/PlanResults";
import DutyControl from "../components/DutyControl";
import LiveLogDay from "../components/LiveLogDay";
import Board from "../components/Board";
import { useAuth } from "../auth";

const SELF_PATCH = {
  assigned: ["en_route"],
  en_route: ["stopped", "delivered"],
  stopped: ["en_route", "delivered"],
  delivered: [],
  draft: [],
  cancelled: [],
};

const STATUS_LABEL = {
  off_duty: "Off duty",
  sleeper_berth: "Sleeper berth",
  driving: "Driving",
  on_duty_not_driving: "On duty (not driving)",
};

const humanize = (s) =>
  s
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");

/** the driver cab: plan a load, ride it through the status flow (start /
 * rest / stop / deliver) and signal duty changes that draw today's live
 * RODS sheet. */
export default function DriverHome() {
  const { user } = useAuth();
  const [me, setMe] = useState(null);
  const [trips, setTrips] = useState([]);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);
  const toastTimer = useRef(null);

  const duty = me?.duty ?? null;
  const profile = me?.driver ?? null;

  function flash(message) {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  }

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [m, t] = await Promise.all([apiJson("/api/me/"), apiJson("/api/trips/")]);
      if (m.ok) setMe(m.data);
      else throw new Error("me");
      if (t.ok) setTrips(t.data);
    } catch {
      setMe(null);
      setError("We couldn't reach the Spotter server. Please retry.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    return () => clearTimeout(toastTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function plan(payload) {
    setBusy(true);
    setError(null);
    setSelected(null);
    setResult(null);
    try {
      const { ok, data } = await apiJson("/api/trips/plan/", {
        method: "POST",
        body: { ...payload, driver_id: profile?.id, vehicle_id: profile?.vehicle_id ?? null },
      });
      if (ok) {
        setResult(data);
        await refresh();
        flash(`Trip #${data.trip?.id} planned and saved. Mark it Start when you roll — your log sheet updates automatically.`);
      } else {
        setError(data?.error || "We couldn't plan that trip. Check the pickup and drop-off, then try again.");
      }
    } catch {
      setError("We couldn't reach the server to plan the trip. Please retry.");
    } finally {
      setBusy(false);
    }
  }

  async function openTrip(tripId) {
    try {
      const { ok, data } = await apiJson(`/api/trips/${tripId}/`);
      if (ok) {
        setResult(null);
        setSelected(data);
      } else {
        setError(data?.error || "We couldn't open that trip. Try again.");
      }
    } catch {
      setError("We couldn't reach the server to open the trip. Please retry.");
    }
  }

  async function commitDuty(status, note) {
    try {
      const { ok, data } = await apiJson("/api/duty/events/", {
        method: "POST",
        body: { status, remark: note },
      });
      if (ok) {
        setMe((m) => ({ ...m, duty: data }));
        flash(`Duty status set to ${STATUS_LABEL[status] ?? status.replaceAll("_", " ")}.`);
        return true;
      }
      setError(data?.error || "We couldn't update your duty status. Try again.");
    } catch {
      setError("We couldn't reach the server to update your duty status. Please retry.");
    }
    return false;
  }

  async function tripAction(trip, next) {
    const dutyFor = {
      en_route: "driving",
      stopped: "off_duty",
      delivered: "off_duty",
    };
    if (!dutyFor[next]) return;
    setBusy(true);
    try {
      const { ok, data } = await apiJson(`/api/trips/${trip.id}/`, {
        method: "PATCH",
        body: { status: next },
      });
      if (ok) {
        setSelected(data);
        await commitDuty(dutyFor[next], "");
        await refresh();
        flash(`Trip marked ${(next.replaceAll("_", " "))}.`);
      } else {
        setError(data?.error || "We couldn't update the trip. Try again.");
      }
    } catch {
      setError("We couldn't reach the server to update the trip. Please retry.");
    } finally {
      setBusy(false);
    }
  }

  const todayDay = duty
    ? {
        day_number: 0,
        date: new Date().toISOString().slice(0, 10),
        segments: duty.segments,
        totals: duty.totals,
      }
    : null;

  return (
    <Board
      className="driver-shell"
      rail={
        <>
          <p className="rail-hello">
            {user.first_name || user.username}
            {selected ? " · Trip view" : ""}
          </p>
          {profile && (
            <section className="hos-card">
              <div className="hos-card-row">
                <span>Cycle used</span>
                <span className="num">
                  {profile.cycle_used}
                  <small> / 70</small>
                </span>
              </div>
              <div className="hos-card-row">
                <span>Vehicle</span>
                <span className="num">{profile.vehicle_unit || "—"}</span>
              </div>
              {duty?.today_driving_hours != null && (
                <div className="hos-card-row">
                  <span>Driving today</span>
                  <span className="num">{duty.today_driving_hours}h</span>
                </div>
              )}
              {me?.alerts?.length > 0 && (
                <div className="hos-alerts">
                  <p className="hos-alerts-title">Watchdog flags</p>
                  {me.alerts.map((a) => (
                    <p key={a.id} className="hos-alert">
                      {humanize(a.rule)} · {a.detail || "Check hours"}
                    </p>
                  ))}
                </div>
              )}
            </section>
          )}

          <div className="rail-block">
            <button
              className={`rail-link ${!selected && !result && !planning ? "rail-active" : ""}`}
              onClick={() => { setSelected(null); setResult(null); setPlanning(false); }}
            >
              ← Duty &amp; Today's Log
            </button>
            <button
              className={`rail-link ${planning ? "rail-active" : ""}`}
              onClick={() => { setSelected(null); setResult(null); setPlanning(true); }}
            >
              + Plan a Trip
            </button>
            <button
              className="rail-link"
              onClick={async () => {
                const { ok, data } = await apiJson("/api/duty/");
                if (ok) setMe((m) => ({ ...m, duty: data }));
              }}
            >
              ↻ Refresh Today
            </button>
          </div>

          <section>
            <h3 className="rail-sub">My Trips</h3>
            <div className="trip-list">
              {trips.length === 0 && (
                <p className="trip-empty">No trips yet. Use the trip planner to create your first load.</p>
              )}
              {trips.slice(0, 15).map((t) => (
                <button
                  key={t.id}
                  className={`trip-row ${selected?.id === t.id ? "trip-active" : ""}`}
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
        </>
      }
    >
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
      {error && (
        <div className="panel-error" role="alert">
          <p className="panel-error-title">Something went wrong.</p>
          <p>{error}</p>
          <p><button className="btn-mini" onClick={refresh}>Retry</button></p>
        </div>
      )}

      {loading && !me && !error && (
        <div className="loading" aria-busy="true" role="status">
          <div className="sk-gauge" />
          <div className="sk-gauge" />
          <div className="sk-log" />
        </div>
      )}

      {!selected && !result && (
        <div className="cab-grid">
          <DutyControl
            current={duty?.current}
            onCommit={commitDuty}
            disabled={busy}
          />

          <div className="live-log-wrap">
            {todayDay && (
              <LiveLogDay
                day={todayDay}
                cycleUsed={profile?.cycle_used}
                drivingHours={duty.today_driving_hours}
                vehicleUnit={profile?.vehicle_unit}
              />
            )}
            {!todayDay && (
              <div className="empty">
                <p className="empty-copy">Set your first duty status and today's log sheet will draw here.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {!selected && result && !planning && (
        <div className="results">
          <p className="plan-saved">
            Trip planned · saved as #{result.trip?.id} ·{" "}
            <button className="btn-mini" onClick={async () => { await openTrip(result.trip.id); }}>
              Open to start it
            </button>
          </p>
          <PlanResults
            result={result}
            pickup={result.trip?.pickup_location ?? "Pickup"}
            dropoff={result.trip?.dropoff_location ?? "Dropoff"}
          />
        </div>
      )}

      {!selected && planning && (
        <div className="plan-layout">
          <div className="plan-form-col">
            <PlannerForm onSubmit={plan} submitting={busy} submitLabel="Plan my trip" />
          </div>
          <div className="plan-result-col">
            {result && (
              <>
                <p className="plan-saved">Trip planned · saved as #{result.trip?.id}</p>
                <PlanResults
                  result={result}
                  pickup={result.trip?.pickup_location ?? "Pickup"}
                  dropoff={result.trip?.dropoff_location ?? "Dropoff"}
                />
              </>
            )}
            {!result && (
              <div className="empty"><p className="empty-copy">Your route, hours gauges and log sheet will appear here once you plan a trip.</p></div>
            )}
          </div>
        </div>
      )}

      {selected && (
        <>
          <div className="trip-actions">
            <span className="trip-actions-label">
              #{selected.id} · {selected.pickup_location} → {selected.dropoff_location}
            </span>
            {(SELF_PATCH[selected.status] || []).map((n) => (
              <button key={n} className="btn-mini" onClick={() => tripAction(selected, n)}>
                {n === "en_route" ? "Start / Continue" : n === "stopped" ? "Stop" : "Deliver"}
              </button>
            ))}
            {selected.status === "en_route" && (
              <button className="btn-mini" onClick={() => commitDuty("sleeper_berth", "")}>
                Rest
              </button>
            )}
          </div>
          <PlanResults
            result={selected}
            pickup={selected.pickup_location}
            dropoff={selected.dropoff_location}
          />
        </>
      )}
    </Board>
  );
}