import logging

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

_q_param = OpenApiParameter(
    name="q", type=str, description="location search fragment (>=3 characters)"
)
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from . import duty
from .models import Alert, DailyLog, Driver, DutyEvent, Trip, TripEvent, Vehicle
from .permissions import IsDispatcher
from .pdf_export import build_logs_pdf
from .routing import geocode, get_route, suggest
from .hos_engine import plan_trip, slice_into_days, compute_daily_totals
from .serializers import (
    AlertSerializer,
    DriverSerializer,
    DutyEventSerializer,
    TripPlanRequestSerializer,
    TripSerializer,
    UserSummarySerializer,
    VehicleSerializer,
)

User = get_user_model()

logger = logging.getLogger("tripplanner")


class HealthView(APIView):
    """GET /api/health/ - liveness, plus a DB ping so Render knows the
    backend is actually able to serve requests, not just boots."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        description="liveness + DB ping",
    )
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

    @extend_schema(
        parameters=[_q_param],
        responses={200: OpenApiTypes.OBJECT},
        description="geocoder autocomplete (lenient, never fails the page)",
    )
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

    @extend_schema(
        request=TripPlanRequestSerializer,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT},
        description="public stateless planner: locations + cycle balance -> route + daily logs",
    )
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

    @extend_schema(
        request=_LoginSerializer,
        responses={200: OpenApiTypes.OBJECT},
        description="username/password -> JWT pair + user summary",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    """POST /api/auth/logout/ {refresh} - blacklist the refresh token."""

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        description="blacklist a refresh token",
    )
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


def _duty_payload(driver):
    """today's duty state for a driver: open event + rows + a drawable day
    (segments padded to 24h) so the cab and the board render identically."""
    segments = duty.today_segments(driver)
    open_ev = duty.open_event(driver)
    current = None
    if open_ev:
        current = {
            "id": open_ev.id,
            "status": open_ev.status,
            "status_label": open_ev.get_status_display(),
            "started_at": open_ev.started_at.isoformat(),
            "ended_at": open_ev.ended_at.isoformat() if open_ev.ended_at else None,
            "location": open_ev.location,
            "remark": open_ev.remark,
            "trip_id": open_ev.trip_id,
        }
    return {
        "driver_id": driver.id,
        "current": current,
        "today": duty.today_events(driver),
        "segments": segments,
        "totals": duty.today_totals(segments),
        "today_driving_hours": duty.today_driving_hours(driver),
    }


class DutyStateView(APIView):
    """GET /api/duty/ - the requesting driver's current duty status and
    today's record of duty status. fleet staff may ask for ?driver_id=."""

    @extend_schema(
        parameters=[OpenApiParameter(name="driver_id", type=int)],
        responses={200: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
        description="current duty state + today's RODS for a driver",
    )
    def get(self, request):
        driver_id = request.query_params.get("driver_id")
        if request.user.can_manage_fleet and driver_id:
            try:
                driver = Driver.objects.get(pk=driver_id)
            except Driver.DoesNotExist:
                return Response({"error": "no such driver"}, status=status.HTTP_404_NOT_FOUND)
        else:
            profile = getattr(request.user, "driver_profile", None)
            if profile is None:
                return Response({"error": "no driver profile for this user"},
                                status=status.HTTP_403_FORBIDDEN)
            driver = profile
        return Response(_duty_payload(driver))


class DutyEventCreateView(APIView):
    """POST /api/duty/events/ {status, location?, remark?, trip_id?} -
    close the driver's current status and open a new one. drivers only."""

    @extend_schema(
        request=DutyEventSerializer,
        responses={201: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
        description="record a duty-status change (closes the previous event)",
    )
    def post(self, request):
        profile = getattr(request.user, "driver_profile", None)
        if request.user.role != "driver" or profile is None:
            return Response({"error": "drivers only"},
                            status=status.HTTP_403_FORBIDDEN)

        status_value = request.data.get("status")
        valid = {s for s, _ in DutyEvent.STATUS_CHOICES}
        if status_value not in valid:
            return Response({"error": "invalid duty status"},
                            status=status.HTTP_400_BAD_REQUEST)

        open_ev = duty.open_event(profile)
        if open_ev and open_ev.status == status_value:
            return Response(
                {"error": f"already on duty status {open_ev.get_status_display()}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        trip_id = request.data.get("trip_id")
        trip = None
        if trip_id:
            trip = Trip.objects.filter(pk=trip_id, driver=profile).first()
            if trip is None:
                return Response({"error": "trip not found for this driver"},
                                status=status.HTTP_400_BAD_REQUEST)

        if open_ev:
            open_ev.ended_at = now
            open_ev.save(update_fields=["ended_at"])

        DutyEvent.objects.create(
            driver=profile,
            status=status_value,
            started_at=now,
            location=(request.data.get("location") or "").strip()[:200],
            remark=(request.data.get("remark") or "").strip()[:255],
            trip=trip,
        )
        logger.info(
            "duty_event user=%s status=%s trip=%s",
            request.user.username, status_value, trip.id if trip else None,
        )
        return Response(_duty_payload(profile), status=status.HTTP_201_CREATED)


class MeView(APIView):
    """GET /api/me/ - current user + (for drivers) their fleet profile +
    open alerts. what the SPA needs to paint the right home screen."""

    @extend_schema(
        responses={200: UserSummarySerializer},
        description="current user summary (+ driver profile/alerts when applicable)",
    )
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
            data["duty"] = _duty_payload(profile)
            data["alerts"] = AlertSerializer(
                profile.alerts.filter(cleared=False)[:10], many=True
            ).data
        return Response(data)


# ---------------------------------------------------------------------------
# fleet
# ---------------------------------------------------------------------------

class DriverListView(APIView):
    # read-side fleet board: the handler gates by can_manage_fleet so
    # auditor reads too; mutations stay dispatcher-only elsewhere.
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: DriverSerializer(many=True)},
        description="active drivers (fleet board)",
    )
    def get(self, request):
        if not request.user.can_manage_fleet:
            return Response({"error": "fleet access denied"},
                            status=status.HTTP_403_FORBIDDEN)
        qs = Driver.objects.select_related("user", "vehicle").filter(active=True)
        return Response(DriverSerializer(qs, many=True).data)


class DriverDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: DriverSerializer, 404: OpenApiTypes.OBJECT},
        description="one driver's profile",
    )
    def get(self, request, pk):
        if not request.user.can_manage_fleet:
            return Response({"error": "fleet access denied"},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            driver = Driver.objects.select_related("user", "vehicle").get(pk=pk)
        except Driver.DoesNotExist:
            return Response({"error": "no such driver"}, status=status.HTTP_404_NOT_FOUND)
        return Response(DriverSerializer(driver).data)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: DriverSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
        description="admin edits a driver profile (name, truck, CDL, cycle, active, role)",
    )
    def patch(self, request, pk):
        if not request.user.is_admin:
            return Response({"error": "admins only"},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            driver = Driver.objects.select_related("user", "vehicle").get(pk=pk)
        except Driver.DoesNotExist:
            return Response({"error": "no such driver"}, status=status.HTTP_404_NOT_FOUND)
        user = driver.user

        for field in ("first_name", "last_name"):
            if field in request.data:
                setattr(user, field, (request.data[field] or "").strip())
        if "role" in request.data:
            role = request.data["role"]
            if role not in dict(User.ROLE_CHOICES):
                return Response({"error": "invalid role"},
                                status=status.HTTP_400_BAD_REQUEST)
            if user.pk == request.user.pk and role != "admin":
                return Response({"error": "you cannot demote your own account"},
                                status=status.HTTP_400_BAD_REQUEST)
            user.role = role
            user.is_staff = role == "admin"
        user.save()

        if "vehicle_id" in request.data:
            vehicle_id = request.data["vehicle_id"]
            if vehicle_id in (None, ""):
                driver.vehicle = None
            else:
                try:
                    vehicle = Vehicle.objects.get(pk=vehicle_id)
                except Vehicle.DoesNotExist:
                    return Response({"error": "no such vehicle"},
                                    status=status.HTTP_400_BAD_REQUEST)
                occupied = Driver.objects.filter(vehicle=vehicle).exclude(pk=driver.pk).exists()
                if occupied:
                    return Response({"error": "that vehicle is already assigned"},
                                    status=status.HTTP_400_BAD_REQUEST)
                driver.vehicle = vehicle
        for field in ("cdl_number", "cycle_used"):
            if field in request.data:
                setattr(driver, field, request.data[field])
        if "active" in request.data:
            driver.active = bool(request.data["active"])
        driver.save()
        return Response(DriverSerializer(driver).data)


class DriverCycleResetView(APIView):
    """POST /api/drivers/<id>/reset-cycle/ - zero the 70h cycle (admin or
    dispatcher). the watchdog re-projects from the new declared balance."""

    permission_classes = [IsDispatcher]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: DriverSerializer, 404: OpenApiTypes.OBJECT},
        description="reset a driver's 70h/8-day cycle balance",
    )
    def post(self, request, pk):
        try:
            driver = Driver.objects.select_related("user", "vehicle").get(pk=pk)
        except Driver.DoesNotExist:
            return Response({"error": "no such driver"}, status=status.HTTP_404_NOT_FOUND)
        try:
            cycle = float(request.data.get("cycle_used") or 0)
        except (TypeError, ValueError):
            return Response({"error": "cycle_used must be a number"},
                            status=status.HTTP_400_BAD_REQUEST)
        driver.cycle_used = max(0.0, min(cycle, 70.0))
        driver.last_cycle_reset = timezone.now()
        driver.save(update_fields=["cycle_used", "last_cycle_reset"])
        logger.info("cycle_reset driver=%s reset=%d by=%s",
                    driver.user.username, driver.cycle_used, request.user.username)
        return Response(DriverSerializer(driver).data)


class VehicleListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: VehicleSerializer(many=True)},
        description="active vehicles",
    )
    def get(self, request):
        if not request.user.can_manage_fleet:
            return Response({"error": "fleet access denied"},
                            status=status.HTTP_403_FORBIDDEN)
        qs = Vehicle.objects.filter(active=True)
        return Response(VehicleSerializer(qs, many=True).data)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={201: VehicleSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
        description="admin adds a vehicle to the fleet",
    )
    def post(self, request):
        if not request.user.is_admin:
            return Response({"error": "admins only"},
                            status=status.HTTP_403_FORBIDDEN)
        unit_no = (request.data.get("unit_no") or "").strip()
        if not unit_no:
            return Response({"error": "unit no is required"},
                            status=status.HTTP_400_BAD_REQUEST)
        if Vehicle.objects.filter(unit_no=unit_no).exists():
            return Response({"error": "unit no already in the fleet"},
                            status=status.HTTP_400_BAD_REQUEST)
        vehicle = Vehicle.objects.create(
            unit_no=unit_no,
            vin=(request.data.get("vin") or "").strip(),
            vehicle_type=request.data.get("vehicle_type") or "sleeper",
            current_odometer=request.data.get("current_odometer"),
        )
        return Response(VehicleSerializer(vehicle).data, status=status.HTTP_201_CREATED)


class VehicleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: VehicleSerializer, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
        description="one vehicle (read for fleet staff, patch for admins)",
    )
    def get(self, request, pk):
        if not request.user.can_manage_fleet:
            return Response({"error": "fleet access denied"},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            vehicle = Vehicle.objects.get(pk=pk)
        except Vehicle.DoesNotExist:
            return Response({"error": "no such vehicle"}, status=status.HTTP_404_NOT_FOUND)
        return Response(VehicleSerializer(vehicle).data)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: VehicleSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
        description="admin edits vin/type/odometer/active",
    )
    def patch(self, request, pk):
        if not request.user.is_admin:
            return Response({"error": "admins only"},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            vehicle = Vehicle.objects.get(pk=pk)
        except Vehicle.DoesNotExist:
            return Response({"error": "no such vehicle"}, status=status.HTTP_404_NOT_FOUND)
        updates = {}
        for field in ("vin", "vehicle_type", "current_odometer"):
            if field in request.data:
                updates[field] = request.data[field]
        if "active" in request.data:
            updates["active"] = bool(request.data["active"])
        if "unit_no" in request.data and request.data["unit_no"]:
            new_unit = request.data["unit_no"].strip()
            if Vehicle.objects.filter(unit_no=new_unit).exclude(pk=vehicle.pk).exists():
                return Response({"error": "unit no already in the fleet"},
                                status=status.HTTP_400_BAD_REQUEST)
            updates["unit_no"] = new_unit
        for k, v in updates.items():
            setattr(vehicle, k, v)
        vehicle.save()
        return Response(VehicleSerializer(vehicle).data)


class CreateDriverView(APIView):
    """POST /api/drivers/ - dispatcher creates a driver login + HOS profile.
    vehicles, passwords and most org rows keep the Django admin for now."""

    permission_classes = [IsDispatcher]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={201: DriverSerializer, 400: OpenApiTypes.OBJECT, 409: OpenApiTypes.OBJECT},
        description="dispatcher creates a driver login + HOS profile",
    )
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
    if not user.can_manage_fleet:
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

    @extend_schema(
        parameters=[
            OpenApiParameter(name="status", type=str),
            OpenApiParameter(name="driver", type=str),
        ],
        responses={200: TripSerializer(many=True)},
        description="trip board (drivers see own trips only)",
    )
    def get(self, request):
        qs = _visible_queryset(request.user)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        driver = request.query_params.get("driver")
        if driver:
            qs = qs.filter(driver__user__username=driver)
        return Response(TripSerializer(qs, many=True).data)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={201: TripSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
        description="dispatcher drafts a trip from locations alone",
    )
    def post(self, request):
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
    @extend_schema(
        responses={200: TripSerializer, 404: OpenApiTypes.OBJECT},
        description="one trip (drivers read own trips only)",
    )
    def get(self, request, pk):
        try:
            trip = Trip.objects.select_related("driver__user", "vehicle", "created_by").get(pk=pk)
        except Trip.DoesNotExist:
            return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
        # drivers may read their own trips only; dispatchers/auditor any
        if not request.user.can_manage_fleet:
            profile = getattr(request.user, "driver_profile", None)
            if not profile or trip.driver_id != profile.id:
                # hide existence: same shape as a missing trip
                return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
        return Response(TripSerializer(trip).data)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: TripSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
        description="advance status / reassign (dispatcher) — a driver may mark their own trip's status only",
    )
    def patch(self, request, pk):
        """status transitions + assignment changes, guarded so a load can't
        jump out of order (assigned -> delivered without driving it).
        drivers may advance their *own* trip's status (start/stop/deliver)
        but can never reassign driver/vehicle."""
        if request.user.is_dispatcher:
            try:
                trip = Trip.objects.select_related("driver__user", "vehicle", "created_by").get(pk=pk)
            except Trip.DoesNotExist:
                return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
        elif request.user.role == "driver":
            profile = getattr(request.user, "driver_profile", None)
            try:
                trip = Trip.objects.select_related("driver__user", "vehicle", "created_by").get(pk=pk)
            except Trip.DoesNotExist:
                return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
            if not profile or trip.driver_id != profile.id:
                # hide existence, same as a missing trip
                return Response({"error": "no such trip"}, status=status.HTTP_404_NOT_FOUND)
            for field in ("driver_id", "vehicle_id"):
                if field in request.data:
                    return Response({"error": "drivers cannot reassign"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "dispatchers only"},
                            status=status.HTTP_403_FORBIDDEN)

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

    @extend_schema(
        request=TripPlanRequestSerializer,
        responses={201: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT},
        description="plan + persist a trip with its daily logs",
    )
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

    @extend_schema(
        responses={200: AlertSerializer(many=True)},
        description="open HOS watchdog alerts (fleet queue for staff)",
    )
    def get(self, request):
        qs = Alert.objects.select_related("driver__user").filter(cleared=False)
        if not request.user.can_manage_fleet:
            profile = getattr(request.user, "driver_profile", None)
            qs = qs.filter(driver=profile) if profile else qs.none()
        return Response(AlertSerializer(qs[:50], many=True).data)


