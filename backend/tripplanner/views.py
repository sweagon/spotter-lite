import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import TripPlanRequestSerializer
from .routing import geocode, get_route, suggest
from .hos_engine import plan_trip, slice_into_days, compute_daily_totals


class HealthView(APIView):
    """GET /api/health/ - trivial liveness check for the host platform."""

    def get(self, request):
        return Response({"status": "ok"})


class SuggestView(APIView):
    """
    GET /api/geocode/suggest/?q=... - geocoder autocomplete.

    feeds the form's "typeahead" so a dispatcher can tab through real place
    names instead of gambling on spellings. frontend debounces the calls.
    """

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 3:
            return Response([])
        try:
            return Response(suggest(q))
        except Exception:
            # autocomplete is a nicety; never let it break the page
            return Response([])


class TripPlanView(APIView):
    """
    POST /api/trip/plan/

    takes current/pickup/dropoff locations + cycle balance, runs routing
    and the HOS simulation, returns the route plus per-day log data.
    """

    def post(self, request):
        serializer = TripPlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # --- geocode all three locations ---
        try:
            current_loc = geocode(data["current_location"])
        except ValueError as e:
            return Response(
                {"error": f"Could not find current location: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            pickup_loc = geocode(data["pickup_location"])
        except ValueError as e:
            return Response(
                {"error": f"Could not find pickup location: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dropoff_loc = geocode(data["dropoff_location"])
        except ValueError as e:
            return Response(
                {"error": f"Could not find dropoff location: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- get driving route (pickup -> dropoff) ---
        # we skip the current location for routing since the driver is
        # assumed to be at or near the pickup (or we just plan from pickup).
        try:
            route = get_route(pickup_loc, dropoff_loc)
        except ValueError as e:
            return Response(
                {"error": f"Routing failed: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": f"Routing service unavailable: {e}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # --- run HOS simulation ---
        stats = {}
        trip_segments = plan_trip(
            pickup_location=pickup_loc,
            dropoff_location=dropoff_loc,
            current_cycle_used=data["current_cycle_used"],
            route_distance_miles=route["distance_miles"],
            route_driving_minutes=route["driving_minutes"],
            route_geometry=route["geometry"],
            start_time=datetime.datetime.now().replace(second=0, microsecond=0),
            stats=stats,
        )

        # --- slice into per-day logs ---
        days = slice_into_days(trip_segments)

        daily_logs = []
        for day_start, day_segs in days:
            totals = compute_daily_totals(day_segs)
            daily_logs.append({
                "date": day_start.strftime("%a %b %d, %Y"),
                "segments": [
                    {
                        "status": seg["status"],
                        "start_time": seg["start_time"].strftime("%H:%M"),
                        "end_time": seg["end_time"].strftime("%H:%M"),
                        # float hours relative to this day's midnight: the
                        # graph needs numeric positions and "00:00" is
                        # ambiguous between day start and day end.
                        "start_hour": (seg["start_time"] - day_start).total_seconds() / 3600,
                        "end_hour": (seg["end_time"] - day_start).total_seconds() / 3600,
                        "location": seg["location"],
                        "name": seg.get("name", seg["location"]),
                    }
                    for seg in day_segs
                ],
                "totals": {k: round(v, 2) for k, v in totals.items()},
            })

        # --- build stop markers for the map ---
        stops = _extract_stops(trip_segments)

        return Response({
            "route": {
                "distance_miles": round(route["distance_miles"], 1),
                "driving_minutes": round(route["driving_minutes"], 1),
                "geometry": route["geometry"],
                "highways": route.get("highways", []),
            },
            "usage": stats,
            "stops": stops,
            "daily_logs": daily_logs,
        })


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
        # 34+ hr sleep == restart, otherwise a normal 10-hr rest reset
        return "restart" if minutes >= 34 * 60 else "rest"
    if seg["status"] == "on_duty_not_driving":
        # the engine always emits pickup first and dropoff last
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
