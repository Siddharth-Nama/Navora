import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_cache = {}


def geocode(place):
    if isinstance(place, dict):
        lat = float(place["lat"])
        lng = float(place["lng"])
        label = place.get("label") or f"{lat}, {lng}"
        return {"lat": lat, "lng": lng, "label": label}

    query = str(place).strip()
    if not query:
        return None
    key = query.casefold()
    if key in _cache:
        return _cache[key]

    response = httpx.get(
        os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"),
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": os.environ.get("MAP_USER_AGENT", "navora-trip-planner")},
        timeout=float(os.environ.get("MAP_TIMEOUT_SECONDS", "8")),
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        _cache[key] = None
        return None
    hit = results[0]
    found = {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "label": hit.get("display_name") or query,
    }
    _cache[key] = found
    return found


def geocode_stops(trip):
    stops = {}
    for field in ("current_location", "pickup_location", "dropoff_location"):
        found = geocode(trip[field])
        if found is None:
            return None, f"Could not find {field}."
        stops[field] = found
    return stops, None


def route(stops):
    points = (
        stops["current_location"],
        stops["pickup_location"],
        stops["dropoff_location"],
    )
    coords = ";".join(f"{point['lng']},{point['lat']}" for point in points)
    base = os.environ.get(
        "OSRM_URL",
        "https://router.project-osrm.org/route/v1/driving",
    ).rstrip("/")
    response = httpx.get(
        f"{base}/{coords}",
        params={"overview": "full", "geometries": "geojson"},
        timeout=float(os.environ.get("MAP_TIMEOUT_SECONDS", "8")),
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None, "Could not find a road route."
    return data["routes"][0], None