class AlertResolveView(APIView):
    """POST /api/alerts/<id>/resolve/ - dispatcher closes a watchdog alert."""

    permission_classes = [IsDispatcher]

    @extend_schema(
        request=None,
        responses={200: AlertSerializer, 404: OpenApiTypes.OBJECT},
        description="dispatcher closes an alert",
    )
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


class ExportLogsPDFView(APIView):
    """
    GET /api/export/logs.pdf?driver_id=&start=&end=

    Compliance packet: every DailyLog sheet for the selected trips as one
    PDF (24x4 shaded grid, line-4 totals + 24.00 checksum, remarks, recap).
    Dispatchers/admins/auditors may export any driver; a driver may export
    only their own runs.
    """

    # no permission_classes override: default IsAuthenticated applies, and
    # role access (fleet-wide vs driver-own) is enforced inside the handler.
    throttle_scope = "export"

    @extend_schema(
        parameters=[
            OpenApiParameter(name="driver_id", type=int),
            OpenApiParameter(name="start", type=str),
            OpenApiParameter(name="end", type=str),
        ],
        responses={200: ("application/pdf", OpenApiTypes.BINARY), 404: OpenApiTypes.OBJECT},
        description="compliance packet PDF (24x4 HOS grids + totals + remarks)",
    )
    def get(self, request):
        qs = Trip.objects.select_related("driver__user", "vehicle").prefetch_related(
            "daily_logs"
        )

        driver_filter = request.query_params.get("driver_id")
        if request.user.can_manage_fleet:
            if driver_filter:
                qs = qs.filter(driver_id=driver_filter)
        else:
            # driver role: locked to their own profile regardless of params
            profile = getattr(request.user, "driver_profile", None)
            if profile is None:
                return Response({"error": "no driver profile for this user"},
                                status=status.HTTP_403_FORBIDDEN)
            qs = qs.filter(driver=profile)

        start = request.query_params.get("start")
        if start:
            qs = qs.filter(created_at__date__gte=start)
        end = request.query_params.get("end")
        if end:
            qs = qs.filter(created_at__date__lte=end)

        trips = list(qs.order_by("created_at")[:50])
        # a compliance packet must contain at least one drawn log sheet:
        # trips with no DailyLog rows yield nothing worth exporting.
        log_trip_ids = set(
            DailyLog.objects.filter(trip_id__in=[t.id for t in trips])
            .values_list("trip_id", flat=True)
        )
        trips = [t for t in trips if t.id in log_trip_ids]
        if not trips:
            return Response({"error": "no trips match that filter"},
                            status=status.HTTP_404_NOT_FOUND)

        logger.info(
            "export_logs_pdf user=%s role=%s trips=%d",
            request.user.username,
            request.user.role,
            len(trips),
        )
        groups = [(t, list(t.daily_logs.all().order_by("day_number"))) for t in trips]
        pdf = build_logs_pdf(groups)
        filename = f"spotter_hos_{timezone.now():%Y%m%d_%H%M}.pdf"
        return HttpResponse(
            pdf,
            content_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


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