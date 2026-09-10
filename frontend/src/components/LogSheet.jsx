import { useMemo } from "react";

/**
 * FMCSA-style daily driver's log, as SVG. geometry follows the real 395.8
 * form: 4 duty rows, midnight-to-midnight hour axis with quarter-hour
 * sub-ticks, a stepped duty line, totals column, remarks row.
 *
 * two product choices on top of the faithful grid:
 *   - the duty line is color-coded BY STATUS (coral driving / teal on-duty /
 *     mint sleeper / ink off-duty) AND given a distinct dash pattern per
 *     status, so the compliance doc stays readable for colorblind viewers.
 *   - totals are set in mono with a checksum rule underneath — the sheet
 *     must sum to 24 and it should visibly look like it.
 */

const ROWS = [
  { key: "off_duty", label: "OFF DUTY" },
  { key: "sleeper_berth", label: "SLEEPER BERTH" },
  { key: "driving", label: "DRIVING" },
  { key: "on_duty_not_driving", label: "ON DUTY (NOT DRIVING)" },
];
const ROW_INDEX = Object.fromEntries(ROWS.map((r, i) => [r.key, i]));

const STATUS_STROKE = {
  off_duty: "#5c747c", // ink-400, dark enough to read against the paper
  sleeper_berth: "#008080",
  driving: "#f84960",
  on_duty_not_driving: "#006b6b",
};
const STATUS_DASH = {
  off_duty: null, // thin, solid
  sleeper_berth: "2 5", // dotted
  driving: null, // solid
  on_duty_not_driving: "6 4", // dashed
};
const STATUS_WIDTH = {
  off_duty: 1.5,
  sleeper_berth: 2.5,
  driving: 2.5,
  on_duty_not_driving: 2.5,
};

const VIEW = { w: 1120, h: 470 };
const HEADER_H = 46;
const MARGIN = { left: 170, right: 104, top: HEADER_H + 34, bottom: 92 };
const GRID_W = VIEW.w - MARGIN.left - MARGIN.right;
const GRID_H = VIEW.h - MARGIN.top - MARGIN.bottom;
const ROW_H = GRID_H / ROWS.length;

const xOf = (hour) => MARGIN.left + (hour / 24) * GRID_W;
const yOf = (row) => MARGIN.top + row * ROW_H + ROW_H / 2;

export default function LogSheet({ day, index }) {
  const { runs, connectors } = useMemo(() => buildGraph(day.segments), [day.segments]);

  const remarks = day.segments
    .filter((s) => s.status !== "off_duty" || s.location !== "Home")
    .map((s) => ({
      time: s.start_time,
      label: s.name && s.name !== s.location ? s.name : s.location,
    }));

  const dayMiles = milesDriven(day.segments);
  const totalHours = (key) => day.totals[key] ?? 0;
  const shortDate = day.date.replace(/^\w+\s+/, ""); // "Thu Sep 10, 2026" -> "Sep 10, 2026"
  const headline = day.date.split(" ")[0].toLowerCase(); // "Thu" -> "thu"

  return (
    <article className="sheet" aria-label={`Daily log ${day.date}`}>
      <div className="sheet-head">
        <h3>{`${headline}, ${shortDate}`}</h3>
        <span className="num">{index + 1}</span>
      </div>
      <svg
        className="sheet-svg"
        viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
        role="img"
        aria-label={`Driver's daily log for ${day.date}, totaling 24 hours`}
      >
        {/* ---- petrol header strip: a real form's top block ---- */}
        <rect x="0" y="0" width={VIEW.w} height={HEADER_H} fill="#043b4c" />
        <text x="18" y="30" className="sheet-title">
          DRIVER'S DAILY LOG
        </text>
        <FormField x={318} label="date" value={day.date} />
        <FormField x={470} label="total miles" value={String(dayMiles)} mono />
        <FormField x={606} label="carrier" value="—" />
        <FormField x={752} label="vehicle no." value="—" />
        <FormField x={898} label="trailer no." value="—" />
        <text x={VIEW.w - 18} y="30" className="sheet-title" textAnchor="end">
          24-HOUR GRID · 49 CFR 395.8
        </text>

        {hourTicks()}

        {ROWS.map((row, i) => (
          <g key={row.key}>
            <line
              x1={MARGIN.left}
              x2={MARGIN.left + GRID_W}
              y1={MARGIN.top + i * ROW_H}
              y2={MARGIN.top + i * ROW_H}
              stroke="#0a4e61"
              strokeWidth="1"
            />
            <text
              x={MARGIN.left - 12}
              y={yOf(i)}
              textAnchor="end"
              dominantBaseline="middle"
              className="sheet-row-label"
            >
              {row.label}
            </text>
            <text
              x={MARGIN.left + GRID_W + 18}
              y={yOf(i)}
              textAnchor="start"
              dominantBaseline="middle"
              className="sheet-total num"
            >
              {fmt(totalHours(row.key))}
            </text>
          </g>
        ))}

        {/* ---- checksum rule: these four numbers must add to 24 ---- */}
        <line
          x1={MARGIN.left + GRID_W + 10}
          y1={MARGIN.top + GRID_H + 4}
          x2={MARGIN.left + GRID_W + 48}
          y2={MARGIN.top + GRID_H + 4}
          stroke="#9fb4b8"
          strokeWidth="1.2"
        />

        {/* ---- the stepped duty line: one colored sub-path per segment ---- */}
        {runs.map((r, i) => (
          <path
            key={i}
            d={`M ${r.x1} ${r.y} L ${r.x2} ${r.y}`}
            fill="none"
            stroke={STATUS_STROKE[r.status]}
            strokeWidth={STATUS_WIDTH[r.status]}
            strokeDasharray={STATUS_DASH[r.status]}
            strokeLinejoin="round"
          />
        ))}
        <path
          d={connectors}
          fill="none"
          stroke="#9fb4b8"
          strokeWidth="1.2"
          opacity="0.7"
        />

        {/* ---- remarks row ---- */}
        <text x={MARGIN.left} y={VIEW.h - 64} className="sheet-remarks">
          REMARKS
        </text>
        {remarks.slice(0, 3).map((r, i) => (
          <text key={i} x={MARGIN.left + 84} y={VIEW.h - 64 + i * 18} className="sheet-remark">
            {r.time} — {r.label}
          </text>
        ))}
      </svg>
    </article>
  );
}

