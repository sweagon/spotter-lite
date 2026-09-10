"""
routing and geocoding helpers. uses:
  - openstreetmap nominatim for geocoding location names -> coordinates
  - osrm public demo server for driving routes (distance + geometry)

both are free, no API keys required. the osrm demo server is rate-limited
and not for production, but it's perfect for a demo/assessment.
"""

import requests
import time

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"

# nominatim requires a valid user-agent; they block default python requests
HEADERS = {"User-Agent": "SpotterTripPlanner/1.0 (assessment project)"}


def geocode(location_name: str) -> dict:
    """
    turn a human-readable location string into {name, lat, lon}.

    returns a dict with keys: name, lat, lon, display_name
    raises ValueError if nothing was found.
    """
    params = {
        "q": location_name,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",  # trucking is US-based
    }
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    results = resp.json()

    if not results:
        raise ValueError(f"Could not find location: '{location_name}'")

    r = results[0]
    return {
        "name": location_name,
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "display_name": r.get("display_name", location_name),
    }


def get_route(origin: dict, destination: dict, waypoints: list = None) -> dict:
    """
    get driving route between two points.

    origin/destination are dicts with lat/lon keys.
    returns: {distance_miles, driving_minutes, geometry: [[lon, lat], ...]}
    """
    coords = [f"{origin['lon']},{origin['lat']}"]

    if waypoints:
        for wp in waypoints:
            coords.append(f"{wp['lon']},{wp['lat']}")

    coords.append(f"{destination['lon']},{destination['lat']}")
    coord_str = ";".join(coords)

    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "true",
    }

    url = f"{OSRM_ROUTE_URL}/{coord_str}"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"Could not find driving route between the given locations")

    route = data["routes"][0]
    distance_meters = route["distance"]
    duration_seconds = route["duration"]

    geometry = route["geometry"]["coordinates"]  # [[lon, lat], ...]

    return {
        "distance_miles": distance_meters / 1609.344,  # meters -> miles
        "driving_minutes": duration_seconds / 60.0,      # seconds -> minutes
        "geometry": geometry,
    }
