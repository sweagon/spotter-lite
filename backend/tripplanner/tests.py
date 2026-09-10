"""
tests for the hos engine. these verify the 49 cfr rules we claim to
implement, not just that the code runs.

run with:  python manage.py test tripplanner -v 2
(no network needed — we use synthetic route data)
"""

from datetime import datetime, timedelta

from django.test import TestCase

from .hos_engine import (
    plan_trip,
    slice_into_days,
    compute_daily_totals,
    merge_segments,
)


class ShortTripTests(TestCase):
    """a 4-hour drive should be trivial: pickup, drive, dropoff, done."""

    def setUp(self):
        self.segments = plan_trip(
            pickup_location={"name": "Dallas, TX"},
            dropoff_location={"name": "Houston, TX"},
            current_cycle_used=30,
            route_distance_miles=240,
            route_driving_minutes=240,
            route_geometry=[[-96.797, 32.7767], [-95.3698, 29.7604]],
            start_time=datetime(2026, 1, 5, 6, 0, 0),
        )
        self.merged = merge_segments(self.segments)

    def test_pickup_and_dropoff_are_on_duty(self):
        self.assertEqual(self.merged[0]["status"], "on_duty_not_driving")
        self.assertEqual(self.merged[-1]["status"], "on_duty_not_driving")
        self.assertEqual(self.merged[0]["location"], "Dallas, TX")
        self.assertEqual(self.merged[-1]["location"], "Houston, TX")

    def test_pickup_and_dropoff_are_one_hour_each(self):
        first = (self.merged[0]["end_time"] - self.merged[0]["start_time"]).total_seconds() / 3600
        last = (self.merged[-1]["end_time"] - self.merged[-1]["start_time"]).total_seconds() / 3600
        self.assertAlmostEqual(first, 1.0)
        self.assertAlmostEqual(last, 1.0)

    def test_driving_total_matches_route(self):
        drive_mins = sum(
            (s["end_time"] - s["start_time"]).total_seconds()
            for s in self.merged if s["status"] == "driving"
        ) / 60.0
        self.assertAlmostEqual(drive_mins, 240, places=0)

    def test_no_stops_required_for_short_trip(self):
        statuses = [s["status"] for s in self.merged]
        # exactly: on_duty, driving, on_duty
        self.assertEqual(statuses, ["on_duty_not_driving", "driving", "on_duty_not_driving"])

    def test_every_day_sums_to_24(self):
        for _, day_segs in slice_into_days(self.segments):
            totals = compute_daily_totals(day_segs)
            self.assertAlmostEqual(totals["total"], 24.0, places=5)


class BreakAndRestTests(TestCase):
    """forced 30-min break after 8hr, 10hr rest after 11hr driving / 14hr window."""

    def _trip(self, miles, minutes, cycle=30, start_hour=6):
        return merge_segments(plan_trip(
            pickup_location={"name": "Origin"},
            dropoff_location={"name": "Destination"},
            current_cycle_used=cycle,
            route_distance_miles=miles,
            route_driving_minutes=minutes,
            route_geometry=[[-120, 35], [-75, 40]],
            start_time=datetime(2026, 1, 5, start_hour, 0, 0),
        ))

    def test_30min_break_after_8hrs_driving(self):
        # 14hrs of driving at 66mph ~ 930 miles
        segs = self._trip(930, 840)
        breaks = [s for s in segs if s["status"] == "off_duty"]
        self.assertEqual(len(breaks), 1, "should be exactly one 30-min break")
        brk = breaks[0]
        mins = (brk["end_time"] - brk["start_time"]).total_seconds() / 60
        self.assertEqual(mins, 30)
        # break should land right at the 8hr mark of driving
        drive_before = sum(
            (s["end_time"] - s["start_time"]).total_seconds() / 3600
            for s in segs if s["status"] == "driving" and s["end_time"] <= brk["start_time"]
        )
        self.assertAlmostEqual(drive_before, 8.0, places=2)

    def test_never_more_than_11_hours_driving_in_a_shift(self):
        # very long single haul: 2500 miles, 38hrs of driving
        segs = self._trip(2500, 2280)
        # split driving into contiguous shifts, each shift must be <= 11hrs
        shifts, cur = [], 0.0
        for s in segs:
            hrs = (s["end_time"] - s["start_time"]).total_seconds() / 3600
            if s["status"] == "driving":
                cur += hrs
            elif s["status"] == "sleeper_berth":
                shifts.append(cur)
                cur = 0.0
        shifts.append(cur)
        for sh in shifts:
            self.assertLessEqual(sh, 11.0 + 1e-6)

    def test_rest_is_10_hours_after_11hr_drive(self):
        segs = self._trip(2500, 2280)
        rests = [s for s in segs
                 if s["status"] == "sleeper_berth"
                 and (s["end_time"] - s["start_time"]).total_seconds() / 3600 > 10 - 1e-6]
        # a 10hr rest or 34hr restart must exist (trip can't be one shift)
        self.assertTrue(rests)


