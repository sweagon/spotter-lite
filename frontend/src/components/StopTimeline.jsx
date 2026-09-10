/**
 * transit-style stop timeline. every row is a dot in the status color joined
 * by a thin rail, like a metro map — and the dots use the exact same
 * stop_type -> color mapping as the map markers so the two features agree.
 */
const KIND = {
  pickup: { label: "Pickup", cls: "dot-mint" },
  dropoff: { label: "Dropoff", cls: "dot-mint" },
  fuel: { label: "Fuel stop", cls: "dot-ink" },
  break: { label: "30-min break", cls: "dot-teal" },
  rest: { label: "10-hr rest", cls: "dot-teal" },
  restart: { label: "34-hr restart", cls: "dot-coral" },
  on_duty: { label: "On duty", cls: "dot-teal" },
};

export default function StopTimeline({ stops }) {
  return (
    <section className="timeline-wrap">
      <h2 className="section-head">Stops</h2>
      <ol className="timeline">
        {stops.map((s, i) => {
          const kind = KIND[s.stop_type] ?? { label: s.kind, cls: "dot-teal" };
          const isLast = i === stops.length - 1;
          return (
            <li key={i} className="timeline-row">
              <span className="timeline-rail">
                <span className={`timeline-dot ${kind.cls}`} />
                {!isLast && <span className="timeline-line" />}
              </span>
              <div className="timeline-body">
                <div className="timeline-title">
                  <strong>{kind.label}</strong>
                  <span className="timeline-place">{s.label}</span>
                </div>
                <div className="timeline-meta num">
                  {s.day} · {s.time} · mi {s.mile} · {s.duration_min} min
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}