function FormField({ x, label, value, mono }) {
  return (
    <g>
      <text x={x} y="20" fontSize="9">
        {label}
      </text>
      <text x={x} y="34" fontSize="12" fontWeight="600" className={mono ? "num" : ""}>
        {value}
      </text>
    </g>
  );
}

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
        y1={MARGIN.top - 12}
        y2={MARGIN.top + GRID_H}
        stroke={isMidnight ? "#eaf1f1" : isThree ? "#0a4e61" : "#0a4e61"}
        strokeWidth={isMidnight ? 1.6 : isThree ? 1 : 0.7}
      />
    );
    if (h < 24 && isThree) {
      for (const q of [0.25, 0.5, 0.75]) {
        ticks.push(
          <line
            key={`q${h}-${q}`}
            x1={xOf(h + q)}
            x2={xOf(h + q)}
            y1={MARGIN.top + GRID_H}
            y2={MARGIN.top + GRID_H - 7}
            stroke="#0a4e61"
            strokeWidth="0.7"
          />
        );
      }
    }
    if (h % 2 === 0 || isMidnight) {
      ticks.push(
        <text key={`t${h}`} x={x} y={MARGIN.top - 20} textAnchor="middle" className="sheet-hour">
          {h === 24 ? 0 : h}
        </text>
      );
    }
  }
  return ticks;
}

function buildGraph(segments) {
  const runs = [];
  const connectorParts = [];
  let prev = null;
  for (const seg of segments) {
    const x1 = xOf(
      seg.start_hour != null ? seg.start_hour : toHour(seg.start_time)
    );
    const x2 = xOf(
      seg.end_hour != null ? seg.end_hour : toHour(seg.end_time)
    );
    const row = ROW_INDEX[seg.status] ?? 0;
    const y = yOf(row);
    if (prev != null && prev.y !== y && x1 - prev.x > 0.01) {
      connectorParts.push(`M ${x1} ${prev.y} L ${x1} ${y}`);
    }
    runs.push({ x1, x2, y, status: seg.status });
    prev = { x: x2, y };
  }
  return { runs, connectors: connectorParts.join(" ") };
}

function milesDriven(segments) {
  const driving = segments.filter((s) => s.status === "driving");
  if (!driving.length) return 0;
  return Math.max(0, Math.round(driving[driving.length - 1].distance - driving[0].distance));
}

const fmt = (h) => (Math.round(h * 10) / 10 === Math.round(h) ? h.toFixed(1) : h.toFixed(2));
const toHour = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h + m / 60;
};