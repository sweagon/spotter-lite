import { useState } from "react";
import GeocodeField from "./GeocodeField";

export default function PlannerForm({
  onSubmit,
  submitting = false,
  assignable = false,
  drivers = [],
  vehicles = [],
  submitLabel = "Plan trip",
}) {
  const [form, setForm] = useState({
    current_location: "",
    pickup_location: "",
    dropoff_location: "",
    current_cycle_used: "",
    driver_id: "",
    vehicle_id: "",
  });

  const valid =
    form.current_location.trim() &&
    form.pickup_location.trim() &&
    form.dropoff_location.trim() &&
    form.current_cycle_used !== "";

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  function submit(e) {
    e.preventDefault();
    if (!valid) return;
    const payload = {
      current_location: form.current_location.trim(),
      pickup_location: form.pickup_location.trim(),
      dropoff_location: form.dropoff_location.trim(),
      current_cycle_used: Number(form.current_cycle_used),
    };
    if (assignable && form.driver_id) payload.driver_id = Number(form.driver_id);
    if (assignable && form.vehicle_id) payload.vehicle_id = Number(form.vehicle_id);
    onSubmit(payload);
  }

  return (
    <form className="trip-form" onSubmit={submit}>
      <h2 className="rail-title">Plan a trip</h2>
      <GeocodeField
        label="Current location"
        value={form.current_location}
        onChange={set("current_location")}
        placeholder="Dallas, TX"
      />
      <GeocodeField
        label="Pickup location"
        value={form.pickup_location}
        onChange={set("pickup_location")}
        placeholder="Memphis, TN"
      />
      <GeocodeField
        label="Dropoff location"
        value={form.dropoff_location}
        onChange={set("dropoff_location")}
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
            onChange={(e) => set("current_cycle_used")(e.target.value)}
            placeholder="30"
            required
          />
          <span className="cycle-unit">hrs</span>
        </span>
      </label>

      {assignable && (
        <>
          <label className="field">
            <span className="field-label">Assign driver</span>
            <select
              value={form.driver_id}
              onChange={(e) => set("driver_id")(e.target.value)}
              className="select"
            >
              <option value="">— unassigned —</option>
              {drivers.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.user.first_name} {d.user.last_name} ({d.user.username})
                  {d.vehicle_unit ? ` · ${d.vehicle_unit}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Vehicle</span>
            <select
              value={form.vehicle_id}
              onChange={(e) => set("vehicle_id")(e.target.value)}
              className="select"
            >
              <option value="">— unassigned —</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      <button
        type="submit"
        className="btn-plan"
        disabled={!valid || submitting}
      >
        {submitting ? "Planning…" : submitLabel}
      </button>
    </form>
  );
}