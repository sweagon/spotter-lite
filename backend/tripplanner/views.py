from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Alert, DailyLog, Driver, Trip, TripEvent, Vehicle
from .permissions import IsDispatcher
from .routing import geocode, get_route, suggest
from .hos_engine import plan_trip, slice_into_days, compute_daily_totals
from .serializers import (
    AlertSerializer,
    DriverSerializer,
    TripPlanRequestSerializer,
    TripSerializer,
    UserSummarySerializer,
    VehicleSerializer,
)

User = get_user_model()


class HealthView(APIView):
    """GET /api/health/ - liveness, plus a DB ping so Render knows the
    backend is actually able to serve requests, not just boots."""

    permission_classes = [AllowAny]

    def get(self, request):
        try:
            from django.db import connection

            connection.ensure_connection()
        except Exception:
            return Response({"status": "error", "database": "unreachable"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"status": "ok", "database": "ok"})


class SuggestView(APIView):
    """
    GET /api/geocode/suggest/?q=... - geocoder autocomplete.

    feeds the form's "typeahead" so a dispatcher can tab through real place
    names instead of gambling on spellings. frontend debounces the calls.
    """

    permission_classes = [AllowAny]
    throttle_scope = "suggest"

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 3:
            return Response([])
        try:
            return Response(suggest(q))
        except Exception:
            # autocomplete is a nicety; never let it break the page
            return Response([])


class RoutingUnavailable(Exception):
    """routing provider is down — map to 503, not a user error."""


def compute_plan(data):
    """shared planner core: geocode + route + HOS sim -> the full response
    payload. used by the public calculator and the authenticated persist path.
    raises ValueError for user-facing errors, RoutingUnavailable for 503s."""
    current_loc = geocode(data["current_location"])
    pickup_loc = geocode(data["pickup_location"])
    dropoff_loc = geocode(data["dropoff_location"])

    try:
        route = get_route(pickup_loc, dropoff_loc)
    except ValueError as e:
        raise ValueError(f"Routing failed: {e}")
    except Exception as e:
        raise RoutingUnavailable(f"Routing service unavailable: {e}")

    stats = {}
    trip_segments = plan_trip(
        pickup_location=pickup_loc,
        dropoff_location=dropoff_loc,
        current_cycle_used=data["current_cycle_used"],
        route_distance_miles=route["distance_miles"],
        route_driving_minutes=route["driving_minutes"],
        route_geometry=route["geometry"],
        # the engine is naive-datetime throughout (matches its defaults);
        # strip tz so we never mix aware and naive in the sim.
        start_time=timezone.localtime().replace(tzinfo=None, second=0, microsecond=0),
        stats=stats,
    )

    days = slice_into_days(trip_segments)
    daily_logs = []
    for day_start, day_segs in days:
        totals = compute_daily_totals(day_segs)
        daily_logs.append({
            "date": day_start.strftime("%a %b %d, %Y"),
            "date_iso": day_start.date().isoformat(),
            "segments": [
                {
                    "status": seg["status"],
                    "start_time": seg["start_time"].strftime("%H:%M"),
                    "end_time": seg["end_time"].strftime("%H:%M"),
                    "start_hour": (seg["start_time"] - day_start).total_seconds() / 3600,
                    "end_hour": (seg["end_time"] - day_start).total_seconds() / 3600,
                    "location": seg["location"],
                    "name": seg.get("name", seg["location"]),
                }
                for seg in day_segs
            ],
            "totals": {k: round(v, 2) for k, v in totals.items()},
        })

    stops = _extract_stops(trip_segments)

    return {
        "route": {
            "distance_miles": round(route["distance_miles"], 1),
            "driving_minutes": round(route["driving_minutes"], 1),
            "geometry": route["geometry"],
            "highways": route.get("highways", []),
        },
        "usage": stats,
        "stops": stops,
        "daily_logs": daily_logs,
    }


class TripPlanView(APIView):
    """
    POST /api/trip/plan/ - public, stateless planner.

    the plain calculator used on the open demo: takes the three locations
    + cycle balance, returns route + logs, persistence-free.
    """

    permission_classes = [AllowAny]
    throttle_scope = "plan"

    def post(self, request):
        serializer = TripPlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = compute_plan(serializer.validated_data)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingUnavailable as e:
            return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(payload)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

