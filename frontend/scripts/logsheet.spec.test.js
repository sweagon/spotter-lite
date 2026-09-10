/**
 * Reference-spec validation for the daily-log grid (spec section 8 + 9):
 *   - 4 rows, fixed order, equal height
 *   - 25 full-height hour lines, labeled midnight..noon..midnight
 *   - 3 quarter ticks per hour per row; rows 1-2 hang down, rows 3-4 rise
 *     up, :30 longer than :15/:45
 *   - the duty line is one continuous step-function polyline
 *   - totals sum to 24.00
 *   - every status-change point carries a location string for the remarks lane
 *
 * run: npm test
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  STATUS_ROWS,
  ROW_INDEX,
  HOUR_MARKS,
  quarterTicks,
  xOf,
  centerY,
  rowTop,
  rowBottom,
  gridBottom,
  VIEW,
  MARGIN,
  GRID_H,
  ROW_H,
  buildDutyLine,
  buildRemarks,
  normalizeSegments,
  sumTotals,
  isAligned,
  recap,
  toMinutes,
} from "../src/components/logSheetSpec.js";

const at = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

const seg = (status, start, end, location) => ({
  status,
  start_minutes: at(start),
  end_minutes: at(end),
  location: location ?? "",
  name: location ?? "",
});

/**
 * spec section 8: the reference "completed log" example.
 *   off duty at midnight -> on duty 06:00 (Richmond) -> drives with stops
 *   -> sleeper 14:15-16:00 (Cherry Hill) -> drives -> off duty 20:00
 *   (Newark). totals: off 10.0, sleeper 1.75, driving 7.75, on-duty 4.5.
 */
const EXAMPLE = [
  seg("off_duty", "00:00", "06:00"),
  seg("on_duty_not_driving", "06:00", "06:30", "Richmond, VA"),
  seg("driving", "06:30", "14:15", "Richmond, VA"),
  seg("sleeper_berth", "14:15", "16:00", "Cherry Hill, NJ"),
  seg("on_duty_not_driving", "16:00", "20:00", "Cherry Hill, NJ"),
  seg("off_duty", "20:00", "24:00", "Newark, NJ"),
];

test("rows: exactly 4, fixed order, never reordered, equal height", () => {
  assert.deepEqual(
    STATUS_ROWS.map((r) => r.key),
    ["off_duty", "sleeper_berth", "driving", "on_duty_not_driving"]
  );
  const tops = STATUS_ROWS.map((_, i) => rowTop(i));
  for (let i = 1; i < tops.length; i++) {
    assert.ok(Math.abs(tops[i] - tops[0]) === i * ROW_H);
  }
  assert.ok(Math.abs(gridBottom() - rowTop(0) - GRID_H) < 1e-9);
  assert.ok(Math.abs(ROW_H * 4 - GRID_H) < 1e-9);
});

test("hour gridlines: 25, spanning full grid height, midnight..noon..midnight", () => {
  assert.equal(HOUR_MARKS.length, 25);
  assert.equal(HOUR_MARKS[0].label, "midnight");
  assert.equal(HOUR_MARKS[12].label, "noon");
  assert.equal(HOUR_MARKS[24].label, "midnight");
  assert.deepEqual(
    HOUR_MARKS.slice(1, 12).map((m) => m.label),
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]
  );
  assert.deepEqual(
    HOUR_MARKS.slice(13, 24).map((m) => m.label),
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]
  );
  for (let h = 0; h <= 24; h++) assert.equal(HOUR_MARKS[h].minutes, h * 60);
});

test("quarter ticks: 3 per hour per row, alternating direction, :30 longest", () => {
  const ticks = quarterTicks();
  assert.equal(ticks.length, 4 * 24 * 3);
  for (const t of ticks) {
    const ratio = (t.x - MARGIN.left) / (VIEW.w - MARGIN.left - MARGIN.right);
    const minutes = Math.round((ratio * 1440) % 60);
    assert.ok([15, 30, 45].includes(minutes), `tick at :${minutes}`);
  }
  for (const t of ticks) {
    const row = t.row;
    if (row < 2) {
      assert.equal(t.y1, rowTop(row), "rows 1-2 hang from the row's top edge");
      assert.ok(t.y2 > t.y1, "rows 1-2 point downward");
    } else {
      assert.equal(t.y1, rowBottom(row), "rows 3-4 rise from the row's bottom edge");
      assert.ok(t.y2 < t.y1, "rows 3-4 point upward");
    }
    const len = Math.abs(t.y2 - t.y1);
    if (t.long) assert.equal(len, 0.5 * ROW_H);
  }
  const byRow = (r) => ticks.filter((t) => t.row === r);
  for (let r = 0; r < 4; r++) {
    const lens30 = byRow(r).filter((t) => t.long).map((t) => Math.abs(t.y2 - t.y1));
    const lensMinor = byRow(r).filter((t) => !t.long).map((t) => Math.abs(t.y2 - t.y1));
    assert.ok(lens30[0] > lensMinor[0], `row ${r}: :30 longer than :15/:45`);
  }
});

