"""duty-status helpers shared by the API and the watchdog.

a driver's record of duty status for *today* is drawn from DutyEvent rows:
the open event plus everything since local midnight, padded with off duty at
both ends so the four graph rows sum to 24 hours like the paper 395.8 sheet.
planning-grade, not an engine-linked ELD record.
"""

from django.utils import timezone

from .models import DutyEvent


def start_of_today():
    local = timezone.localtime(timezone.now())
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return timezone.make_aware(local_midnight.replace(tzinfo=None))


def open_event(driver):
    return (
        DutyEvent.objects.filter(driver=driver, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )


def today_events(driver):
    return list(
        DutyEvent.objects.filter(driver=driver, started_at__gte=start_of_today())
        .order_by("started_at")
        .values("id", "status", "started_at", "ended_at", "location", "remark", "trip_id")
    )


def _minutes_since_local_midnight(dt):
    local = timezone.localtime(dt)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((local - midnight).total_seconds() // 60)


def today_segments(driver):
    """segments covering the whole 0-1440 minute day (for the log sheet):
    real events, padded with off duty before the first change and after the
    last, so the sheet always balances to 24.00."""
    day_start = start_of_today()
    now = timezone.now()
    rows = (
        DutyEvent.objects.filter(driver=driver, started_at__gte=day_start)
        .order_by("started_at")
        .values("status", "started_at", "ended_at", "location", "remark")
    )
    segments = []
    cursor = 0
    for ev in rows:
        start = _minutes_since_local_midnight(ev["started_at"])
        end = _minutes_since_local_midnight(ev["ended_at"] or now)
        end = max(end, start)
        if start > cursor:
            segments.append(_seg("off_duty", cursor, start, ""))
        segments.append(_seg(ev["status"], start, end, ev["location"] or ev["remark"] or ""))
        cursor = end
    if cursor < 1440:
        segments.append(_seg("off_duty", cursor, 1440, ""))
    return segments


def _seg(status, start, end, location):
    return {
        "status": status,
        "start_time": _mm_to_hm(start),
        "end_time": _mm_to_hm(end),
        "start_min": start,
        "end_min": end,
        "location": location,
        "name": status.replace("_", " ").title(),
    }


def _mm_to_hm(minutes):
    minutes = max(0, min(minutes, 1440))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def today_totals(segments):
    """round to the fourth but keep exact 24: drive etc from the segments,
    off duty fills the remainder."""
    hours = {"driving": 0.0, "sleeper_berth": 0.0, "on_duty_not_driving": 0.0}
    for s in segments:
        minutes = s.get("end_min", 0) - s.get("start_min", 0)
        if s["status"] in hours and minutes > 0:
            hours[s["status"]] += minutes / 60.0
    hours["off_duty"] = 24.0 - sum(hours.values())
    return {k: round(v, 2) for k, v in hours.items()}


def today_driving_hours(driver):
    """completed + in-progress driving today (seconds->hours)."""
    day_start = start_of_today()
    now = timezone.now()
    total = 0.0
    rows = DutyEvent.objects.filter(
        driver=driver, status="driving",
        started_at__gte=day_start, started_at__lte=now,
    ).values("started_at", "ended_at")
    for ev in rows:
        end = min(ev["ended_at"] or now, now)
        if end < ev["started_at"]:
            continue
        total += (end - ev["started_at"]).total_seconds()
    return round(total / 3600.0, 2)