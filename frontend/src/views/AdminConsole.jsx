import { useEffect, useState } from "react";
import { apiJson } from "../api";
import Board from "../components/Board";

const ROLES = ["driver", "dispatcher", "auditor"];
const VEHICLE_TYPES = ["sleeper", "daycab", "dryvan", "reefer", "flatbed"];

const emptyDriverForm = () => ({
  username: "", password: "", first_name: "", last_name: "",
  role: "driver", vehicle_id: "", cycle_used: 0, active: true,
});
const emptyVehicleForm = () => ({
  unit_no: "", vin: "", vehicle_type: "sleeper",
  current_odometer: "", active: true,
});

export default function AdminConsole() {
  const [tab, setTab] = useState("drivers");
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [dForm, setDForm] = useState(null);
  const [vForm, setVForm] = useState(null);
  const [flash, setFlash] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [d, v] = await Promise.all([
        apiJson("/api/drivers/"),
        apiJson("/api/vehicles/"),
      ]);
      if (d.ok) setDrivers(d.data);
      if (v.ok) setVehicles(v.data);
      if (!d.ok || !v.ok) setError("We couldn't load the fleet. Please retry.");
    } catch {
      setError("We couldn't reach the server to load the fleet. Please retry.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  function notify(msg) {
    setFlash(msg);
    setTimeout(() => setFlash(null), 3500);
  }

  async function submitDriver() {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        username: dForm.username.trim(),
        password: dForm.password,
        first_name: dForm.first_name.trim(),
        last_name: dForm.last_name.trim(),
        role: dForm.role,
        vehicle_id: dForm.vehicle_id ? Number(dForm.vehicle_id) : null,
        cycle_used: Number(dForm.cycle_used),
      };
      const { ok, data } = await apiJson(
        dForm.editing ? `/api/drivers/${dForm.id}/` : "/api/drivers/create/",
        { method: dForm.editing ? "PATCH" : "POST", body: payload }
      );
      if (ok) {
        setDForm(null);
        await load();
        notify(dForm.editing ? `Driver #${data.id} updated.` : `Driver ${data.user.username} added.`);
      } else {
        setError(data?.error || "We couldn't save the driver. Check the fields and try again.");
      }
    } catch {
      setError("We couldn't reach the server to save the driver. Please retry.");
    } finally {
      setBusy(false);
    }
  }

  async function submitVehicle() {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        unit_no: vForm.unit_no.trim(),
        vin: vForm.vin.trim(),
        vehicle_type: vForm.vehicle_type,
        current_odometer: vForm.current_odometer ? Number(vForm.current_odometer) : null,
      };
      if (vForm.editing) payload.active = vForm.active;
      const { ok, data } = await apiJson(
        vForm.editing ? `/api/vehicles/${vForm.id}/` : "/api/vehicles/",
        { method: vForm.editing ? "PATCH" : "POST", body: payload }
      );
      if (ok) {
        setVForm(null);
        await load();
        notify(vForm.editing ? `Vehicle ${data.unit_no} updated.` : `Vehicle ${data.unit_no} added.`);
      } else {
        setError(data?.error || "We couldn't save the vehicle. Check the fields and try again.");
      }
    } catch {
      setError("We couldn't reach the server to save the vehicle. Please retry.");
    } finally {
      setBusy(false);
    }
  }

  async function resetCycle(id, done) {
    setError(null);
    try {
      const { ok } = await apiJson(`/api/drivers/${id}/reset-cycle/`, { method: "POST", body: {} });
      if (ok) { await load(); notify(`Driver cycle reset to 00:00.`); }
    } catch {
      setError("We couldn't reach the server to reset the cycle. Please retry.");
    }
    if (done) done();
  }

  return (
    <Board
      className="board-shell"
        rail={
          <>
            <div className="rail-block">
              <h3 className="rail-sub">Admin console</h3>
              <button className={`rail-link ${tab === "drivers" ? "rail-active" : ""}`} onClick={() => setTab("drivers")}>
                Drivers
              </button>
              <button className={`rail-link ${tab === "vehicles" ? "rail-active" : ""}`} onClick={() => setTab("vehicles")}>
                Vehicles
              </button>
            </div>
            <div className="rail-block">
              <h3 className="rail-sub">Fleet</h3>
              <div className="fleet-mini">
                <p className="fleet-line"><span>Drivers</span><span className="num">{drivers.length}</span></p>
                <p className="fleet-line"><span>Vehicles</span><span className="num">{vehicles.length}</span></p>
              </div>
            </div>
          </>
        }
      >
        {flash && <div className="toast">{flash}</div>}
        {error && (
          <div className="panel-error" role="alert">
            <p className="panel-error-title">Something went wrong.</p>
            <p>{error}</p>
            <p><button className="btn-mini" onClick={load}>Retry</button></p>
          </div>
        )}

        {loading && !dForm && !vForm && (
          <div className="loading" aria-busy="true" role="status">
            <div className="sk-gauge" />
            <div className="sk-gauge" />
            <div className="sk-log" />
          </div>
        )}

        {dForm && (
          <section className="admin-form">
            <h2 className="admin-form-title">{dForm.editing ? `Edit driver #${dForm.id}` : "Add a driver"}</h2>
            <div className="admin-form-grid">
              <label className="field">Username
                <input className="input-mini" disabled={dForm.editing} value={dForm.username}
                  onChange={(e) => setDForm({ ...dForm, username: e.target.value })} />
              </label>
              <label className="field">Password
                <input className="input-mini" type="password" value={dForm.password}
                  onChange={(e) => setDForm({ ...dForm, password: e.target.value })} placeholder={dForm.editing ? "Leave blank to keep" : "Required"} />
              </label>
              <label className="field">First name
                <input className="input-mini" value={dForm.first_name}
                  onChange={(e) => setDForm({ ...dForm, first_name: e.target.value })} />
              </label>
              <label className="field">Last name
                <input className="input-mini" value={dForm.last_name}
                  onChange={(e) => setDForm({ ...dForm, last_name: e.target.value })} />
              </label>
              <label className="field">Role
                <select className="input-mini" value={dForm.role}
                  onChange={(e) => setDForm({ ...dForm, role: e.target.value })}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label className="field">Truck
                <select className="input-mini" value={String(dForm.vehicle_id || "")}
                  onChange={(e) => setDForm({ ...dForm, vehicle_id: e.target.value })}>
                  <option value="">— None —</option>
                  {vehicles.filter((v) => v.active || v.id === dForm.vehicle_id).map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.unit_no}{v.assigned_driver ? " (Assigned)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">Cycle used (h)
                <input className="input-mini" type="number" min="0" max="70" step="0.5" value={dForm.cycle_used}
                  onChange={(e) => setDForm({ ...dForm, cycle_used: e.target.value })} />
              </label>
              <label className="field">Active
                <select className="input-mini" value={dForm.active ? "1" : "0"}
                  onChange={(e) => setDForm({ ...dForm, active: e.target.value === "1" })}>
                  <option value="1">Yes</option>
                  <option value="0">No</option>
                </select>
              </label>
            </div>
            <div className="admin-form-actions">
              <button className="btn-mini" disabled={busy} onClick={submitDriver}>Save driver</button>
              <button className="btn-mini" onClick={() => setDForm(null)}>Cancel</button>
            </div>
          </section>
        )}

        {vForm && (
          <section className="admin-form">
            <h2 className="admin-form-title">{vForm.editing ? `Edit vehicle ${vForm.unit_no}` : "Add a vehicle"}</h2>
            <div className="admin-form-grid">
              <label className="field">Unit no
                <input className="input-mini" value={vForm.unit_no}
                  onChange={(e) => setVForm({ ...vForm, unit_no: e.target.value })} />
              </label>
              <label className="field">VIN
                <input className="input-mini" value={vForm.vin}
                  onChange={(e) => setVForm({ ...vForm, vin: e.target.value })} placeholder="Optional" />
              </label>
              <label className="field">Type
                <select className="input-mini" value={vForm.vehicle_type}
                  onChange={(e) => setVForm({ ...vForm, vehicle_type: e.target.value })}>
                  {VEHICLE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label className="field">Odometer
                <input className="input-mini" type="number" min="0" value={vForm.current_odometer}
                  onChange={(e) => setVForm({ ...vForm, current_odometer: e.target.value })} />
              </label>
              <label className="field">Active
                <select className="input-mini" value={vForm.active ? "1" : "0"}
                  onChange={(e) => setVForm({ ...vForm, active: e.target.value === "1" })}>
                  <option value="1">Yes</option>
                  <option value="0">No</option>
                </select>
              </label>
            </div>
            <div className="admin-form-actions">
              <button className="btn-mini" disabled={busy} onClick={submitVehicle}>Save vehicle</button>
              <button className="btn-mini" onClick={() => setVForm(null)}>Cancel</button>
            </div>
          </section>
        )}

        {!dForm && !vForm && tab === "drivers" && (
          <div className="board-list">
            <p className="board-subhead">Manage your roster: add drivers, edit details, and reset the 70-hour cycle.</p>
            <button className="btn-mini" onClick={() => setDForm({ ...emptyDriverForm() })}>+ Add driver</button>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Driver</th><th>Role</th><th>Truck</th><th>Cycle</th><th>Hours today</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {drivers.length === 0 && !loading && (
                  <tr><td className="trip-empty" colSpan={7}>No drivers yet. Add your first driver above.</td></tr>
                )}
                {drivers.map((d) => (
                  <tr key={d.id}>
                    <td className="num">{d.user.username}<br /><span className="muted">{d.user.first_name} {d.user.last_name}</span></td>
                    <td data-label="Role">{d.user.role.toLowerCase()}</td>
                    <td data-label="Truck" className="num">{d.vehicle_unit || "—"}</td>
                    <td data-label="Cycle" className="num">{d.cycle_used.toFixed(1)}h</td>
                    <td data-label="Hours today" className="num">{d.today_driving_hours.toFixed(1)}h</td>
                    <td data-label="Status">{d.active ? "Active" : "Off"}</td>
                    <td className="table-actions">
                      <button className="btn-mini" onClick={() => setDForm({
                        ...emptyDriverForm(),
                        editing: true, id: d.id,
                        username: d.user.username, password: "",
                        first_name: d.user.first_name || "", last_name: d.user.last_name || "",
                        role: d.user.role.toLowerCase(),
                        vehicle_id: d.vehicle_id ?? "",
                        cycle_used: d.cycle_used,
                        active: d.active,
                      })}>Edit</button>
                      <button className="btn-mini" onClick={() => resetCycle(d.id)}>Reset cycle</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!dForm && !vForm && tab === "vehicles" && (
          <div className="board-list">
            <p className="board-subhead">Keep the fleet straight: add vehicles and track odometer readings.</p>
            <button className="btn-mini" onClick={() => setVForm({ ...emptyVehicleForm() })}>+ Add vehicle</button>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Unit</th><th>Type</th><th>VIN</th><th>Odometer</th><th>Assigned to</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {vehicles.length === 0 && !loading && (
                  <tr><td className="trip-empty" colSpan={7}>No vehicles yet. Add your first vehicle above.</td></tr>
                )}
                {vehicles.map((v) => (
                  <tr key={v.id}>
                    <td className="num">{v.unit_no}</td>
                    <td data-label="Type">{v.vehicle_type}</td>
                    <td data-label="VIN" className="num">{v.vin || "—"}</td>
                    <td data-label="Odometer" className="num">{v.current_odometer ? v.current_odometer.toLocaleString() : "—"}</td>
                    <td data-label="Assigned to" className="num">{v.assigned_driver || "—"}</td>
                    <td data-label="Status">{v.active ? "Active" : "Off"}</td>
                    <td className="table-actions">
                      <button className="btn-mini" onClick={() => setVForm({
                        ...emptyVehicleForm(),
                        editing: true, id: v.id,
                        unit_no: v.unit_no, vin: v.vin || "",
                        vehicle_type: v.vehicle_type,
                        current_odometer: v.current_odometer ?? "",
                        active: v.active,
                      })}>Edit</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Board>
  );
}