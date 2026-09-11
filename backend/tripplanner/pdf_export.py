"""
pdf_export - compliance packet builder.

Turns one or more persisted trips (their DailyLog day sheets) into a single
Record-of-Duty-Status PDF: a per-day 24x4 shaded grid in FMCSA 395.8 order,
a line-4 totals row with the mandatory 24.00 checksum, a remarks column and
a per-trip recap. Pure reportlab; no DB writes, no templates.

The on-screen SVG grid stays the canonical visual; this is the print/audit
artifact a safety reviewer can hand to a DOT inspector.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

STATUS_ORDER = [
    ("off_duty", "OFF DUTY"),
    ("sleeper_berth", "SLEEPER BERTH"),
    ("driving", "DRIVING"),
    ("on_duty_not_driving", "ON DUTY (NOT DRIVING)"),
]

SHADE = {
    "off_duty": colors.HexColor("#5c747c"),
    "sleeper_berth": colors.HexColor("#64748b"),
    "driving": colors.HexColor("#2dd4bf"),
    "on_duty_not_driving": colors.HexColor("#f4c66d"),
}

# a cell is "shaded" when a single status owns at least 30 of its 60 minutes
SHADE_MIN_MINUTES = 30


def _secs(hhmm):
    h, m = (hhmm.split(":") if isinstance(hhmm, str) else ("00", "00"))
    return int(h) * 3600 + int(m) * 60


def _hour_hits(segments, hour):
    """duty statuses overlapping `hour`, as (status, minutes) pairs."""
    window_start = hour * 3600
    window_end = window_start + 3600
    hits = []
    for seg in segments:
        try:
            seg_start = _secs(seg["start_time"])
            seg_end = _secs(seg["end_time"])
        except (ValueError, KeyError, TypeError):
            continue
        overlap = min(window_end, seg_end) - max(window_start, seg_start)
        if overlap > 0:
            hits.append((seg["status"], round(overlap / 60.0, 2)))
    return hits


def _dominant_fill(segments, hour):
    """single-owner shading: the status holding the hour, else None."""
    hits = _hour_hits(segments, hour)
    if not hits:
        return None
    total = sum(m for _, m in hits)
    if len(hits) == 1 and hits[0][1] >= SHADE_MIN_MINUTES:
        return SHADE.get(hits[0][0])
    if total >= 30 and len(hits) == 2:
        # one contiguous status owns the hour outright
        for status, mins in hits:
            if mins >= 45:
                return SHADE.get(status)
    return None


def _remarks(segments):
    lines = []
    for seg in segments:
        if seg.get("status") == "driving":
            continue
        start = seg.get("start_time", "n/a")
        end = seg.get("end_time", "n/a")
        label = (seg.get("name") or seg.get("location") or "").strip()
        lines.append(f"{start}-{end}  {seg['status'].replace('_', ' ').upper()}: {label}")
    return "\n".join(lines) or "no stops logged this day"


def _day_grid_table(segments):
    base = ParagraphStyle("base", fontSize=8.5, leading=11)
    tiny = ParagraphStyle("tiny", parent=base, fontSize=7, leading=9)
    centre = ParagraphStyle("centre", parent=base, alignment=TA_CENTER, fontSize=6.5)

    hour_header = [Paragraph(f"{h:02d}", centre) for h in range(24)]
    rows = [[Paragraph("[hh]", centre)] + hour_header]

    for key, label in STATUS_ORDER:
        row = [Paragraph(label, tiny)]
        for hour in range(24):
            cell = Paragraph("", centre)
            row.append(cell)
        rows.append(row)

    grid = Table(rows, colWidths=None, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#8a9ba5")),
        ("BOX", (0, 0), (-1, -1), 0.9, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#e5edf0")),
    ]
    for idx, (key, _label) in enumerate(STATUS_ORDER, start=1):
        for hour in range(24):
            fill = _dominant_fill(segments, hour)
            if fill:
                style.append(("BACKGROUND", (hour + 1, idx), (hour + 1, idx), fill))
    grid.setStyle(TableStyle(style))
    return grid


def _totals_line(totals):
    parts = [f"{label}: {totals.get(key, 0.0):.2f}h" for key, label in STATUS_ORDER]
    check = sum(totals.get(k, 0.0) for k, _ in STATUS_ORDER)
    ok = "✓ MATCHES 24.00" if abs(check - 24.0) < 0.001 else "⚠ MUST BE 24.00"
    return f"{'   '.join(parts)}  |  day total {check:.2f} — {ok}"


def _recap_table(logs):
    base = ParagraphStyle("base", fontSize=8.5, leading=11)
    tiny = ParagraphStyle("tiny", parent=base, fontSize=7.5, leading=9)
    header = ["DAY / DATE", "DRIVING", "ON DUTY", "SLEEPER", "OFF DUTY", "TOTAL"]
    rows = [[Paragraph(c, tiny) for c in header]]
    for day_idx, day in enumerate(logs, start=1):
        totals = day.totals if isinstance(day.totals, dict) else {}
        values = (
            f"{day_idx} — {day.date}",
            totals.get("driving", 0.0),
            totals.get("on_duty_not_driving", 0.0),
            totals.get("sleeper_berth", 0.0),
            totals.get("off_duty", 0.0),
            sum(totals.get(k, 0.0) for k, _ in STATUS_ORDER),
        )
        rows.append([Paragraph(str(v), tiny) for v in values])
    recap = Table(rows)
    recap.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8a9ba5")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edf0")),
    ]))
    return recap


def build_logs_pdf(groups):
    """groups: [(Trip, [DailyLog, ...]), ...] -> PDF bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.5 * inch,
        title="HOS Record of Duty Status",
    )

    base = ParagraphStyle("base", fontSize=8.5, leading=11)
    tiny = ParagraphStyle("tiny", parent=base, fontSize=7.5, leading=9)
    h = ParagraphStyle("h", parent=base, fontSize=13, leading=16)

    story = [
        Paragraph("RECORD OF DUTY STATUS — HOS DAILY LOGS", h),
        Paragraph(
            "49 CFR 395.8 · planning-grade record from Spotter (no ELD feed) · "
            "line-4 cells shaded by the duty status owning each hour",
            tiny,
        ),
        Spacer(1, 8),
    ]

    for trip, logs in groups:
        driver = trip.driver
        driver_name = "UNASSIGNED"
        cdl = ""
        if driver:
            driver_name = driver.user.get_full_name() or driver.user.username
            cdl = driver.cdl_number or ""

        story.append(Paragraph(
            f"<b>Driver:</b> {driver_name} &nbsp;&nbsp; <b>CDL/DOT:</b> {cdl or '—'} &nbsp;&nbsp; "
            f"<b>Vehicle:</b> {trip.vehicle.unit_no if trip.vehicle else '—'}",
            base,
        ))
        story.append(Paragraph(
            f"<b>Trip #{trip.id}:</b> {trip.current_location} → {trip.pickup_location} → "
            f"{trip.dropoff_location} &nbsp;&nbsp; "
            f"<b>{trip.distance_miles:.1f} mi / {trip.driving_minutes / 60:.1f} h planned</b>",
            base,
        ))
        story.append(Spacer(1, 8))

        for day_index, day in enumerate(logs, start=1):
            segments = day.segments if isinstance(day.segments, list) else []
            totals = day.totals if isinstance(day.totals, dict) else {}
            date_label = day.date.strftime("%a %b %d, %Y")

            story.append(Paragraph(
                f"<b>DAY {day_index} — {date_label}</b>  &nbsp;(line 4: 24 cells per day)", base,
            ))
            story.append(_day_grid_table(segments))
            story.append(Spacer(1, 3))
            story.append(Paragraph(f"<b>Line 4 totals — {_totals_line(totals)}</b>", base))
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>REMARKS</b>", base))
            story.append(Paragraph(_remarks(segments), tiny))
            story.append(Spacer(1, 10))

        story.append(Paragraph(
            f"<b>RECAP — trip #{trip.id} (planning projection, not an audited record)</b>", base,
        ))
        story.append(_recap_table(logs))
        story.append(Spacer(1, 14))

    doc.build(story)
    return buf.getvalue()


def build_trip_logs_pdf(trip):
    """Single-trip compliance packet -> bytes."""
    logs = list(trip.daily_logs.all().order_by("day_number"))
    return build_logs_pdf([(trip, logs)])