class _LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSummarySerializer(self.user).data
        return data


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/ - username/password -> tokens + the user, so
    the SPA can route by role without a second round-trip."""

    permission_classes = [AllowAny]
    serializer_class = _LoginSerializer


class LogoutView(APIView):
    """POST /api/auth/logout/ {refresh} - blacklist the refresh token."""

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"error": "refresh token required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response(
                {"error": "invalid refresh token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": "logged out"})


class MeView(APIView):
    """GET /api/me/ - current user + (for drivers) their fleet profile +
    open alerts. what the SPA needs to paint the right home screen."""

    def get(self, request):
        data = UserSummarySerializer(request.user).data
        profile = getattr(request.user, "driver_profile", None)
        if profile:
            data["driver"] = {
                "id": profile.id,
                "vehicle_id": profile.vehicle_id,
                "vehicle_unit": profile.vehicle.unit_no if profile.vehicle_id else None,
                "cycle_used": profile.cycle_used,
                "cdl_number": profile.cdl_number,
            }
            data["alerts"] = AlertSerializer(
                profile.alerts.filter(cleared=False)[:10], many=True
            ).data
        return Response(data)


# ---------------------------------------------------------------------------
# fleet
# ---------------------------------------------------------------------------

class DriverListView(APIView):
    permission_classes = [IsDispatcher]

    def get(self, request):
        qs = Driver.objects.select_related("user", "vehicle").filter(active=True)
        return Response(DriverSerializer(qs, many=True).data)


class DriverDetailView(APIView):
    permission_classes = [IsDispatcher]

    def get(self, request, pk):
        try:
            driver = Driver.objects.select_related("user", "vehicle").get(pk=pk)
        except Driver.DoesNotExist:
            return Response({"error": "no such driver"}, status=status.HTTP_404_NOT_FOUND)
        return Response(DriverSerializer(driver).data)


class VehicleListView(APIView):
    permission_classes = [IsDispatcher]

    def get(self, request):
        qs = Vehicle.objects.filter(active=True)
        return Response(VehicleSerializer(qs, many=True).data)


class CreateDriverView(APIView):
    """POST /api/drivers/ - dispatcher creates a driver login + HOS profile.
    vehicles, passwords and most org rows keep the Django admin for now."""

    permission_classes = [IsDispatcher]

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        first_name = (request.data.get("first_name") or "").strip()
        last_name = (request.data.get("last_name") or "").strip()
        vehicle_id = request.data.get("vehicle_id")
        cycle_used = float(request.data.get("cycle_used") or 0)

        if not username or not password:
            return Response({"error": "username and password are required"},
                            status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=username).exists():
            return Response({"error": "username already taken"},
                            status=status.HTTP_400_BAD_REQUEST)
        vehicle = None
        if vehicle_id:
            try:
                vehicle = Vehicle.objects.get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                return Response({"error": "no such vehicle"},
                                status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role="driver",
        )
        Driver.objects.create(user=user, vehicle=vehicle, cycle_used=cycle_used)
        return Response(DriverSerializer(user.driver_profile).data,
                        status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# trips
# ---------------------------------------------------------------------------

def _visible_queryset(user, pk=None):
    qs = Trip.objects.select_related("driver__user", "vehicle", "created_by")
    if not user.is_dispatcher:
        profile = getattr(user, "driver_profile", None)
        return qs.filter(driver=profile) if profile else qs.none()
    return qs


ALLOWED_TRANSITIONS = {
    "draft": {"assigned", "cancelled"},
    "assigned": {"en_route", "cancelled"},
    "en_route": {"stopped", "delivered"},
    "stopped": {"en_route", "delivered"},
    "delivered": set(),
    "cancelled": set(),
}


class TripListView(APIView):
    """GET /api/trips/?status=&driver= - fleet trip board.
    drivers see only their own; only dispatchers create trips."""

    def get(self, request):
        qs = _visible_queryset(request.user)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        driver = request.query_params.get("driver")
        if driver:
            qs = qs.filter(driver__user__username=driver)
        return Response(TripSerializer(qs, many=True).data)

    def post(self, request):
        """create a draft trip from locations alone (planned later)."""
        if not request.user.is_dispatcher:
            return Response({"error": "dispatchers only"},
                            status=status.HTTP_403_FORBIDDEN)
        locs = {k: (request.data.get(k) or "").strip()
                for k in ("current_location", "pickup_location", "dropoff_location")}
        if not all(locs.values()):
            return Response({"error": "all three locations are required"},
                            status=status.HTTP_400_BAD_REQUEST)
        trip = Trip(created_by=request.user, **locs)
        trip.save()
        return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)


class TripDetailView(APIView):
    def get(self, request, pk):
        try:
            trip = Trip.objects.select_related("driver__user", "vehicle", "created_by").get(pk=pk)
        except Trip.DoesNotExist:
            return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
        # drivers may read their own trips only; dispatchers any
        if not request.user.is_dispatcher:
            profile = getattr(request.user, "driver_profile", None)
            if not profile or trip.driver_id != profile.id:
                # hide existence: same shape as a missing trip
                return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
        return Response(TripSerializer(trip).data)

    def patch(self, request, pk):
        """status transitions + assignment changes, guarded so a load can't
        jump out of order (assigned -> delivered without driving it)."""
        if not request.user.is_dispatcher:
            return Response({"error": "dispatchers only"},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            trip = Trip.objects.select_related("driver__user", "vehicle", "created_by").get(pk=pk)
        except Trip.DoesNotExist:
            return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)

        updates = {}
        status_from = trip.status
        moved_to = None
        if "status" in request.data:
            new_status = request.data["status"]
            allowed = ALLOWED_TRANSITIONS.get(trip.status, set())
            if new_status not in allowed:
                return Response(
                    {"error": f"cannot go {trip.status} -> {new_status}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if new_status != trip.status:
                updates["status"] = new_status
                moved_to = new_status

        if "driver_id" in request.data:
            driver = request.data["driver_id"]
            if driver in (None, ""):
                updates["driver_id"] = None
            else:
                try:
                    updates["driver_id"] = Driver.objects.get(pk=driver).pk
                except Driver.DoesNotExist:
                    return Response({"error": "no such driver"},
                                    status=status.HTTP_400_BAD_REQUEST)

        if "vehicle_id" in request.data:
            vehicle = request.data["vehicle_id"]
            if vehicle in (None, ""):
                updates["vehicle_id"] = None
            else:
                try:
                    updates["vehicle_id"] = Vehicle.objects.get(pk=vehicle).pk
                except Vehicle.DoesNotExist:
                    return Response({"error": "no such vehicle"},
                                    status=status.HTTP_400_BAD_REQUEST)

        for field in ("actual_pickup_at", "actual_delivery_at", "actual_miles"):
            if field in request.data:
                updates[field] = request.data[field]

        for k, v in updates.items():
            setattr(trip, k, v)
        trip.save(update_fields=[*updates.keys(), "updated_at"])
        if moved_to:
            TripEvent.objects.create(
                trip=trip,
                user=request.user,
                from_status=status_from,
                to_status=moved_to,
            )
        return Response(TripSerializer(trip).data)


class TripPlanPersistView(APIView):
    """
    POST /api/trips/plan/ - plan AND persist as a trip.

    same input as the public calculator plus optional driver/vehicle; runs
    the planner, stores the Trip + its DailyLogs, returns the plan payload
    with the new trip id.

    dispatchers may assign any driver/vehicle (plan lands as "assigned").
    drivers may plan only for themselves and their own truck (lands as
    "draft", the dispatcher approves it).
    """

    throttle_scope = "plan"

    def post(self, request):
        serializer = TripPlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        user = request.user
        trip_status = "draft"
        if user.is_dispatcher:
            driver = vehicle = None
            if data.get("driver_id"):
                try:
                    driver = Driver.objects.get(pk=data["driver_id"])
                except Driver.DoesNotExist:
                    return Response({"error": "no such driver"},
                                    status=status.HTTP_400_BAD_REQUEST)
            if data.get("vehicle_id"):
                try:
                    vehicle = Vehicle.objects.get(pk=data["vehicle_id"])
                except Vehicle.DoesNotExist:
                    return Response({"error": "no such vehicle"},
                                    status=status.HTTP_400_BAD_REQUEST)
            trip_status = "assigned" if (driver or vehicle) else "draft"
        else:
            # a driver planning for their own load: lock to their profile
            profile = getattr(user, "driver_profile", None)
            if profile is None:
                return Response({"error": "no driver profile for this user"},
                                status=status.HTTP_403_FORBIDDEN)
            driver = profile
            if data.get("vehicle_id") and data["vehicle_id"] != profile.vehicle_id:
                return Response({"error": "you can only plan for your own vehicle"},
                                status=status.HTTP_403_FORBIDDEN)
            vehicle = profile.vehicle if profile.vehicle_id else None

        try:
            payload = compute_plan(data)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingUnavailable as e:
            return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        trip = Trip.objects.create(
            created_by=request.user,
            driver=driver,
            vehicle=vehicle,
            current_location=data["current_location"],
            pickup_location=data["pickup_location"],
            dropoff_location=data["dropoff_location"],
            status=trip_status,
            distance_miles=payload["route"]["distance_miles"],
            driving_minutes=payload["route"]["driving_minutes"],
            usage=payload["usage"],
            route_geometry=payload["route"]["geometry"],
            highways=payload["route"]["highways"],
            stops=payload["stops"],
            cycle_used_planned=data["current_cycle_used"],
        )

        for day_number, day in enumerate(payload["daily_logs"], start=1):
            DailyLog.objects.create(
                trip=trip,
                day_number=day_number,
                date=day["date_iso"],
                segments=day["segments"],
                totals=day["totals"],
            )

        return Response(
            {**payload, "trip": TripSerializer(trip).data},
            status=status.HTTP_201_CREATED,
        )


class AlertListView(APIView):
    """GET /api/alerts/ - open watchdog alerts. dispatchers see the fleet
    queue; drivers see only their own.""" 

    def get(self, request):
        qs = Alert.objects.select_related("driver__user").filter(cleared=False)
        if not request.user.is_dispatcher:
            profile = getattr(request.user, "driver_profile", None)
            qs = qs.filter(driver=profile) if profile else qs.none()
        return Response(AlertSerializer(qs[:50], many=True).data)


class AlertResolveView(APIView):
    """POST /api/alerts/<id>/resolve/ - dispatcher closes a watchdog alert."""

    permission_classes = [IsDispatcher]

    def post(self, request, pk):
        try:
            alert = Alert.objects.get(pk=pk)
        except Alert.DoesNotExist:
            return Response({"error": "no such alert"},
                            status=status.HTTP_404_NOT_FOUND)
        alert.cleared = True
        alert.cleared_by = request.user
        alert.cleared_at = timezone.now()
        alert.save(update_fields=["cleared", "cleared_by", "cleared_at"])
        return Response(AlertSerializer(alert).data)


def _extract_stops(segments):
    """pull out the non-driving segments as map markers + timeline rows."""
    stops = []
    for i, seg in enumerate(segments):
        if seg["status"] != "driving":
            stops.append({
                "status": seg["status"],
                "stop_type": _stop_type(seg, i, segments),
                "label": seg.get("name", _status_label(seg["status"])),
                "kind": _status_label(seg["status"]),
                "time": seg["start_time"].strftime("%H:%M"),
                "day": seg["start_time"].strftime("%a %b %d"),
                "location": seg["location"],
                "lat": seg.get("lat"),
                "lon": seg.get("lon"),
                "mile": round(seg.get("distance") or 0.0, 1),
                "duration_min": round(
                    (seg["end_time"] - seg["start_time"]).total_seconds() / 60
                ),
            })
    return stops


def _stop_type(seg, i, segments):
    """classify a stop into pickup/dropoff/fuel/break/rest/restart — the
    frontend keys its timeline + map dots off this, so it needs to be exact."""
    minutes = round((seg["end_time"] - seg["start_time"]).total_seconds() / 60)
    label = (seg.get("name") or "").lower()
    if "fuel" in label:
        return "fuel"
    if seg["status"] == "off_duty":
        return "break"
    if seg["status"] == "sleeper_berth":
        return "restart" if minutes >= 34 * 60 else "rest"
    if seg["status"] == "on_duty_not_driving":
        if i == 0:
            return "pickup"
        if i == len(segments) - 1:
            return "dropoff"
        return "on_duty"
    return "on_duty"


def _status_label(status):
    return {
        "off_duty": "Off Duty",
        "sleeper_berth": "Sleeper Berth",
        "driving": "Driving",
        "on_duty_not_driving": "On Duty (Not Driving)",
    }.get(status, status)