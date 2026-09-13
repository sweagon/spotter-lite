/**
 * hours instrument cluster — three compact gauges (driving / window / cycle).
 * the bar's color is functional, not decorative: teal under 70% of the limit,
 * coral 70-90%, alert red above 90%. a dispatcher can tell at a glance
 * whether the trip is tight without reading the numbers.
 */
const LIMITS = {
  driving: { limit: 11, label: "Driving" },
  window: { limit: 14, label: "On-duty window" },
  cycle: { limit: 70, label: "70-hour cycle" },
};

function barColor(used, limit) {
  const pct = used / limit;
  // lighter derived shades on the dark petrol cards — the 500 brand values
  // drop below the 3:1 non-text contrast floor against petrol-800.
  if (pct > 0.9) return "var(--alert-400)";
  if (pct >= 0.7) return "var(--coral-400)";
  return "var(--teal-400)";
}

export default function HoursCluster({ usage }) {
  if (!usage) return null;

  return (
    <section className="cluster" aria-label="Hours used this trip">
      {Object.entries(LIMITS).map(([key, cfg]) => {
        const used = usage[`${key}_hours`] ?? 0;
        const limit = cfg.limit;
        const pct = Math.min(100, (used / limit) * 100);
        return (
          <div
            key={key}
            className="gauge"
            role="progressbar"
            aria-valuenow={Math.round(used * 10) / 10}
            aria-valuemin={0}
            aria-valuemax={limit}
            aria-label={`${cfg.label}: ${used.toFixed(1)} of ${limit} hours`}
          >
            <div className="gauge-head">
              <span className="gauge-label">{cfg.label}</span>
              <span className="gauge-value num">
                {used.toFixed(1)}
                <span className="gauge-limit">/{limit}</span>
              </span>
            </div>
            <div className="gauge-track">
              <div
                className="gauge-fill"
                style={{ width: `${pct}%`, background: barColor(used, limit) }}
              />
            </div>
          </div>
        );
      })}
    </section>
  );
}