test("duty line: continuous step-function, no gaps, no diagonals, 0..1440", () => {
  const { runs, transitions } = buildDutyLine(EXAMPLE);
  assert.equal(runs.length, EXAMPLE.length);
  assert.equal(transitions.length, EXAMPLE.length - 1);
  assert.ok(Math.abs(runs[0].x1 - xOf(0)) < 1e-9, "starts at midnight");
  assert.ok(Math.abs(runs[runs.length - 1].x2 - xOf(1440)) < 1e-9, "ends at midnight");

  runs.forEach((r, i) => {
    assert.ok(r.x2 >= r.x1, "horizontal runs never go backwards");
    assert.ok(Math.abs(r.y - centerY(ROW_INDEX[r.status])) < 1e-9, "runs live on the centerline");
    assert.equal(r.y, r.y, "a run is horizontal (constant y)");
    if (i > 0) {
      assert.ok(Math.abs(r.x1 - runs[i - 1].x2) < 1e-9, "no gaps between runs");
    }
  });

  transitions.forEach((t, i) => {
    assert.ok(Math.abs(t.x - runs[i + 1].x1) < 1e-9, "connector sits at the change point");
    assert.equal(t.x, t.x, "connector is vertical (constant x)");
    assert.ok(Math.abs(t.yFrom - runs[i].y) < 1e-9, "connector leaves the previous row");
    assert.ok(Math.abs(t.yTo - runs[i + 1].y) < 1e-9, "connector lands at the next row");
  });

  assert.equal(sumTotals({} ), 0); // untouched rows contribute nothing
});

test("worked example: 10 + 1.75 + 7.75 + 4.5 = 24.00 exactly", () => {
  const totals = {
    off_duty: 10,
    sleeper_berth: 1.75,
    driving: 7.75,
    on_duty_not_driving: 4.5,
  };
  assert.equal(sumTotals(totals), 24);
  assert.ok(isAligned(totals));

  const snap = {
    off_duty: 10,
    sleeper_berth: 1.75,
    driving: 7.75,
    on_duty_not_driving: 4.5,
  };
  const structTotals = {};
  for (const r of STATUS_ROWS) {
    structTotals[r.key] =
      EXAMPLE.filter((s) => s.status === r.key).reduce(
        (a, s) => a + (s.end_minutes - s.start_minutes),
        0
      ) / 60;
  }
  for (const k of Object.keys(snap)) {
    assert.equal(structTotals[k], snap[k], `${k} hours`);
  }
  assert.equal(sumTotals(structTotals), 24);
});

test("remarks: one per change, tick at the change x, location always present", () => {
  const remarks = buildRemarks(EXAMPLE);
  assert.equal(remarks.length, EXAMPLE.length - 1);
  EXAMPLE.slice(1).forEach((s, i) => {
    assert.ok(Math.abs(remarks[i].x - xOf(s.start_minutes)) < 1e-9);
    assert.ok(remarks[i].label.length > 0, `change ${i} has a place name`);
  });
  assert.equal(remarks[2].label, "Cherry Hill, NJ"); // sleeper entry
  assert.equal(remarks[4].label, "Newark, NJ"); // end-of-day off duty
});

test("backend segments (float hours) normalize to the same minutes", () => {
  const raw = [
    { status: "driving", start_hour: 6.5, end_hour: 14.25, location: "Richmond, VA", distance: 410.2 },
  ];
  const [n] = normalizeSegments(raw);
  assert.equal(n.start_minutes, 390);
  assert.equal(n.end_minutes, 855);
  assert.equal(n.distance, 410.2);
  assert.equal(toMinutes("24:00"), 1440);
  assert.equal(toMinutes("00:00"), 0);
});

test("recap: cycle math is derived and bounded", () => {
  const rc = recap({ off_duty: 10, sleeper_berth: 1.75, driving: 7.75, on_duty_not_driving: 4.5 }, 40.5);
  assert.equal(rc.onDutyToday, 12.25);
  assert.equal(rc.drivingToday, 7.75);
  assert.equal(rc.availableTomorrow, 29.5);
  assert.equal(recap({}, 99).availableTomorrow, 0); // never negative
});