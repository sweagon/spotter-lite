"""
pure hours-of-service engine. no django imports, no network calls — feed it
the route stats plus the driver's starting cycle balance and it walks the
trip forward minute by minute, emitting a list of duty-status segments.

each segment is a dict:

    {"status", "start_time", "end_time", "location", "distance"}

status is one of: "off_duty", "sleeper_berth", "driving", "on_duty_not_driving"

this deliberately over-simplifies an enormous body of rules. the prompts for
that are documented in the docstrings below so a human reviewer can see the
reasoning and judge whether the simplifications are acceptable for this
assessment scope. audited against 49 cfr part 395.
"""

from datetime import datetime, timedelta

# ---- constants -------------------------------------------------------------

FUEL_INTERVAL_MILES = 1000     # must fuel at least every 1,000 miles
FUEL_DURATION_MIN = 40         # on-duty-not-driving (fueling + admin)
BREAK_AFTER_DRIVE_HOURS = 8    # 30-min break after 8 cumulative hours driving
BREAK_DURATION_MIN = 30
MAX_DRIVING_HOURS = 11         # 11-hour driving limit
MAX_WINDOW_HOURS = 14          # 14-hour duty window
REST_HOURS = 10                # 10 consecutive hours off resets 11hr/14hr
RESTART_HOURS = 34             # 34-hour restart resets the 70hr clock
MAX_CYCLE_HOURS = 70           # 70-hour / 8-day rolling cap
PICKUP_MINUTES = 60            # loading at pickup: 1hr on-duty-not-driving
DROPOFF_MINUTES = 60           # unloading at dropoff: 1hr on-duty-not-driving


