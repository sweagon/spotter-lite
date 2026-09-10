import { useMemo } from "react";

/**
 * FMCSA-style driver's daily log, drawn as SVG (no screenshots / no pdf).
 *
 * layout mirrors the real 395.8 form:
 *   - 4 horizontal duty rows: off duty / sleeper berth / driving / on-duty(not driving)
 *   - 0-24 hour axis with hour lines + quarter-hour sub-ticks
 *   - a stepped line (the "graph") moving between rows as duty status changes
 *   - a totals column on the right that adds up to 24
 *   - a remarks row underneath listing each status change + location
 */

const ROWS = [
  { key: "off_duty", label: "OFF DUTY" },
  { key: "sleeper_berth", label: "SLEEPER BERTH" },
  { key: "driving", label: "DRIVING" },
  { key: "on_duty_not_driving", label: "ON DUTY (NOT DRIVING)" },
];
const ROW_INDEX = Object.fromEntries(ROWS.map((r, i) => [r.key, i]));

const VIEW = { w: 1120, h: 430 };
const MARGIN = { left: 170, right: 90, top: 52, bottom: 96 };
const GRID_W = VIEW.w - MARGIN.left - MARGIN.right;
const GRID_H = VIEW.h - MARGIN.top - MARGIN.bottom;
const ROW_H = GRID_H / ROWS.length;
const LINE_COLOR = "#1d4ed8";

const xOf = (hour) => MARGIN.left + (hour / 24) * GRID_W;
const yOf = (row) => MARGIN.top + row * ROW_H + ROW_H / 2;
const toHour = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h + m / 60;
};

export default function LogSheet({ day, index }) {
  const { pathD, points } = useMemo(() => buildGraph(day.segments), [day.segments]);

  const remarks = day.segments
    .filter((s) => s.status !== "off_duty" || s.location !== "Home")
    .map((s) => ({
      time: s.start_time,
      label:
        s.name && s.name !== s.location
          ? `${s.name}`
          : `${s.location}`,
      status: s.status,
    }));

  const totalHours = (key) => day.totals[key] ?? 0;

  return (
    <div className="log-card">
      <div className="log-sidebar">
        <div className="log-day">{day.date}</div>
        <div className="log-title">DRIVER'S DAILY LOG</div>
        <div className="log-form-noise">
          24-HOURLY GRID — 49 CFR 395.8 · Sheet {index + 1}
        </div>
      </div>
      <svg className="log-svg" viewBox={`0 0 ${VIEW.w} ${VIEW.h}`} aria-label={`Daily log for ${day.date}`}>
        {/* ---------- hour axis ---------- */}
        {hourTicks()}
        {/* ---------- duty rows ---------- */}
        {ROWS.map((row, i) => (
          <g key={row.key}>
            <line
              x1={MARGIN.left}
              x2={MARGIN.left + GRID_W}
              y1={MARGIN.top + i * ROW_H}
              y2={MARGIN.top + i * ROW_H}
              stroke="#9ca3af"
              strokeWidth="1.2"
            />
            <text
              x={MARGIN.left - 12}
              y={yOf(i)}
              textAnchor="end"
              dominantBaseline="middle"
              className="log-row-label"
            >
              {row.label}
            </text>
            <text
              x={MARGIN.left + GRID_W + 16}
              y={yOf(i)}
              textAnchor="start"
              dominantBaseline="middle"
              className="log-total"
            >
              {fmt(totalHours(row.key))}
            </text>
          </g>
        ))}
        {/* ---------- the duty graph line ---------- */}
        <path d={pathD} fill="none" stroke={LINE_COLOR} strokeWidth="2.5" strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="3" fill={LINE_COLOR} />
        ))}
        {/* ---------- remarks ---------- */}
        <text x={MARGIN.left} y={VIEW.h - 68} className="log-remarks-label">
          REMARKS
        </text>
        {remarks.slice(0, 3).map((r, i) => (
          <text
            key={i}
            x={MARGIN.left + 80}
            y={VIEW.h - 68 + i * 16}
            className="log-remarks-line"
          >
            {r.time} — {statusShort(r.status)} — {r.label}
          </text>
        ))}
        <line x1={MARGIN.left} y1={VIEW.h - 12} x2={VIEW.w - MARGIN.right} y2={VIEW.h - 12} stroke="#9ca3af" />
        <line x1={MARGIN.left} y1={VIEW.h - 34} x2={VIEW.w - MARGIN.right} y2={VIEW.h - 34} stroke="#cbd5e1" />
        <line x1={MARGIN.left} y1={VIEW.h - 56} x2={VIEW.w - MARGIN.right} y2={VIEW.h - 56} stroke="#e2e8f0" />
      </svg>
    </div>
  );

  function hourTicks() {
    const ticks = [];
    for (let h = 0; h <= 24; h++) {
      const x = xOf(h);
      const isMidnight = h === 0 || h === 24;
      const isThree = h % 3 === 0 && !isMidnight;
      ticks.push(
        <line
          key={`h${h}`}
          x1={x}
          x2={x}
          y1={MARGIN.top - 14}
          y2={MARGIN.top + GRID_H}
          stroke={isMidnight ? "#374151" : isThree ? "#94a3b8" : "#d1d5db"}
          strokeWidth={isMidnight ? 1.6 : 0.9}
          strokeDasharray={isMidnight ? null : isThree ? "3 3" : "2 4"}
        />
      );
      if (h < 24) {
        // quarter hour sub-ticks within the hour — thin, partial depth
        for (const q of [0.25, 0.5, 0.75]) {
          ticks.push(
            <line
              key={`q${h}-${q}`}
              x1={xOf(h + q)}
              x2={xOf(h + q)}
              y1={MARGIN.top + GRID_H}
              y2={MARGIN.top + GRID_H - 8}
              stroke="#cbd5e1"
              strokeWidth="0.8"
            />
          );
        }
      }
      // number labels every 2 hours + endpoints
      if (h % 2 === 0 || isMidnight) {
        ticks.push(
          <text
            key={`t${h}`}
            x={x}
            y={MARGIN.top - 24}
            textAnchor="middle"
            className="log-hour-label"
          >
            {h === 24 ? 0 : h}
          </text>
        );
      }
    }
    return ticks;
  }

  function buildGraph(segments) {
    let d = "";
    let prev = null;
    const pts = [];
    for (const seg of segments) {
      const x1 = xOf(
        seg.start_hour != null ? seg.start_hour : toHour(seg.start_time)
      );
      const x2 = xOf(
        seg.end_hour != null ? seg.end_hour : toHour(seg.end_time)
      );
      const row = ROW_INDEX[seg.status] ?? 0;
      const y = yOf(row);
      if (prev === null) {
        d += `M ${x1} ${y}`;
      } else {
        // vertical connector from previous row to this row at the change time
        d += ` L ${x1} ${prev.y}`;
        d += ` L ${x1} ${y}`;
      }
      d += ` L ${x2} ${y}`;
      pts.push({ x: x1, y });
      prev = { x: x2, y };
    }
    pts.push({ x: prev?.x ?? xOf(24), y: prev?.y ?? yOf(0) });
    return { pathD: d, points: pts };
  }
}

const fmt = (h) => h.toFixed(String(h).length > 4 ? 2 : 1) + "hr";

const statusShort = (s) =>
  ({
    off_duty: "Off duty",
    sleeper_berth: "Sleeper berth",
    driving: "Driving",
    on_duty_not_driving: "On duty (not driving)",
  }[s] ?? s);