/**
 * FMCSA 395.8 daily-log grid — pure geometry + rules, no JSX.
 *
 * everything here is deterministic math over a normalized 0-1440 minute
 * axis so the renderer (`LogSheet.jsx`) and the spec test
 * (`scripts/logsheet.spec.test.js`) share one source of truth.
 *
 * hard rules enforced:
 *   - exactly 4 rows, fixed order, equal height
 *   - 25 full-height hour lines, labeled midnight..noon..midnight
 *   - 3 interior quarter ticks per hour PER ROW; rows 1-2 hang down from
 *     the row's top edge, rows 3-4 rise up from the row's bottom edge,
 *     and the :30 tick is longer than :15/:45
 *   - the duty line is one continuous horizontal-then-vertical step graph
 *   - totals must sum to 24.00
 */

export const STATUS_ROWS = [
  { key: "off_duty", label: "OFF DUTY" },
  { key: "sleeper_berth", label: "SLEEPER BERTH" },
  { key: "driving", label: "DRIVING" },
  { key: "on_duty_not_driving", label: "ON DUTY (NOT DRIVING)" },
];

export const ROW_INDEX = Object.freeze(
  Object.fromEntries(STATUS_ROWS.map((r, i) => [r.key, i]))
);

export const VIEW = { w: 1120, h: 470 };
export const HEADER_H = 46;
export const MARGIN = { left: 170, right: 104, top: HEADER_H + 34, bottom: 92 };

export const GRID_W = VIEW.w - MARGIN.left - MARGIN.right;
export const GRID_H = VIEW.h - MARGIN.top - MARGIN.bottom;
export const ROW_H = GRID_H / STATUS_ROWS.length;

/** 0-1440 minutes on the horizontal axis. */
export const xOf = (minutes) => MARGIN.left + (minutes / 1440) * GRID_W;
/** centerline of a given duty row (the line lives on the center, by mandate). */
export const centerY = (row) => MARGIN.top + row * ROW_H + ROW_H / 2;
export const rowTop = (row) => MARGIN.top + row * ROW_H;
export const rowBottom = (row) => MARGIN.top + (row + 1) * ROW_H;
/** bottom edge of the whole 4-row grid block. */
export const gridBottom = () => rowBottom(STATUS_ROWS.length - 1);

/** 25 hour marks: 0..24 inclusive; 0 and 24 are "midnight", 12 is "noon". */
export const HOUR_MARKS = Object.freeze(
  Array.from({ length: 25 }, (_, h) => ({
    hour: h,
    minutes: h * 60,
    label: h === 0 || h === 24 ? "midnight" : h === 12 ? "noon" : String(h % 12),
  }))
);

/**
 * quarter-hour ticks. per hour per row there are exactly 3 marks (:15,:30,:45).
 * rows 1-2: the tick hangs DOWN from the row's top boundary;
 * rows 3-4: the tick rises UP from the row's bottom boundary.
 * the :30 mark is longer (half the row height) and the :15/:45 are ~70% of it.
 */
export function quarterTicks() {
  const ticks = [];
  for (let row = 0; row < STATUS_ROWS.length; row++) {
    const hangsDown = row < 2;
    for (let h = 0; h < 24; h++) {
      for (const q of [15, 30, 45]) {
        const x = xOf(h * 60 + q);
        const long = q === 30;
        const len = long ? 0.5 * ROW_H : 0.35 * ROW_H;
        const y1 = hangsDown ? rowTop(row) : rowBottom(row);
        ticks.push({
          x,
          y1,
          y2: hangsDown ? y1 + len : y1 - len,
          long,
          row,
        });
      }
    }
  }
  return ticks;
}

/** convert backend segments (start/end in float hours) to pure minutes. */
export function toMinutes(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  return h * 60 + m;
}

export function normalizeSegments(raw) {
  return (raw || []).map((s) => ({
    status: s.status,
    start_minutes: (s.start_hour != null ? s.start_hour : toMinutes(s.start_time)) * 60,
    end_minutes: (s.end_hour != null ? s.end_hour : toMinutes(s.end_time)) * 60,
    distance: s.distance ?? 0,
    location: s.location ?? s.name ?? "",
    name: s.name ?? s.location ?? "",
  }));
}

/**
 * the duty line. a single step-function polyline: horizontal runs on each
 * row's centerline joined by vertical connectors at the change points.
 * returns { runs, transitions } where transitions carry the status the line
 * is moving INTO (for coloring the step in the direction of travel).
 */
export function buildDutyLine(segments) {
  const runs = [];
  const transitions = [];
  let prevY = null;
  for (const seg of segments) {
    const x1 = xOf(seg.start_minutes);
    const x2 = xOf(seg.end_minutes);
    const y = centerY(ROW_INDEX[seg.status] ?? 0);
    if (prevY !== null && y !== prevY) {
      transitions.push({ x: x1, yFrom: prevY, yTo: y, into: seg.status });
    }
    runs.push({ x1, x2, y, status: seg.status });
    prevY = y;
  }
  return { runs, transitions };
}

/**
 * remarks lane entries: one per status change (the start of every segment
 * after the first — the first segment carries the day open from yesterday,
 * so it is not a change). each needs the location string to draw.
 */
export function buildRemarks(segments) {
  return segments.slice(1).map((seg) => ({
    x: xOf(seg.start_minutes),
    minutes: seg.start_minutes,
    label: seg.name && seg.name !== seg.location ? seg.name : seg.location,
  }));
}

export function sumTotals(totals) {
  return STATUS_ROWS.reduce((acc, row) => acc + (totals[row.key] ?? 0), 0);
}

/** the hard checksum: a single day must total 24.00. */
export const isAligned = (totals) => Math.abs(sumTotals(totals) - 24) < 1e-6;

/** compact recap (zone 5) figures. */
export function recap(totals, cycleUsed) {
  const onDutyToday = (totals.driving ?? 0) + (totals.on_duty_not_driving ?? 0);
  return {
    onDutyToday,
    offDutyToday: totals.off_duty ?? 0,
    sleeperToday: totals.sleeper_berth ?? 0,
    drivingToday: totals.driving ?? 0,
    cycleUsed: cycleUsed ?? null,
    availableTomorrow: cycleUsed == null ? null : Math.max(0, 70 - cycleUsed),
  };
}