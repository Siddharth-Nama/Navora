import json
import logging

import httpx
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from trips.maps import (
    geocode_stops,
    point_at_mile,
    route,
    route_distance,
    route_geometry,
)
from trips.planner import build_timeline, split_daily_logs, summarize_trip

logger = logging.getLogger(__name__)

DEFAULT_CYCLE_USED = 0.0


def health(request):
    return JsonResponse({"status": "ok"})


def read_location(field, value):
    if value is None:
        return None, f"{field} is required."
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, f"{field} is required."
        return text, None
    if isinstance(value, dict) and "lat" in value and "lng" in value:
        try:
            lat = float(value["lat"])
            lng = float(value["lng"])
        except (TypeError, ValueError):
            return None, f"{field} coordinates must be numbers."
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return None, f"{field} coordinates are out of range."
        return {"lat": lat, "lng": lng}, None
    return None, f"{field} must be a place name or coordinates."


def read_trip_input(body):
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return None, "Request body must be JSON."
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object."

    trip = {}
    for field in ("pickup_location", "dropoff_location"):
        value, error = read_location(field, data.get(field))
        if error:
            return None, error
        trip[field] = value

    if "current_cycle_used" not in data or data.get("current_cycle_used") is None:
        trip["current_cycle_used"] = DEFAULT_CYCLE_USED
    else:
        hours = data.get("current_cycle_used")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            return None, "current_cycle_used must be a number from 0 to 70."
        if hours < 0 or hours > 70:
            return None, "current_cycle_used must be a number from 0 to 70."
        trip["current_cycle_used"] = float(hours)
    return trip, None


@csrf_exempt
def plan_trip(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    trip, error = read_trip_input(request.body)
    if error:
        return JsonResponse({"error": error}, status=400)

    try:
        stops, error = geocode_stops(trip)
    except httpx.TimeoutException:
        logger.warning("Geocode timed out for trip=%s", trip)
        return JsonResponse({"error": "Map lookup timed out."}, status=502)
    except httpx.HTTPError:
        logger.warning("Geocode failed for trip=%s", trip)
        return JsonResponse({"error": "Map lookup failed."}, status=502)
    if error:
        return JsonResponse({"error": error}, status=400)

    road, error = route(stops)
    if error:
        status = 502
        if error.startswith("No road route"):
            status = 400
        return JsonResponse({"error": error}, status=status)

    distance = route_distance(road)
    geometry = route_geometry(road)
    events, clocks = build_timeline(distance, trip["current_cycle_used"])
    logs = split_daily_logs(events)
    summary = summarize_trip(events, distance, clocks)

    stop_points = []
    for event in events:
        if event["status"] == "driving":
            continue
        point = point_at_mile(geometry, event["miles"]) or {}
        stop_points.append(
            {
                "type": event["type"],
                "status": event["status"],
                "hours": event["start"],
                "miles": event["miles"],
                "lat": point.get("lat"),
                "lng": point.get("lng"),
            }
        )

    return JsonResponse(
        {
            "stops": stops,
            "route": {
                "miles": distance["miles"],
                "minutes": distance["minutes"],
                "legs": distance["legs"],
                "geometry": geometry,
            },
            "events": events,
            "markers": stop_points,
            "logs": logs,
            "summary": summary,
        }
    )
