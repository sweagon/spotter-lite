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
from django.utils import timezone
from rest_framework.test import APIClient

from .hos_engine import (
    plan_trip,
    slice_into_days,
    compute_daily_totals,
    merge_segments,
)
from .models import Alert, DailyLog, Driver, DutyEvent, Trip, Vehicle
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
        # a trip that isn't yours does not exist: 404 hiding, same as reads
        self.assertEqual(resp.status_code, 404)

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

    def test_debounce_window_blocks_refire(self):
        # breach trip fires, clear the alerts, then run again immediately:
        # the WATCH_HOS_FIRE_MINUTES window must prevent re-firing.
        self._trip()
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        self.assertEqual(Alert.objects.filter(driver=self.driver).count(), 4)
        Alert.objects.update(cleared=True, cleared_at=timezone.now())
        call_command("watch_hos", verbosity=0)
        self.assertEqual(Alert.objects.filter(driver=self.driver).count(), 4)

    def test_debounce_expires_after_window(self):
        self._trip()
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        self.assertEqual(Alert.objects.filter(driver=self.driver).count(), 4)
        Alert.objects.update(cleared=True, cleared_at=timezone.now())
        # move every alert outside the debounce window so it can fire again
        hour_ago = timezone.now() - timedelta(hours=2)
        Alert.objects.update(triggered_at=hour_ago)
        call_command("watch_hos", verbosity=0)
        self.assertGreater(Alert.objects.filter(driver=self.driver).count(), 4)


