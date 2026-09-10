import { useMemo } from "react";
import {
  STATUS_ROWS,
  MARGIN,
  VIEW,
  GRID_W,
  ROW_H,
  xOf,
  centerY,
  rowTop,
  gridBottom,
  HOUR_MARKS,
  quarterTicks,
  normalizeSegments,
  buildDutyLine,
  buildRemarks,
  sumTotals,
  isAligned,
  recap,
} from "./logSheetSpec";

/**
 * FMCSA-style daily driver's log, as SVG. geometry faithful to the 395.8
 * form per the reference spec (see scripts/logsheet.spec.test.js which
 * asserts the same rules):
 *   - 4 fixed rows over a 0-1440 minute axis
 *   - 25 full-height hour lines, labeled midnight..noon..midnight
 *   - 3 quarter ticks per hour per row; rows 1-2 hang down, rows 3-4 rise
 *     up, the :30 mark longer than :15/:45
 *   - a single stepped duty line, connectors colored toward the new status
 *   - a remarks lane ticked + labeled at every change x-position
 *   - totals column with ruled cells and a programmatic 24.00 checksum
 *
 * product choices on top of the faithful grid: per-status colors + dash
 * patterns for colorblind readability, and a compact shipping/recap strip.
 */

const STATUS_STROKE = {
  off_duty: "#5c747c", // ink-400
  sleeper_berth: "#008080",
  driving: "#f84960",
  on_duty_not_driving: "#006b6b",
};
const STATUS_DASH = {
  off_duty: null,
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

const TOTALS_X = MARGIN.left + GRID_W + 12;
const TOTALS_W = 62;
const REMARK_DROP = 11;

export default function LogSheet({ day, index, cycleUsed }) {
  const segs = useMemo(() => normalizeSegments(day.segments), [day.segments]);
  const { runs, transitions } = useMemo(() => buildDutyLine(segs), [segs]);
  const remarks = useMemo(
    () =>
      buildRemarks(segs)
        .map((r) => ({ x: r.x, label: clipLabel(r.label) }))
        .filter((r) => r.label != null)
        .filter((r, i, all) => i === 0 || all[i - 1].x !== r.x || all[i - 1].label !== r.label),
    [segs]
  );

  const dayMiles = milesDriven(segs);
  const totals = Object.fromEntries(
    STATUS_ROWS.map((r) => [r.key, day.totals?.[r.key] ?? 0])
  );
  const sum = sumTotals(totals);
  const aligned = isAligned(totals);
  const rc = recap(totals, cycleUsed ?? (day.cycle_used ?? null));
  const pretty = prettyDate(day.date); // "Thu Sep 10, 2026" for both ISO + pretty input
  const headline = pretty.split(" ")[0].toLowerCase().replace(/[,]/g, "");
  const shortDate = pretty.split(" ").slice(1).join(" ");

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
        {/* ---- zone 1 (simplified): identity header strip ---- */}
        <rect x="0" y="0" width={VIEW.w} height={46} fill="#043b4c" />
        <text x="18" y="30" className="sheet-title">
          DRIVER'S DAILY LOG
        </text>
        <FormField x={318} label="date" value={pretty} />
        <FormField x={452} label="total miles" value={String(dayMiles)} mono />
        <FormField x={598} label="carrier" value="—" />
        <FormField x={744} label="vehicle no." value="—" />
        <FormField x={810} label="trailer no." value="—" />
        <text x={VIEW.w - 20} y="30" className="sheet-title sheet-title--cram" textAnchor="end">
          24-HOUR GRID · 49 CFR 395.8
        </text>

        {/* ---- zone 2: the grid ---- */}
        <line
          x1={MARGIN.left - 8}
          y1={rowTop(0)}
          x2={MARGIN.left + GRID_W}
          y2={rowTop(0)}
          stroke="#0a3d4e"
          strokeWidth="2"
        />

        {/* 25 full-height hour lines, all heaviest weight */}
        {HOUR_MARKS.map(({ hour, minutes, label }) => (
          <g key={hour}>
            <line
              x1={xOf(minutes)}
              x2={xOf(minutes)}
              y1={rowTop(0)}
              y2={gridBottom()}
              stroke="#0a4e61"
              strokeWidth="1.5"
            />
            <text x={xOf(minutes)} y={MARGIN.top - 20} textAnchor="middle" className="sheet-hour">
              {label}
            </text>
          </g>
        ))}

        {/* 3 quarter ticks per hour per row, alternating direction */}
        {quarterTicks().map((tck, i) => (
          <line
            key={i}
            x1={tck.x}
            x2={tck.x}
            y1={tck.y1}
            y2={tck.y2}
            stroke="#0a4e61"
            strokeWidth={tck.long ? 1 : 0.75}
          />
        ))}

        {/* row boundary lines + labels + ruled totals cells */}
        {STATUS_ROWS.map((row, i) => (
          <g key={row.key}>
            <line
              x1={MARGIN.left - 8}
              x2={MARGIN.left + GRID_W}
              y1={rowTop(i)}
              y2={rowTop(i)}
              stroke="#0a4e61"
              strokeWidth="1"
            />
            <text
              x={MARGIN.left - 12}
              y={centerY(i)}
              textAnchor="end"
              dominantBaseline="middle"
              className="sheet-row-label"
            >
              {row.label}
            </text>

            {/* totals cell: box + rule to print the number on */}
            <rect
              x={TOTALS_X}
              y={rowTop(i) + 2}
              width={TOTALS_W}
              height={ROW_H - 4}
              fill="#fbfcfc"
              stroke="#9fb4b8"
              strokeWidth="0.8"
            />
            <line
              x1={TOTALS_X + 6}
              x2={TOTALS_X + TOTALS_W - 6}
              y1={centerY(i) + 5}
              y2={centerY(i) + 5}
              stroke="#9fb4b8"
              strokeWidth="1"
            />
            <text
              x={TOTALS_X + TOTALS_W / 2}
              y={centerY(i) - 1}
              textAnchor="middle"
              className="sheet-total num"
            >
              {fmt(totals[row.key])}
            </text>
          </g>
        ))}
        <line
          x1={MARGIN.left - 8}
          x2={MARGIN.left + GRID_W}
          y1={gridBottom()}
          y2={gridBottom()}
          stroke="#0a4e61"
          strokeWidth="1"
        />

        {/* ---- the stepped duty line (step function, never diagonal) ---- */}
        {transitions.map((t, i) => (
          <line
            key={`c${i}`}
            x1={t.x}
            x2={t.x}
            y1={t.yFrom}
            y2={t.yTo}
            stroke={STATUS_STROKE[t.into]}
            strokeWidth="1.6"
            opacity="0.85"
          />
        ))}
        {runs.map((r, i) => (
          <path
            key={i}
            d={`M ${r.x1} ${r.y} L ${r.x2} ${r.y}`}
            fill="none"
            stroke={STATUS_STROKE[r.status]}
            strokeWidth={STATUS_WIDTH[r.status]}
            strokeDasharray={STATUS_DASH[r.status]}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {/* ---- zone 3: remarks lane, ticked at each change x ---- */}
        <text x={MARGIN.left} y={gridBottom() + 26} className="sheet-remarks">
          REMARKS
        </text>
        {remarks.map((r, i) => (
          <g key={i}>
            <line
              x1={r.x}
              x2={r.x}
              y1={gridBottom()}
              y2={gridBottom() + REMARK_DROP}
              stroke="#64748b"
              strokeWidth="1"
            />
            <text
              x={Math.max(r.x, MARGIN.left + 66)}
              y={gridBottom() + REMARK_DROP + 12 + (i % 2 ? 10 : 0)}
              transform={`rotate(-40 ${Math.max(r.x, MARGIN.left + 66)} ${gridBottom() + REMARK_DROP + 6})`}
              className="sheet-remark"
            >
              {r.label}
            </text>
          </g>
        ))}

        {/* ---- zones 4-5 (simplified): shipping + recap strip ---- */}
        <g>
          <line
            x1={MARGIN.left - 8}
            y1={VIEW.h - 58}
            x2={VIEW.w - 14}
            y2={VIEW.h - 58}
            stroke="#9fb4b8"
            strokeWidth="0.8"
          />
          <text x={MARGIN.left} y={VIEW.h - 36} className="sheet-recap txt">
            SHIPPING DOC NO.{fill()} SHIPPER/COMMODITY{fill()}
          </text>
          <text x={MARGIN.left} y={VIEW.h - 20} className="sheet-recap txt">
            ON DUTY TODAY {fmt(rc.onDutyToday)} · OFF DUTY {fmt(rc.offDutyToday)} · SLEEPER {fmt(rc.sleeperToday)} · DRIVING {fmt(rc.drivingToday)}
          </text>
          {rc.availableTomorrow != null && (
            <text x={VIEW.w - 14} y={VIEW.h - 20} className="sheet-recap txt" textAnchor="end">
              70HR CYCLE: {fmt(rc.cycleUsed)} USED · {fmt(rc.availableTomorrow)} AVAIL
            </text>
          )}
          <text
            x={VIEW.w - 14}
            y={VIEW.h - 36}
            textAnchor="end"
            className={`sheet-chip ${aligned ? "ok" : "bad"}`}
          >
            {aligned ? "✓ 24.00" : `Δ ${fmt(Math.abs(sum - 24))} — must equal 24.00`}
          </text>
        </g>
      </svg>
    </article>
  );
}

function FormField({ x, label, value, mono }) {
  return (
    <g>
      <text x={x} y="20" className="sheet-field-label">
        {label}
      </text>
      <text x={x} y="35" className={`sheet-field-value ${mono ? "num" : ""}`}>
        {value}
      </text>
    </g>
  );
}

function milesDriven(segments) {
  const driving = segments.filter((s) => s.status === "driving");
  if (!driving.length) return 0;
  return Math.max(
    0,
    Math.round(driving[driving.length - 1].distance - driving[0].distance)
  );
}

/** blank underline for print-style form fields. */
const fill = () => " ____________";

/** drop noise labels ("en route" fallbacks) and clip over-long place names. */
function clipLabel(s) {
  const t = (s ?? "").trim();
  if (!t || /^en route$/i.test(t)) return null;
  return t.length > 22 ? `${t.slice(0, 22)}…` : t;
}

/** accept "2026-09-10" or "Thu Sep 10, 2026", always render "Thu, Sep 10, 2026". */
function prettyDate(d) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
    const dt = new Date(`${d}T00:00:00`);
    if (!Number.isNaN(dt.getTime())) {
      return dt.toLocaleDateString("en-US", {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }
  }
  return d;
}

const fmt = (h) => (Math.round(h * 10) / 10 === Math.round(h) ? h.toFixed(1) : h.toFixed(2));