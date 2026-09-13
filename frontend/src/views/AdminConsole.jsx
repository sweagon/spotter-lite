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
  const [busy, setBusy] = useState(false);

  async function load() {
    const [d, v] = await Promise.all([
      apiJson("/api/drivers/"),
      apiJson("/api/vehicles/"),
    ]);
    if (d.ok) setDrivers(d.data);
    if (v.ok) setVehicles(v.data);
  }
  useEffect(() => { load(); }, []);

  function notify(msg) {
    setFlash(msg);
    setTimeout(() => setFlash(null), 3500);
  }

  async function submitDriver() {
    setBusy(true);
    setError(null);
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
    setBusy(false);
    if (ok) {
      setDForm(null);
      await load();
      notify(dForm.editing ? `Driver #${data.id} updated.` : `Driver ${data.user.username} added.`);
    } else {
      setError(data?.error || "We couldn't save the driver. Check the fields and try again.");
    }
  }

  async function submitVehicle() {
    setBusy(true);
    setError(null);
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
    setBusy(false);
    if (ok) {
      setVForm(null);
      await load();
      notify(vForm.editing ? `Vehicle ${data.unit_no} updated.` : `Vehicle ${data.unit_no} added.`);
    } else {
      setError(data?.error || "We couldn't save the vehicle. Check the fields and try again.");
    }
  }

  async function resetCycle(id, done) {
    const { ok } = await apiJson(`/api/drivers/${id}/reset-cycle/`, { method: "POST", body: {} });
    if (ok) { await load(); notify(`Driver cycle reset to 00:00.`); }
    if (done) done();
  }

  return (
    <Board
      className="board-shell"
        rail={
          <>
            <div className="rail-block">
              <h3 className="rail-sub">admin console</h3>
              <button className={`rail-link ${tab === "drivers" ? "rail-active" : ""}`} onClick={() => setTab("drivers")}>
                drivers
              </button>
              <button className={`rail-link ${tab === "vehicles" ? "rail-active" : ""}`} onClick={() => setTab("vehicles")}>
                vehicles
              </button>
            </div>
            <div className="rail-block">
              <h3 className="rail-sub">fleet</h3>
              <div className="fleet-mini">
                <p className="fleet-line"><span>drivers</span><span className="num">{drivers.length}</span></p>
                <p className="fleet-line"><span>vehicles</span><span className="num">{vehicles.length}</span></p>
              </div>
            </div>
          </>
        }
      >
        {flash && <div className="toast">{flash}</div>}
        {error && (
          <div className="panel-error" role="alert">
            <p className="panel-error-title">We couldn't save your changes.</p>
            <p>{error}</p>
          </div>
        )}

        {dForm && (
          <section className="admin-form">
            <h2 className="admin-form-title">{dForm.editing ? `Edit driver #${dForm.id}` : "Add a driver"}</h2>
            <div className="admin-form-grid">
              <label className="field">username
                <input className="input-mini" disabled={dForm.editing} value={dForm.username}
                  onChange={(e) => setDForm({ ...dForm, username: e.target.value })} />
              </label>
              <label className="field">password
                <input className="input-mini" type="password" value={dForm.password}
                  onChange={(e) => setDForm({ ...dForm, password: e.target.value })} placeholder={dForm.editing ? "leave blank to keep" : "required"} />
              </label>
              <label className="field">first name
                <input className="input-mini" value={dForm.first_name}
                  onChange={(e) => setDForm({ ...dForm, first_name: e.target.value })} />
              </label>
              <label className="field">last name
                <input className="input-mini" value={dForm.last_name}
                  onChange={(e) => setDForm({ ...dForm, last_name: e.target.value })} />
              </label>
              <label className="field">role
                <select className="input-mini" value={dForm.role}
                  onChange={(e) => setDForm({ ...dForm, role: e.target.value })}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label className="field">truck
                <select className="input-mini" value={String(dForm.vehicle_id || "")}
                  onChange={(e) => setDForm({ ...dForm, vehicle_id: e.target.value })}>
                  <option value="">— none —</option>
                  {vehicles.filter((v) => v.active || v.id === dForm.vehicle_id).map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.unit_no}{v.assigned_driver ? " (assigned)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">cycle used (h)
                <input className="input-mini" type="number" min="0" max="70" step="0.5" value={dForm.cycle_used}
                  onChange={(e) => setDForm({ ...dForm, cycle_used: e.target.value })} />
              </label>
              <label className="field">active
                <select className="input-mini" value={dForm.active ? "1" : "0"}
                  onChange={(e) => setDForm({ ...dForm, active: e.target.value === "1" })}>
                  <option value="1">yes</option>
                  <option value="0">no</option>
                </select>
              </label>
            </div>
            <div className="admin-form-actions">
              <button className="btn-mini" disabled={busy} onClick={submitDriver}>save driver</button>
              <button className="btn-mini" onClick={() => setDForm(null)}>cancel</button>
            </div>
          </section>
        )}

        {vForm && (
          <section className="admin-form">
            <h2 className="admin-form-title">{vForm.editing ? `Edit vehicle ${vForm.unit_no}` : "Add a vehicle"}</h2>
            <div className="admin-form-grid">
              <label className="field">unit no
                <input className="input-mini" value={vForm.unit_no}
                  onChange={(e) => setVForm({ ...vForm, unit_no: e.target.value })} />
              </label>
              <label className="field">vin
                <input className="input-mini" value={vForm.vin}
                  onChange={(e) => setVForm({ ...vForm, vin: e.target.value })} placeholder="optional" />
              </label>
              <label className="field">type
                <select className="input-mini" value={vForm.vehicle_type}
                  onChange={(e) => setVForm({ ...vForm, vehicle_type: e.target.value })}>
                  {VEHICLE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label className="field">odometer
                <input className="input-mini" type="number" min="0" value={vForm.current_odometer}
                  onChange={(e) => setVForm({ ...vForm, current_odometer: e.target.value })} />
              </label>
              <label className="field">active
                <select className="input-mini" value={vForm.active ? "1" : "0"}
                  onChange={(e) => setVForm({ ...vForm, active: e.target.value === "1" })}>
                  <option value="1">yes</option>
                  <option value="0">no</option>
                </select>
              </label>
            </div>
            <div className="admin-form-actions">
              <button className="btn-mini" disabled={busy} onClick={submitVehicle}>save vehicle</button>
              <button className="btn-mini" onClick={() => setVForm(null)}>cancel</button>
            </div>
          </section>
        )}

        {!dForm && !vForm && tab === "drivers" && (
          <div className="board-list">
            <p className="board-subhead">Manage your roster: add drivers, edit details, and reset the 70-hour cycle.</p>
            <button className="btn-mini" onClick={() => setDForm({ ...emptyDriverForm() })}>+ add driver</button>
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
                    <td data-label="role">{d.user.role.toLowerCase()}</td>
                    <td data-label="truck" className="num">{d.vehicle_unit || "—"}</td>
                    <td data-label="cycle" className="num">{d.cycle_used.toFixed(1)}h</td>
                    <td data-label="hours today" className="num">{d.today_driving_hours.toFixed(1)}h</td>
                    <td data-label="status">{d.active ? "active" : "off"}</td>
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
                      })}>edit</button>
                      <button className="btn-mini" onClick={() => resetCycle(d.id)}>reset cycle</button>
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
            <button className="btn-mini" onClick={() => setVForm({ ...emptyVehicleForm() })}>+ add vehicle</button>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>unit</th><th>type</th><th>vin</th><th>odometer</th><th>assigned to</th><th>status</th><th />
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v) => (
                  <tr key={v.id}>
                    <td className="num">{v.unit_no}</td>
                    <td data-label="type">{v.vehicle_type}</td>
                    <td data-label="vin" className="num">{v.vin || "—"}</td>
                    <td data-label="odometer" className="num">{v.current_odometer ? v.current_odometer.toLocaleString() : "—"}</td>
                    <td data-label="assigned to" className="num">{v.assigned_driver || "—"}</td>
                    <td data-label="status">{v.active ? "active" : "off"}</td>
                    <td className="table-actions">
                      <button className="btn-mini" onClick={() => setVForm({
                        ...emptyVehicleForm(),
                        editing: true, id: v.id,
                        unit_no: v.unit_no, vin: v.vin || "",
                        vehicle_type: v.vehicle_type,
                        current_odometer: v.current_odometer ?? "",
                        active: v.active,
                      })}>edit</button>
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