class AuditorReadOnlyTests(TestCase):
    """the auditor role: full read-only fleet visibility, zero writes."""

    def setUp(self):
        self.client = APIClient()
        self.disp = User.objects.create_user(username="dex", password="pw", role="dispatcher")
        self.auditor = User.objects.create_user(
            username="audit", password="pw", role="auditor"
        )
        self.driver_user = User.objects.create_user(
            username="pat", password="pw", role="driver"
        )
        self.driver = Driver.objects.create(user=self.driver_user)
        self.trip = Trip.objects.create(
            created_by=self.disp,
            driver=self.driver,
            current_location="A",
            pickup_location="A",
            dropoff_location="B",
        )
        self.alert = Alert.objects.create(
            driver=self.driver,
            rule="drive_11",
            detail="projected breach",
            triggered_at=timezone.now(),
        )

    def test_auditor_reads_fleet(self):
        self.client.force_authenticate(self.auditor)
        self.assertEqual(self.client.get("/api/trips/").status_code, 200)
        self.assertEqual(self.client.get("/api/drivers/").status_code, 200)
        self.assertEqual(self.client.get("/api/vehicles/").status_code, 200)
        self.assertEqual(self.client.get("/api/alerts/").status_code, 200)
        resp = self.client.get(f"/api/trips/{self.trip.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_auditor_cannot_mutate(self):
        self.client.force_authenticate(self.auditor)
        # status transition
        self.assertEqual(
            self.client.patch(f"/api/trips/{self.trip.id}/", {"status": "assigned"}, format="json").status_code,
            403,
        )
        # resolve an alert
        self.assertEqual(
            self.client.post(f"/api/alerts/{self.alert.id}/resolve/", {}, format="json").status_code,
            403,
        )
        # create a driver
        self.assertEqual(
            self.client.post("/api/drivers/create/",
                             {"username": "x", "password": "pw"},
                             format="json").status_code,
            403,
        )
        # draft a trip
        self.assertEqual(
            self.client.post("/api/trips/", {
                "current_location": "A", "pickup_location": "A", "dropoff_location": "B",
            }, format="json").status_code,
            403,
        )


class ExportLogsPDFTests(TestCase):
    """the compliance packet endpoint returns a real PDF, role-scoped."""

    def setUp(self):
        self.client = APIClient()
        self.disp = User.objects.create_user(username="dex", password="pw", role="dispatcher")
        self.audit = User.objects.create_user(username="audit", password="pw", role="auditor")
        self.a_user = User.objects.create_user(username="alice", password="pw", role="driver")
        self.b_user = User.objects.create_user(username="bob", password="pw", role="driver")
        self.drive_a = Driver.objects.create(user=self.a_user)
        self.drive_b = Driver.objects.create(user=self.b_user)
        self.trip_a = Trip.objects.create(
            created_by=self.disp, driver=self.drive_a,
            current_location="A", pickup_location="A", dropoff_location="B",
            distance_miles=240, driving_minutes=240,
        )
        DailyLog.objects.create(
            trip=self.trip_a, day_number=1, date="2026-09-01",
            segments=[{"status": "driving", "start_time": "08:00", "end_time": "12:00",
                       "location": "A", "name": "en route"}],
            totals={"driving": 4.0, "off_duty": 8.0,
                    "on_duty_not_driving": 12.0, "sleeper_berth": 0.0},
        )
        self.trip_b = Trip.objects.create(
            created_by=self.disp, driver=self.drive_b,
            current_location="A", pickup_location="A", dropoff_location="C",
        )

    def _export(self, **params):
        return self.client.get("/api/export/logs.pdf", params)

    def test_dispatcher_export_is_pdf(self):
        self.client.force_authenticate(self.disp)
        resp = self._export(driver_id=self.drive_a.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_auditor_can_export(self):
        self.client.force_authenticate(self.audit)
        resp = self._export(driver_id=self.drive_a.id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_driver_exports_only_own_logs(self):
        self.client.force_authenticate(self.a_user)
        # asking for someone else's driver_id is ignored -> returns own only
        resp = self._export(driver_id=self.drive_b.id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_driver_export_with_no_trips_is_404(self):
        self.client.force_authenticate(self.b_user)
        resp = self._export()
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_export_is_401(self):
        resp = self._export()
        self.assertEqual(resp.status_code, 401)


class DutyEventTests(TestCase):
    """the driver's live record of duty status: one open event at a time,
    today's sheet always balances to 24h, role access scoped."""

    def setUp(self):
        self.client = APIClient()
        self.driver_user = User.objects.create_user(
            username="duty", password="pw", role="driver"
        )
        self.driver = Driver.objects.create(user=self.driver_user)
        self.other_user = User.objects.create_user(
            username="other", password="pw", role="driver"
        )
        self.other = Driver.objects.create(user=self.other_user)
        self.disp = User.objects.create_user(
            username="dex", password="pw", role="dispatcher"
        )
        self.audit = User.objects.create_user(
            username="audit", password="pw", role="auditor"
        )

    def _post(self, **body):
        return self.client.post("/api/duty/events/", body, format="json")

    def test_driver_posts_status_change(self):
        self.client.force_authenticate(self.driver_user)
        resp = self._post(status="driving", location="Dallas, TX")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["current"]["status"], "driving")
        self.assertEqual(DutyEvent.objects.filter(ended_at__isnull=True).count(), 1)

    def test_next_change_closes_the_previous(self):
        self.client.force_authenticate(self.driver_user)
        self._post(status="driving", location="Dallas, TX")
        resp = self._post(status="off_duty", location="Houston, TX")
        self.assertEqual(resp.status_code, 201)
        closed = DutyEvent.objects.get(status="driving")
        self.assertIsNotNone(closed.ended_at)
        open_evs = DutyEvent.objects.filter(ended_at__isnull=True)
        self.assertEqual(open_evs.count(), 1)
        self.assertEqual(open_evs.get().status, "off_duty")

    def test_same_status_change_is_400(self):
        self.client.force_authenticate(self.driver_user)
        self._post(status="driving")
        self.assertEqual(self._post(status="driving").status_code, 400)

    def test_invalid_status_is_400(self):
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(self._post(status="tow_plane").status_code, 400)

    def test_non_driver_cannot_post(self):
        self.client.force_authenticate(self.disp)
        self.assertEqual(self._post(status="driving").status_code, 403)
        self.client.force_authenticate(self.audit)
        self.assertEqual(self._post(status="driving").status_code, 403)

    def test_duty_state_segments_balance_to_24(self):
        self.client.force_authenticate(self.driver_user)
        self._post(status="driving", location="Dallas, TX")
        self._post(status="sleeper_berth", location="I-20 rest area")
        resp = self.client.get("/api/duty/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data["segments"]), 3)
        total = sum(resp.data["totals"].values())
        self.assertAlmostEqual(total, 24.0, places=2)

    def test_fleet_or_auditor_can_read_any_driver(self):
        self.client.force_authenticate(self.driver_user)
        self._post(status="driving")
        self.client.force_authenticate(self.audit)
        resp = self.client.get(f"/api/duty/?driver_id={self.driver.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["current"]["status"], "driving")
        self.client.force_authenticate(self.disp)
        self.assertEqual(
            self.client.get(f"/api/duty/?driver_id={self.driver.id}").status_code, 200
        )

    def test_driver_state_is_scoped_to_self(self):
        self.client.force_authenticate(self.other_user)
        resp = self.client.get(f"/api/duty/?driver_id={self.driver.id}")
        # non-fleet driver_id is ignored: they get their own (empty) state
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["driver_id"], self.other.id)

    def test_me_includes_duty(self):
        self.client.force_authenticate(self.driver_user)
        self._post(status="off_duty")
        resp = self.client.get("/api/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["duty"]["current"]["status"], "off_duty")

    def test_trip_must_belong_to_driver(self):
        trip = Trip.objects.create(
            created_by=self.disp, driver=self.other, current_location="A",
            pickup_location="A", dropoff_location="B",
        )
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(
            self._post(status="driving", trip_id=trip.id).status_code, 400
        )


class DriverSelfPatchTests(TestCase):
    """a driver can advance their own load's status but never reassign."""

    def setUp(self):
        self.client = APIClient()
        self.driver_user = User.objects.create_user(
            username="pat", password="pw", role="driver"
        )
        self.driver = Driver.objects.create(user=self.driver_user)
        self.other_user = User.objects.create_user(
            username="bob", password="pw", role="driver"
        )
        self.other = Driver.objects.create(user=self.other_user)
        self.disp = User.objects.create_user(
            username="dex", password="pw", role="dispatcher"
        )
        self.audit = User.objects.create_user(
            username="audit", password="pw", role="auditor"
        )

    def _trip(self, driver=None, status="assigned"):
        return Trip.objects.create(
            created_by=self.disp,
            driver=driver or self.driver,
            current_location="A", pickup_location="A", dropoff_location="B",
            status=status,
        )

    def test_driver_starts_own_trip(self):
        trip = self._trip()
        self.client.force_authenticate(self.driver_user)
        resp = self.client.patch(f"/api/trips/{trip.id}/", {"status": "en_route"}, format="json")
        self.assertEqual(resp.status_code, 200)
        trip.refresh_from_db()
        self.assertEqual(trip.status, "en_route")
        event = trip.events.first()
        self.assertEqual(event.user_id, self.driver_user.id)
        self.assertEqual(event.to_status, "en_route")

    def test_driver_cannot_reassign(self):
        trip = self._trip()
        self.client.force_authenticate(self.driver_user)
        resp = self.client.patch(
            f"/api/trips/{trip.id}/", {"driver_id": self.other.id}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_driver_cannot_jump_out_of_order(self):
        trip = self._trip()
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(
            self.client.patch(f"/api/trips/{trip.id}/", {"status": "delivered"}, format="json").status_code,
            400,
        )

    def test_driver_cannot_touch_others_trip(self):
        trip = self._trip(driver=self.other)
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(
            self.client.patch(f"/api/trips/{trip.id}/", {"status": "en_route"}, format="json").status_code,
            404,
        )

    def test_auditor_still_cannot_patch(self):
        trip = self._trip()
        self.client.force_authenticate(self.audit)
        self.assertEqual(
            self.client.patch(f"/api/trips/{trip.id}/", {"status": "en_route"}, format="json").status_code,
            403,
        )


class WatchdogActualHoursTests(TestCase):
    """self-declared driving today counts toward the guardrail projection."""

    def setUp(self):
        self.driver_user = User.objects.create_user(
            username="ron", password="pw", role="driver"
        )
        self.driver = Driver.objects.create(
            user=self.driver_user, cycle_used=0.0
        )
        self.disp = User.objects.create_user(
            username="dex", password="pw", role="dispatcher"
        )

    def _drove(self, hours=6.0):
        now = timezone.now()
        DutyEvent.objects.create(
            driver=self.driver, status="driving",
            started_at=now - timedelta(hours=hours),
            ended_at=now - timedelta(hours=1),
        )

    def _trip(self, driving=6.0):
        return Trip.objects.create(
            created_by=self.disp,
            driver=self.driver,
            current_location="A", pickup_location="A", dropoff_location="B",
            status="en_route",
            usage={"driving_hours": driving, "window_hours": driving + 2,
                   "cycle_hours": driving},
            cycle_used_planned=0.0,
            distance_miles=500, driving_minutes=600,
        )

    def test_actual_driving_pushes_over_11(self):
        # 6h already driven today + a fresh 6h plan = 12h -> drive_11 fires.
        self._drove(6.0)
        self._trip(6.0)
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        rules = set(Alert.objects.filter(driver=self.driver).values_list("rule", flat=True))
        self.assertIn("drive_11", rules)

    def test_no_actual_driving_stays_under(self):
        # plan only: 6h drive, no actual hours -> no drive_11 alert.
        self._trip(6.0)
        from django.core.management import call_command
        call_command("watch_hos", verbosity=0)
        rules = set(Alert.objects.filter(driver=self.driver).values_list("rule", flat=True))
        self.assertNotIn("drive_11", rules)


class AdminCrudTests(TestCase):
    """SPA admin console: drivers + vehicles CRUD, admin-scoped."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="sasha", password="pw", role="admin"
        )
        self.disp = User.objects.create_user(
            username="dex", password="pw", role="dispatcher"
        )
        self.audit = User.objects.create_user(
            username="audit", password="pw", role="auditor"
        )
        self.driver_user = User.objects.create_user(
            username="dora", password="pw", role="driver",
            first_name="Dora", last_name="Anton",
        )
        self.driver = Driver.objects.create(
            user=self.driver_user, cycle_used=42.5
        )
        self.v1 = Vehicle.objects.create(unit_no="V-1", vehicle_type="sleeper")
        self.v2 = Vehicle.objects.create(unit_no="V-2", vehicle_type="daycab")

    def test_admin_creates_vehicle(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post("/api/vehicles/", {
            "unit_no": "V-9", "vehicle_type": "reefer", "current_odometer": 120000,
        }, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["unit_no"], "V-9")

    def test_dispatcher_cannot_create_vehicle(self):
        self.client.force_authenticate(self.disp)
        resp = self.client.post("/api/vehicles/", {"unit_no": "V-9"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_admin_patches_vehicle(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(f"/api/vehicles/{self.v1.id}/",
                                 {"vin": "1HGCM82633A", "active": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.vin, "1HGCM82633A")
        self.assertFalse(self.v1.active)

    def test_admin_patches_driver(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(f"/api/drivers/{self.driver.id}/", {
            "first_name": "Dora", "last_name": "Anton-2",
            "vehicle_id": self.v2.id, "cycle_used": 10,
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.driver.refresh_from_db()
        self.driver_user.refresh_from_db()
        self.assertEqual(self.driver.vehicle_id, self.v2.id)
        self.assertEqual(self.driver.cycle_used, 10)
        self.assertEqual(self.driver_user.last_name, "Anton-2")

    def test_auditor_cannot_patch_driver(self):
        self.client.force_authenticate(self.audit)
        resp = self.client.patch(f"/api/drivers/{self.driver.id}/",
                                 {"cycle_used": 5}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_admin_cannot_assign_occupied_vehicle(self):
        other = Driver.objects.create(user=User.objects.create_user(
            username="bob", password="pw", role="driver"))
        other.vehicle = self.v2
        other.save()
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(f"/api/drivers/{self.driver.id}/",
                                 {"vehicle_id": self.v2.id}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_admin_cannot_demote_self(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(f"/api/drivers/{self.driver.id}/", {"role": "dispatcher"}, format="json")
        self.assertEqual(resp.status_code, 200)
        # now self-demote attempt on own profile (admin has no driver profile,
        # so create one first)
        admin_profile = Driver.objects.create(user=self.admin)
        resp = self.client.patch(f"/api/drivers/{admin_profile.id}/", {"role": "driver"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_reset_cycle_sets_zero_and_timestamp(self):
        self.client.force_authenticate(self.disp)
        resp = self.client.post(f"/api/drivers/{self.driver.id}/reset-cycle/", {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.cycle_used, 0.0)
        self.assertIsNotNone(self.driver.last_cycle_reset)

    def test_auditor_cannot_reset_cycle(self):
        self.client.force_authenticate(self.audit)
        resp = self.client.post(f"/api/drivers/{self.driver.id}/reset-cycle/", {}, format="json")
        self.assertEqual(resp.status_code, 403)