class CycleAndRestartTests(TestCase):
    """70hr cap and the 34hr restart."""

    def test_restart_when_cycle_would_blow_past_70(self):
        segs = plan_trip(
            pickup_location={"name": "LA"},
            dropoff_location={"name": "NYC"},
            current_cycle_used=60,
            route_distance_miles=2800,
            route_driving_minutes=2520,
            route_geometry=[[-118.24, 34.05], [-100.0, 36.0], [-74.0, 40.7]],
            start_time=datetime(2026, 1, 5, 8, 0, 0),
        )
        # must contain a 34-hour+ sleeper block (the restart)
        restarts = [s for s in segs
                    if s["status"] == "sleeper_berth"
                    and (s["end_time"] - s["start_time"]).total_seconds() / 3600 >= 34 - 1e-6]
        self.assertEqual(len(restarts), 1)
        self.assertAlmostEqual(
            (restarts[0]["end_time"] - restarts[0]["start_time"]).total_seconds() / 3600,
            34.0, places=3)

    def test_no_restart_when_cycle_has_room(self):
        segs = plan_trip(
            pickup_location={"name": "LA"},
            dropoff_location={"name": "NYC"},
            current_cycle_used=10,  # lots of room
            route_distance_miles=2800,
            route_driving_minutes=2520,
            route_geometry=[[-118.24, 34.05], [-100.0, 36.0], [-74.0, 40.7]],
            start_time=datetime(2026, 1, 5, 8, 0, 0),
        )
        restarts = [s for s in segs
                    if s["status"] == "sleeper_berth"
                    and (s["end_time"] - s["start_time"]).total_seconds() / 3600 >= 34 - 1e-6]
        self.assertEqual(restarts, [])

    def test_fuel_stops_every_1000_miles(self):
        segs = plan_trip(
            pickup_location={"name": "LA"},
            dropoff_location={"name": "NYC"},
            current_cycle_used=10,
            route_distance_miles=2800,
            route_driving_minutes=2520,
            route_geometry=[[-118.24, 34.05], [-100.0, 36.0], [-74.0, 40.7]],
            start_time=datetime(2026, 1, 5, 8, 0, 0),
        )
        # fuel shows up as on-duty-not-driving blocks mid-route (not the endpoints)
        internal_onduty = [s for s in segs
                           if s["status"] == "on_duty_not_driving"
                           and s["location"] not in ("LA", "NYC")]
        # 2800 miles should trigger fuel at ~1000 and ~2000 = 2 stops
        self.assertEqual(len(internal_onduty), 2,
                         "expected 2 fuel stops for a 2800mi haul")
        for s in internal_onduty:
            mins = (s["end_time"] - s["start_time"]).total_seconds() / 60
            self.assertEqual(mins, 40)


class DaySlicingTests(TestCase):
    def test_segment_spanning_midnight_gets_split(self):
        segs = [
            {"status": "driving", "start_time": datetime(2026, 1, 5, 23, 0),
             "end_time": datetime(2026, 1, 6, 1, 0), "location": "en route",
             "distance": 50.0},
        ]
        days = slice_into_days(segs)
        self.assertEqual(len(days), 2)
        day1_parts = [s for _, d in days for s in d
                      if s["start_time"].date() == datetime(2026, 1, 5).date()
                      and s["status"] == "driving"]
        day2_parts = [s for _, d in days for s in d
                      if s["start_time"].date() == datetime(2026, 1, 6).date()
                      and s["status"] == "driving"]
        self.assertEqual(len(day1_parts), 1)
        self.assertEqual(len(day2_parts), 1)
        # 23:00-24:00 on day1, then 00:00-01:00 on day2
        self.assertEqual(day1_parts[0]["end_time"].hour, 0)
        self.assertEqual(day2_parts[0]["start_time"].hour, 0)