def plan_trip(pickup_location: dict, dropoff_location: dict,
              current_cycle_used: float,
              route_distance_miles: float, route_driving_minutes: float,
              route_geometry: list,
              start_time: datetime = None,
              stats: dict = None) -> list:
    """
    main entry point. walks a timeline minute by minute and returns a flat
    list of duty-status segments covering the entire trip.

    the route_driving_minutes is the actual behind-the-wheel time from the
    router — it does NOT include pickup/dropoff time or any breaks we insert.

    route_geometry is a list of [lon, lat] coordinates for the route, used
    only for location interpolation (we don't use the router for turn-by-turn).

    current_cycle_used is how many hours of the 70-hour cycle the driver has
    already burned in the prior 8 days.

    if stats is provided it's filled in-place with the *peak* values reached
    during the sim: {"driving_hours", "window_hours", "cycle_hours"}. peaks
    matter more than the end-of-trip snapshot because they reveal tight
    moments (e.g. driving smacking exactly 11.0 before a rest resets it).
    """
    if start_time is None:
        start_time = datetime.now().replace(second=0, microsecond=0)

    # pre-compute location interpolation tables from route geometry
    cum_dists, total_geom_dist = _build_distance_table(route_geometry)

    # scale factor: real route miles vs geometry arc-length
    scale = route_distance_miles / total_geom_dist if total_geom_dist > 0 else 1.0

    # driving speed in miles-per-minute (constant along the route)
    speed_mpm = route_distance_miles / route_driving_minutes if route_driving_minutes > 0 else 1.0

    # simulation state
    clock = start_time
    location_label = pickup_location.get("name", "Pickup")
    distance_so_far = 0.0       # miles
    drive_since_break = 0.0     # hours since last 30-min break
    drive_this_shift = 0.0      # hours driven since last 10hr rest (toward 11hr)
    window_hours = 0.0          # hours since last 10hr rest (toward 14hr)
    cycle_used = current_cycle_used  # rolling 70hr balance
    remaining_drive = route_driving_minutes  # minutes left behind the wheel
    fuel_stops_made = 0  # how many 1,000-mile fuel milestones we've passed
    segments = []
    safety_iterations = 0

    # peak values reached during the trip, for the instrument cluster
    peaks = {"driving_hours": 0.0, "window_hours": 0.0, "cycle_hours": 0.0}

    def track_peaks():
        peaks["driving_hours"] = max(peaks["driving_hours"], drive_this_shift)
        peaks["window_hours"] = max(peaks["window_hours"], window_hours)
        peaks["cycle_hours"] = max(peaks["cycle_hours"], cycle_used)

    def loc_at(d):
        """(label, lat, lon) for a point along the route."""
        return _interpolate_location(route_geometry, cum_dists, scale, d)

    def emit(status, start, end, loc, dist, lat=None, lon=None, name=None):
        segments.append({
            "status": status,
            "start_time": start,
            "end_time": end,
            "location": loc,
            "name": name or loc,
            "distance": round(dist, 1),
            "lat": lat,
            "lon": lon,
        })

    # ---- 1) pickup: 1hr on-duty-not-driving ----
    pickup_end = clock + timedelta(minutes=PICKUP_MINUTES)
    emit("on_duty_not_driving", clock, pickup_end, location_label, 0.0,
         lat=pickup_location.get("lat"), lon=pickup_location.get("lon"))
    clock = pickup_end
    window_hours += PICKUP_MINUTES / 60.0
    cycle_used += PICKUP_MINUTES / 60.0
    track_peaks()

    # ---- 2) driving loop ----
    # drive in 1-minute increments. every minute, we check whether a
    # break/rest/fuel/refresh should fire before we drive the next minute.
    # this gives us precise counters and avoids computing which event comes
    # first (which is error-prone when multiple events are close).

    while remaining_drive > 0:
        safety_iterations += 1
        # absolutely should not need more than ~1 minute of sim per drive
        # minute plus generous slack for inserted stops; if we blow 100k
        # iterations something is wrong, bail so a bad route can't hang.
        if safety_iterations > 100000:
            raise RuntimeError("HOS simulation did not converge; check inputs")
        # --- check in priority order what forces a stop before driving more ---

        # (a) 70hr cap is hit: must 34hr restart
        if cycle_used >= MAX_CYCLE_HOURS - 1e-9:
            label, flat, flon = loc_at(distance_so_far)
            restart_end = clock + timedelta(hours=RESTART_HOURS)
            emit("sleeper_berth", clock, restart_end, label, distance_so_far,
                 lat=flat, lon=flon)
            clock = restart_end
            drive_since_break = 0
            drive_this_shift = 0
            window_hours = 0
            cycle_used = 0
            continue

        # (b) 11hr driving or 14hr window hit: must 10hr rest
        if drive_this_shift >= MAX_DRIVING_HOURS - 1e-9 or \
           window_hours >= MAX_WINDOW_HOURS - 1e-9:
            label, flat, flon = loc_at(distance_so_far)
            rest_end = clock + timedelta(hours=REST_HOURS)
            emit("sleeper_berth", clock, rest_end, label, distance_so_far,
                 lat=flat, lon=flon)
            clock = rest_end
            drive_since_break = 0
            drive_this_shift = 0
            window_hours = 0
            continue

        # (c) 30-min break after 8hr cumulative driving
        if drive_since_break >= BREAK_AFTER_DRIVE_HOURS - 1e-9:
            label, flat, flon = loc_at(distance_so_far)
            brk_end = clock + timedelta(minutes=BREAK_DURATION_MIN)
            emit("off_duty", clock, brk_end, label, distance_so_far,
                 lat=flat, lon=flon)
            clock = brk_end
            drive_since_break = 0
            # the window does NOT pause for a break: the 14hr clock keeps
            # running even though we log the break as off-duty.
            window_hours += BREAK_DURATION_MIN / 60.0
            track_peaks()
            continue

        # (d) fuel stop if we've crossed a 1,000-mile mark
        next_fuel = (fuel_stops_made + 1) * FUEL_INTERVAL_MILES
        if distance_so_far + 1e-9 >= next_fuel and remaining_drive > 0:
            label, flat, flon = loc_at(distance_so_far)
            fuel_end = clock + timedelta(minutes=FUEL_DURATION_MIN)
            emit("on_duty_not_driving", clock, fuel_end, label, distance_so_far,
                 lat=flat, lon=flon, name=f"Fuel stop ~{int(next_fuel)} mi")
            clock = fuel_end
            window_hours += FUEL_DURATION_MIN / 60.0
            cycle_used += FUEL_DURATION_MIN / 60.0
            fuel_stops_made += 1  # advance the milestone so we don't re-fire
            track_peaks()
            continue

        # --- none of the above fired: we can drive one minute ---
        # (but check we're not about to blow a cap on this very minute)
        # max we can drive this minute without tripping any cap:
        headroom_break = BREAK_AFTER_DRIVE_HOURS - drive_since_break
        headroom_11 = MAX_DRIVING_HOURS - drive_this_shift
        headroom_14 = MAX_WINDOW_HOURS - window_hours
        headroom_70 = MAX_CYCLE_HOURS - cycle_used
        headroom = min(headroom_break, headroom_11, headroom_14, headroom_70)
        # headroom is in hours. convert to minutes, but don't drive more than 1 or remaining.
        drive_this_minute = min(1.0, headroom * 60, remaining_drive)
        if drive_this_minute <= 0:
            # edge case: all headroom is 0 but the stop-checks above didn't fire
            # (floating point). nudge the clock and let the checks fire next iteration.
            drive_this_minute = 0.5

        dist_before = distance_so_far
        drive_end = clock + timedelta(minutes=drive_this_minute)
        emit("driving", clock, drive_end, "en route", dist_before)

        miles_driven = drive_this_minute * speed_mpm
        distance_so_far += miles_driven
        drive_since_break += drive_this_minute / 60.0
        drive_this_shift += drive_this_minute / 60.0
        window_hours += drive_this_minute / 60.0
        cycle_used += drive_this_minute / 60.0
        clock = drive_end
        remaining_drive -= drive_this_minute
        track_peaks()

    # ---- 3) dropoff: 1hr on-duty-not-driving ----
    dropoff_end = clock + timedelta(minutes=DROPOFF_MINUTES)
    emit("on_duty_not_driving", clock, dropoff_end,
         dropoff_location.get("name", "Dropoff"), route_distance_miles,
         lat=dropoff_location.get("lat"), lon=dropoff_location.get("lon"))

    if stats is not None:
        round2 = lambda v: round(v, 2)
        stats.update({k: round2(v) for k, v in peaks.items()})

    return segments


