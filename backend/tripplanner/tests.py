"""
tests for the hos engine. these verify the 49 cfr rules we claim to
implement, not just that the code runs.

run with:  python manage.py test tripplanner -v 2
(no network needed — we use synthetic route data)
"""

from datetime import datetime, timedelta

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .hos_engine import (
    plan_trip,
    slice_into_days,
    compute_daily_totals,
    merge_segments,
)
from .models import Alert, DailyLog, Driver, Trip, Vehicle
from .routing import _normalize_highways
from .views import _stop_type

User = get_user_model()


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


class NewApiFeaturesTests(TestCase):
    """the fields the redesigned frontend depends on: usage peaks, highway
    labels, stop types, and the geocode autocomplete endpoint."""

    def test_usage_peaks_recorded(self):
        stats = {}
        plan_trip(
            pickup_location={"name": "LA"},
            dropoff_location={"name": "NYC"},
            current_cycle_used=60,
            route_distance_miles=2800,
            route_driving_minutes=2520,
            route_geometry=[[-118.24, 34.05], [-100.0, 36.0], [-74.0, 40.7]],
            start_time=datetime(2026, 1, 5, 8, 0, 0),
            stats=stats,
        )
        # driving hits the 11hr cap exactly before a 10hr rest resets it
        self.assertAlmostEqual(stats["driving_hours"], 11.0, places=1)
        # window ends a shift via either the 14-hr cap or (more often here)
        # the 11-hr driving cap plus break/fuel time — so it must be tight,
        # over 10, and never past 14.
        self.assertGreater(stats["window_hours"], 10.0)
        self.assertLessEqual(stats["window_hours"], 14.0 + 1e-6)
        self.assertGreaterEqual(stats["cycle_hours"], 60.0)
        self.assertLessEqual(stats["cycle_hours"], 70.0)

    def test_highways_normalization(self):
        # raw osrm step names -> display labels; junk is dropped
        names = ["Interstate 55", "I-55", "US Highway 50", "Route 66",
                 "", "Unknown Road", "State Highway 400"]
        out = _normalize_highways(names)
        self.assertEqual(out, ["I-55", "US-50", "Route 66"])
        self.assertEqual(_normalize_highways(["", "local street", None]), [])

    def test_stop_type_classification(self):
        # synthetic segment list mimicking a real trip's non-driving spots
        t0 = datetime(2026, 1, 5, 6, 0, 0)
        segs = [
            {"status": "on_duty_not_driving", "name": "LA",                 "start_time": t0,            "end_time": t0 + timedelta(hours=1)},
            {"status": "driving",            "name": "en route",            "start_time": t0 + timedelta(hours=1), "end_time": t0 + timedelta(hours=9)},
            {"status": "off_duty",           "name": "37.7, -112.9",        "start_time": t0 + timedelta(hours=9),  "end_time": t0 + timedelta(hours=9.5)},
            {"status": "on_duty_not_driving","name": "Fuel stop ~1000 mi",  "start_time": t0 + timedelta(hours=20), "end_time": t0 + timedelta(hours=20.67)},
            {"status": "sleeper_berth",      "name": "40.3, -103.3",        "start_time": t0 + timedelta(hours=30), "end_time": t0 + timedelta(hours=40)},
            {"status": "sleeper_berth",      "name": "38.4, -112.6",        "start_time": t0 + timedelta(hours=40), "end_time": t0 + timedelta(hours=74)},
            {"status": "on_duty_not_driving","name": "NYC",                 "start_time": t0 + timedelta(hours=90), "end_time": t0 + timedelta(hours=91)},
        ]
        types = [_stop_type(s, i, segs) for i, s in enumerate(segs)]
        # only non-driving segments get classified, but we index all for clarity
        self.assertEqual(types[0], "pickup")
        self.assertEqual(types[2], "break")
        self.assertEqual(types[3], "fuel")
        self.assertEqual(types[4], "rest")
        self.assertEqual(types[5], "restart")
        self.assertEqual(types[6], "dropoff")

    def test_suggest_requires_three_chars(self):
        # no network call here: <3 chars returns immediately with no results
        resp = APIClient().get("/api/geocode/suggest/?q=ab")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])


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

