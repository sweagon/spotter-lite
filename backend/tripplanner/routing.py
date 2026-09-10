"""
routing and geocoding helpers. uses:
  - openstreetmap nominatim for geocoding location names -> coordinates
  - osrm public demo server for driving routes (distance + geometry)

both are free, no API keys required. the osrm demo server is rate-limited
and not for production, but it's perfect for a demo/assessment.
"""

import re

import requests
import time

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"

# nominatim requires a valid user-agent; they block default python requests
HEADERS = {"User-Agent": "SpotterTripPlanner/1.0 (assessment project)"}


def suggest(query: str, limit: int = 8) -> list:
    """
    geocoder autocomplete. returns a list of candidate {name, display_name,
    lat, lon} entries so the frontend can offer pick-aplace suggestions while
    the dispatcher types. thin proxy over nominatim's /search.
    """
    params = {
        "q": query,
        "format": "json",
        "limit": limit,
        "addressdetails": 1,
        "countrycodes": "us",
    }
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    return [
        {
            "name": r.get("display_name") or query,
            "short_name": r.get("name") or (r.get("display_name") or query)[:64],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
        }
        for r in results
    ]


def _normalize_highways(step_names: list) -> list:
    """
    turn raw osrm step road names into display labels like "I-55" / "US-66".
    best effort: the free demo route is sparsely annotated, so anything we
    can't confidently call a number road gets dropped rather than shown.
    """
    out = []
    for raw in step_names:
        name = (raw or "").strip()
        if not name or not name.strip():
            continue
        # osrm gives e.g. "Interstate 55", "I-55", "US Highway 50", "Route 66"
        lowered = name.lower()
        label = None
        if "interstate" in lowered:
            label = "I-" + re.sub(r"\D", "", name).lstrip("0")
        elif re.match(r"^i-?\d", lowered):
            label = "I-" + re.sub(r"\D", "", name).lstrip("0")
        elif "u.s." in lowered or "us" in lowered:
            label = "US-" + re.sub(r"\D", "", name).lstrip("0")
        elif lowered.startswith("route "):
            label = "Route " + re.sub(r"\D", "", name)
        elif lowered.startswith("state highway") or "state" in lowered:
            label = "SR-" + re.sub(r"\D", "", name).lstrip("0")
        if label and label not in out:
            out.append(label)
        if len(out) >= 3:
            break
    return out


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
        "steps": "true",  # give us road names so we can label "I-55 / I-44"
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

    # step road names -> short highway labels, deduped
    step_names = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            step_names.append(step.get("name", ""))
    highways = _normalize_highways(step_names)

    return {
        "distance_miles": distance_meters / 1609.344,  # meters -> miles
        "driving_minutes": duration_seconds / 60.0,      # seconds -> minutes
        "geometry": geometry,
        "highways": highways,
    }
