import logging
import math
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

_cache = {}
_route_cache = {}


def map_timeout():
    seconds = float(os.environ.get("MAP_TIMEOUT_SECONDS", "8"))
    return httpx.Timeout(seconds, connect=min(3.0, seconds))


def validate_coordinates(point, field):
    try:
        lat = float(point["lat"])
        lng = float(point["lng"])
    except (KeyError, TypeError, ValueError):
        return None, f"{field} coordinates must be numbers."
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None, f"{field} coordinates are out of range."
    return {"lat": lat, "lng": lng}, None


def geocode(place):
    if isinstance(place, dict):
        found, _error = validate_coordinates(place, "location")
        return found

    query = str(place).strip()
    if not query:
        return None
    key = query.casefold()
    if key in _cache:
        return _cache[key]

    try:
        response = httpx.get(
            os.environ.get(
                "NOMINATIM_URL",
                "https://nominatim.openstreetmap.org/search",
            ),
            params={"q": query, "format": "json", "limit": 1},
            headers={
                "User-Agent": os.environ.get(
                    "MAP_USER_AGENT",
                    "navora-trip-planner",
                )
            },
            timeout=map_timeout(),
        )
        response.raise_for_status()
        results = response.json()
    except httpx.TimeoutException:
        logger.warning("Nominatim timeout for query=%s", query)
        raise
    except httpx.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("Nominatim error status=%s query=%s", status, query)
        raise

    if not results:
        _cache[key] = None
        return None
    hit = results[0]
    found = {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
    }
    _cache[key] = found
    return found


def geocode_stops(trip):
    stops = {}
    for field in ("pickup_location", "dropoff_location"):
        value = trip[field]
        if isinstance(value, dict):
            found, error = validate_coordinates(value, field)
            if error:
                return None, error
        else:
            found = geocode(value)
            if found is None:
                return None, f"Could not find {field}."
        stops[field] = found

    pickup = stops["pickup_location"]
    dropoff = stops["dropoff_location"]
    if (
        abs(pickup["lat"] - dropoff["lat"]) < 1e-6
        and abs(pickup["lng"] - dropoff["lng"]) < 1e-6
    ):
        return None, "pickup_location and dropoff_location must be different."
    return stops, None


def _route_cache_key(stops):
    pickup = stops["pickup_location"]
    dropoff = stops["dropoff_location"]
    return (
        round(pickup["lat"], 5),
        round(pickup["lng"], 5),
        round(dropoff["lat"], 5),
        round(dropoff["lng"], 5),
    )


def route(stops):
    key = _route_cache_key(stops)
    if key in _route_cache:
        return _route_cache[key], None

    points = (
        stops["pickup_location"],
        stops["dropoff_location"],
    )
    coords = ";".join(f"{point['lng']},{point['lat']}" for point in points)
    base = os.environ.get(
        "OSRM_URL",
        "https://router.project-osrm.org/route/v1/driving",
    ).rstrip("/")
    url = f"{base}/{coords}"

    try:
        response = httpx.get(
            url,
            params={"overview": "simplified", "geometries": "geojson"},
            timeout=map_timeout(),
        )
    except httpx.TimeoutException:
        logger.warning("OSRM timeout for route=%s", coords)
        return None, "Route lookup timed out."
    except httpx.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("OSRM request error status=%s route=%s", status, coords)
        return None, "Route lookup failed."

    if response.status_code >= 400:
        logger.warning(
            "OSRM HTTP %s for route=%s body=%s",
            response.status_code,
            coords,
            response.text[:200],
        )
        return None, "Route lookup failed."

    try:
        data = response.json()
    except ValueError:
        logger.warning("OSRM returned non-JSON for route=%s", coords)
        return None, "Route lookup failed."

    code = data.get("code")
    if code != "Ok" or not data.get("routes"):
        logger.warning("OSRM code=%s for route=%s", code, coords)
        if code in {"NoRoute", "NoSegment"}:
            return None, "No road route found between pickup and dropoff."
        return None, "Route lookup failed."

    road = data["routes"][0]
    _route_cache[key] = road
    return road, None


def route_distance(road):
    legs = [
        {
            "miles": leg["distance"] / 1609.344,
            "minutes": leg["duration"] / 60,
        }
        for leg in road.get("legs", [])
    ]
    return {
        "miles": road["distance"] / 1609.344,
        "minutes": road["duration"] / 60,
        "legs": legs,
    }


def route_geometry(road):
    coordinates = road.get("geometry", {}).get("coordinates", [])
    return [{"lat": lat, "lng": lng} for lng, lat in coordinates]


def _miles_between(a, b):
    lat1, lng1 = math.radians(a["lat"]), math.radians(a["lng"])
    lat2, lng2 = math.radians(b["lat"]), math.radians(b["lng"])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    return 3958.7613 * 2 * math.asin(math.sqrt(h))


def point_at_mile(points, miles):
    if not points:
        return None
    if miles <= 0:
        return points[0]
    walked = 0.0
    for start, end in zip(points, points[1:]):
        segment = _miles_between(start, end)
        if walked + segment >= miles:
            if segment == 0:
                return end
            ratio = (miles - walked) / segment
            return {
                "lat": start["lat"] + (end["lat"] - start["lat"]) * ratio,
                "lng": start["lng"] + (end["lng"] - start["lng"]) * ratio,
            }
        walked += segment
    return points[-1]