class OrgAuthTests(TestCase):
    """the org layer is built on real auth: users, tokens, role-gated access."""

    def setUp(self):
        self.client = APIClient()
        self.driver_user = User.objects.create_user(
            username="dave", password="pw", role="driver"
        )
        self.disp_user = User.objects.create_user(
            username="dana", password="pw", role="dispatcher"
        )
        self.vehicle = Vehicle.objects.create(unit_no="U-1", vehicle_type="sleeper")
        self.driver = Driver.objects.create(user=self.driver_user, vehicle=self.vehicle)

    def test_login_returns_tokens_and_user_role(self):
        resp = self.client.post("/api/auth/login/", {
            "username": "dana", "password": "pw",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertEqual(resp.data["user"]["role"], "Dispatcher")

    def test_login_rejects_bad_password(self):
        resp = self.client.post("/api/auth/login/", {
            "username": "dana", "password": "nope",
        }, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_health_with_db_ping(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["database"], "ok")

    def test_me_includes_driver_profile_and_alerts(self):
        self.client.force_authenticate(self.driver_user)
        resp = self.client.get("/api/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "Driver")
        self.assertEqual(resp.data["driver"]["id"], self.driver.id)
        self.assertEqual(resp.data["driver"]["vehicle_unit"], "U-1")

    def test_me_requires_auth(self):
        resp = self.client.get("/api/me/")
        self.assertEqual(resp.status_code, 401)

    def test_logout_blacklists_refresh(self):
        login = self.client.post("/api/auth/login/", {
            "username": "dana", "password": "pw",
        }, format="json")
        refresh = login.data["refresh"]
        out = self.client.post(
            "/api/auth/logout/",
            {"refresh": refresh},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
        )
        self.assertEqual(out.status_code, 200)
        re_use = self.client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(re_use.status_code, 401)


class OrgPermissionsTests(TestCase):
    """role gates: drivers manage nothing but their own trips."""

    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user(username="alice", password="pw", role="driver")
        self.bob = User.objects.create_user(username="bob", password="pw", role="driver")
        self.disp = User.objects.create_user(username="dex", password="pw", role="dispatcher")
        self.drive_a = Driver.objects.create(user=self.alice)
        self.drive_b = Driver.objects.create(user=self.bob)
        self.trip_a = Trip.objects.create(
            created_by=self.disp,
            driver=self.drive_a,
            pickup_location="Memphis, TN",
            dropoff_location="Chicago, IL",
            current_location="Memphis, TN",
        )
        self.trip_b = Trip.objects.create(
            created_by=self.disp,
            driver=self.drive_b,
            pickup_location="Dallas, TX",
            dropoff_location="Houston, TX",
            current_location="Dallas, TX",
        )

    def test_driver_sees_only_own_trips(self):
        self.client.force_authenticate(self.alice)
        resp = self.client.get("/api/trips/")
        self.assertEqual(resp.status_code, 200)
        ids = [t["id"] for t in resp.data]
        self.assertEqual(ids, [self.trip_a.id])
        self.assertNotIn(self.trip_b.id, ids)

    def test_driver_cannot_read_other_drivers_trip(self):
        self.client.force_authenticate(self.alice)
        resp = self.client.get(f"/api/trips/{self.trip_b.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_driver_cannot_patch_other_trip(self):
        self.client.force_authenticate(self.alice)
        resp = self.client.patch(
            f"/api/trips/{self.trip_b.id}/",
            {"status": "en_route"},
            format="json",
        )
        # writes are dispatcher-only; drivers get a hard 403 regardless of which trip
        self.assertEqual(resp.status_code, 403)

    def test_driver_cannot_list_fleet(self):
        self.client.force_authenticate(self.alice)
        for path in ("/api/drivers/", "/api/vehicles/", "/api/vehicles/"):
            resp = self.client.get(path)
            self.assertIn(resp.status_code, (401, 403))

    def test_dispatcher_sees_all_trips(self):
        self.client.force_authenticate(self.disp)
        resp = self.client.get("/api/trips/")
        self.assertEqual(len(resp.data), 2)

    def test_status_transitions_are_guarded(self):
        self.client.force_authenticate(self.disp)
        # draft -> delivered is an impossible jump
        bad = self.client.patch(
            f"/api/trips/{self.trip_a.id}/",
            {"status": "delivered"},
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        # and the legal path works
        r1 = self.client.patch(f"/api/trips/{self.trip_a.id}/", {"status": "assigned"}, format="json")
        r2 = self.client.patch(f"/api/trips/{self.trip_a.id}/", {"status": "en_route"}, format="json")
        r3 = self.client.patch(f"/api/trips/{self.trip_a.id}/", {"status": "delivered"}, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.data["status"], "delivered")


class TripPlanPersistTests(TestCase):
    """POST /api/trips/plan/ persists a Trip + daily logs without network."""

    def setUp(self):
        self.client = APIClient()
        self.disp = User.objects.create_user(username="dex", password="pw", role="dispatcher")
        self.vehicle = Vehicle.objects.create(unit_no="U-2")
        self.driver = Driver.objects.create(user=self.disp, vehicle=self.vehicle)
        self.driver.user = User.objects.create_user(
            username="pat", password="pw", role="driver"
        )
        self.driver.save()

        self.fake_payload = {
            "route": {
                "distance_miles": 240.0,
                "driving_minutes": 240.0,
                "geometry": [[-96.8, 32.8], [-95.4, 29.8]],
                "highways": ["I-45"],
            },
            "usage": {"driving_hours": 4.0, "window_hours": 6.0, "cycle_hours": 4.0},
            "stops": [],
            "daily_logs": [
                {
                    "date": "Mon Jan 05, 2026",
                    "date_iso": "2026-01-05",
                    "segments": [],
                    "totals": {"driving": 4.0, "off_duty": 8.0, "on_duty_not_driving": 12.0, "sleeper_berth": 0.0},
                }
            ],
        }

    def test_plan_creates_trip_and_logs(self):
        self.client.force_authenticate(self.disp)
        with mock.patch("tripplanner.views.compute_plan", return_value=self.fake_payload):
            resp = self.client.post("/api/trips/plan/", {
                "current_location": "Dallas, TX",
                "pickup_location": "Dallas, TX",
                "dropoff_location": "Houston, TX",
                "current_cycle_used": 30,
                "driver_id": self.driver.id,
                "vehicle_id": self.vehicle.id,
            }, format="json")
        self.assertEqual(resp.status_code, 201)
        trip_id = resp.data["trip"]["id"]
        self.assertEqual(resp.data["trip"]["status"], "assigned")
        trip = Trip.objects.get(pk=trip_id)
        self.assertEqual(trip.driver_id, self.driver.id)
        self.assertEqual(trip.cycle_used_planned, 30)
        self.assertEqual(DailyLog.objects.filter(trip=trip).count(), 1)
        self.assertEqual(DailyLog.objects.get(trip=trip).date.isoformat(), "2026-01-05")

    def test_plan_requires_auth(self):
        resp = self.client.post("/api/trips/plan/", {
            "current_location": "Dallas, TX",
            "pickup_location": "Dallas, TX",
            "dropoff_location": "Houston, TX",
            "current_cycle_used": 30,
        }, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_driver_plans_own_draft(self):
        self.client.force_authenticate(self.driver.user)
        with mock.patch("tripplanner.views.compute_plan", return_value=self.fake_payload):
            resp = self.client.post("/api/trips/plan/", {
                "current_location": "Dallas, TX",
                "pickup_location": "Dallas, TX",
                "dropoff_location": "Houston, TX",
                "current_cycle_used": 12,
            }, format="json")
        self.assertEqual(resp.status_code, 201)
        trip = Trip.objects.get(pk=resp.data["trip"]["id"])
        self.assertEqual(trip.status, "draft")  # dispatcher must approve
        self.assertEqual(trip.driver_id, self.driver.id)
        self.assertEqual(trip.vehicle_id, self.vehicle.id)

    def test_driver_cannot_assign_another_vehicle(self):
        other = Vehicle.objects.create(unit_no="U-9")
        self.client.force_authenticate(self.driver.user)
        with mock.patch("tripplanner.views.compute_plan", return_value=self.fake_payload):
            resp = self.client.post("/api/trips/plan/", {
                "current_location": "Dallas, TX",
                "pickup_location": "Dallas, TX",
                "dropoff_location": "Houston, TX",
                "current_cycle_used": 12,
                "vehicle_id": other.id,
            }, format="json")
        self.assertEqual(resp.status_code, 403)


class WatchdogTests(TestCase):
    """the HOS tracker agent: plans become alerts at the right thresholds."""

    def setUp(self):
        self.driver_user = User.objects.create_user(
            username="ron", password="pw", role="driver"
        )
        self.driver = Driver.objects.create(
            user=self.driver_user, cycle_used=60.0
        )
        self.disp = User.objects.create_user(
            username="dex", password="pw", role="dispatcher"
        )

    def _trip(self, status="en_route", driving=12.0, window=15.0, cycle=76.0):
        return Trip.objects.create(
            created_by=self.disp,
            driver=self.driver,
            current_location="A",
            pickup_location="A",
            dropoff_location="B",
            status=status,
            usage={
                "driving_hours": driving,
                "window_hours": window,
                "cycle_hours": cycle,
            },
            cycle_used_planned=60.0,
            distance_miles=500,
            driving_minutes=600,
        )

    def test_breached_plan_raises_alerts(self):
        self._trip()
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        rules = set(Alert.objects.filter(driver=self.driver).values_list("rule", flat=True))
        self.assertIn("drive_11", rules)
        self.assertIn("duty_14", rules)
        self.assertIn("cycle_70", rules)

    def test_idempotent_across_runs(self):
        # breach trip fires 4 rules (drive_11, duty_14, cycle_70, over_hours)
        self._trip()
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        call_command("watch_hos", verbosity=0)
        self.assertEqual(Alert.objects.filter(driver=self.driver).count(), 4)

    def test_clean_driver_no_alerts(self):
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        self.assertEqual(Alert.objects.filter(driver=self.driver).count(), 0)

    def test_delivered_trip_not_flagged(self):
        # a finished load is history, not a live projection
        self._trip(status="delivered")
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        self.assertEqual(Alert.objects.filter(driver=self.driver).count(), 0)

    def test_tripevent_audit_recorded(self):
        self.client = APIClient()
        self.client.force_authenticate(self.disp)
        trip = Trip.objects.create(
            created_by=self.disp,
            driver=self.driver,
            current_location="A",
            pickup_location="A",
            dropoff_location="B",
        )
        resp = self.client.patch(f"/api/trips/{trip.id}/", {"status": "assigned"}, format="json")
        self.assertEqual(resp.status_code, 200)
        event = trip.events.first()
        self.assertEqual(event.to_status, "assigned")
        self.assertEqual(event.user_id, self.disp.id)
