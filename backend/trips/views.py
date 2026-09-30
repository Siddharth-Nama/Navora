import json

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


def health(request):
    return JsonResponse({"status": "ok"})


def read_location(field, value):
    if isinstance(value, str) and value.strip():
        return value.strip(), None
    if isinstance(value, dict) and "lat" in value and "lng" in value:
        try:
            return {
                "lat": float(value["lat"]),
                "lng": float(value["lng"]),
                "label": value.get("label"),
            }, None
        except (TypeError, ValueError):
            return None, f"{field} coordinates must be numbers."
    return None, f"{field} must be a place name or coordinates."


def read_trip_input(body):
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return None, "Request body must be JSON."
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object."

    trip = {}
    for field in ("current_location", "pickup_location", "dropoff_location"):
        value, error = read_location(field, data.get(field))
        if error:
            return None, error
        trip[field] = value

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

    stops, error = geocode_stops(trip)
    if error:
        return JsonResponse({"error": error}, status=400)

    road, error = route(stops)
    if error:
        return JsonResponse({"error": error}, status=502)

    distance = route_distance(road)
    geometry = route_geometry(road)
    events, clocks = build_timeline(distance, trip["current_cycle_used"])
    logs = split_daily_logs(events)
    summary = summarize_trip(events, distance, clocks)

    stop_points = []
    for event in events:
        if event["status"] == "driving":
            continue
        point = point_at_mile(geometry, event["miles"]) or {
            "lat": None,
            "lng": None,
        }
        stop_points.append(
            {
                "label": event["label"],
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