import { useState } from "react";

/** the in-cab duty-status control: four FMCSA states, one tap to open a
 * short confirm sheet (note/location), confirm commits the change. the ELD
 * "signal rest / start / stop" that drives the live RODS sheet. */
const STATES = [
  { key: "off_duty", label: "Off duty", hint: "ended your shift" },
  { key: "sleeper_berth", label: "Sleeper", hint: "resting in the berth" },
  { key: "driving", label: "Driving", hint: "behind the wheel" },
  { key: "on_duty_not_driving", label: "On duty", hint: "working, not driving" },
];

export default function DutyControl({ current, onCommit, disabled }) {
  const [confirming, setConfirming] = useState(null);
  const [note, setNote] = useState("");
  const active = current?.status ?? null;

  function open(state) {
    if (state.key === active) return; // no-op re-taps
    setNote("");
    setConfirming(state);
  }

  async function confirm() {
    if (!confirming) return;
    await onCommit(confirming.key, note.trim());
    setConfirming(null);
  }

  return (
    <div className="duty-card">
      <div className="duty-head">
        <span className="rail-sub">duty status</span>
        {active ? (
          <span className={`duty-now duty-now--${active}`}>
            {current.location ? `${current.status_label} · ${current.location}` : current.status_label}
          </span>
        ) : (
          <span className="duty-now duty-now--idle">no status set today</span>
        )}
      </div>

      <div className="duty-statuses" role="group" aria-label="Set your duty status">
        {STATES.map((s) => (
          <button
            key={s.key}
            className={`duty-btn duty-btn--${s.key} ${active === s.key ? "duty-btn--active" : ""}`}
            onClick={() => open(s)}
            disabled={disabled || active === s.key}
            title={s.hint}
          >
            {s.label}
          </button>
        ))}
      </div>

      {confirming && (
        <div className="duty-confirm">
          <p className="duty-confirm-title">
            Start <strong>{confirming.label}</strong>?
          </p>
          <input
            className="duty-note"
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="optional remark — e.g. ramp 4, DFW"
            autoFocus
          />
          <div className="duty-confirm-actions">
            <button className="btn-mini" onClick={() => setConfirming(null)}>cancel</button>
            <button className="btn-mini btn-mini--solid" onClick={confirm}>confirm</button>
          </div>
        </div>
      )}
    </div>
  );
}