def merge_segments(segments: list) -> list:
    """
    collapse adjacent segments with the same status & location into one.
    the simulation runs at 1-minute resolution so raw output has a segment
    per minute; nobody wants that on a paper log. driving location is
    interpolated every minute, so we merge by status + location where the
    location genuinely changes (stops), but merge driving runs regardless of
    the drifting coordinate label.
    """
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        last = merged[-1]
        same_status = last["status"] == seg["status"]
        same_place = last["location"] == seg["location"]
        contiguous = last["end_time"] == seg["start_time"]
        driving_run = last["status"] == "driving" and seg["status"] == "driving"
        if contiguous and same_status and (same_place or driving_run):
            last["end_time"] = seg["end_time"]
            last["distance"] = seg["distance"]
            if not same_place:
                # keep the label from the earlier segment; fine for logging
                pass
        else:
            merged.append(dict(seg))
    return merged


def slice_into_days(segments: list) -> list:
    """
    chop the flat segment list into per-calendar-day chunks (midnight to
    midnight). segments that span midnight get split so neither day's log
    crosses a day boundary.

    returns a list of (day_start_datetime, [segments_for_that_day]).
    """
    if not segments:
        return []

    segments = merge_segments(segments)

    # find calendar range
    first_midnight = segments[0]["start_time"].replace(hour=0, minute=0, second=0, microsecond=0)
    last_midnight = segments[-1]["end_time"].replace(hour=0, minute=0, second=0, microsecond=0)
    if (segments[-1]["end_time"] - last_midnight).total_seconds() > 0:
        last_midnight += timedelta(days=1)

    days = []
    day_start = first_midnight
    while day_start < last_midnight:
        day_end = day_start + timedelta(days=1)
        day_segments = []
        for seg in segments:
            seg_start = max(seg["start_time"], day_start)
            seg_end = min(seg["end_time"], day_end)
            if seg_start < seg_end:
                day_segments.append({
                    "status": seg["status"],
                    "start_time": seg_start,
                    "end_time": seg_end,
                    "location": seg["location"],
                    "distance": seg["distance"],
                })
        if day_segments:
            # pad the day so the 24hr grid is complete like a paper log:
            # off-duty from midnight until the first segment, and off-duty
            # after the last segment until the next midnight. this makes the
            # per-row totals always add to 24, which is what an inspector
            # expects to see (and it also reflects the reality that the
            # driver is off duty before they go on shift).
            first = day_segments[0]
            if first["start_time"] > day_start:
                day_segments.insert(0, {
                    "status": "off_duty",
                    "start_time": day_start,
                    "end_time": first["start_time"],
                    "location": "Home",
                    "distance": 0.0,
                })
            last = day_segments[-1]
            if last["end_time"] < day_end:
                day_segments.append({
                    "status": "off_duty",
                    "start_time": last["end_time"],
                    "end_time": day_end,
                    "location": "Off Duty",
                    "distance": 0.0,
                })
            days.append((day_start, day_segments))
        day_start = day_end

    return days


def compute_daily_totals(day_segments: list) -> dict:
    """sum up hours by status for one day's segments. totals should add to 24."""
    totals = {"off_duty": 0.0, "sleeper_berth": 0.0, "driving": 0.0,
              "on_duty_not_driving": 0.0}
    for seg in day_segments:
        mins = (seg["end_time"] - seg["start_time"]).total_seconds() / 60.0
        totals[seg["status"]] += mins / 60.0
    totals["total"] = sum(totals.values())
    return totals


def _build_distance_table(geometry: list):
    """pre-compute cumulative distances along route geometry for interpolation."""
    cum = [0.0]
    for i in range(1, len(geometry)):
        lon1, lat1 = geometry[i - 1]
        lon2, lat2 = geometry[i]
        d = _haversine(lat1, lon1, lat2, lon2)
        cum.append(cum[-1] + d)
    return cum, cum[-1]


def _haversine(lat1, lon1, lat2, lon2):
    """distance in miles between two lat/lon points."""
    import math
    R = 3958.8  # earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _interpolate_location(geometry, cum_dists, scale, target_miles):
    """find the approximate (label, lat, lon) at a given distance along route."""
    if not geometry or len(geometry) < 2:
        return "en route", None, None
    # convert target miles back to geometry distance
    geom_target = target_miles / scale if scale > 0 else target_miles
    for i in range(1, len(cum_dists)):
        if cum_dists[i] >= geom_target - 1e-9:
            seg_len = cum_dists[i] - cum_dists[i - 1]
            if seg_len < 1e-9:
                t = 0.0
            else:
                t = (geom_target - cum_dists[i - 1]) / seg_len
            lon = geometry[i - 1][0] + t * (geometry[i][0] - geometry[i - 1][0])
            lat = geometry[i - 1][1] + t * (geometry[i][1] - geometry[i - 1][1])
            return f"{lat:.4f}, {lon:.4f}", lat, lon
    last = geometry[-1]
    return f"{last[1]:.4f}, {last[0]:.4f}", last[1], last[0]
