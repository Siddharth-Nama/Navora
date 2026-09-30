import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def health(request):
    return JsonResponse({"status": "ok"})


def read_trip_input(body):
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return None, "Request body must be JSON."
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object."

    trip = {}
    for field in ("current_location", "pickup_location", "dropoff_location"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"{field} is required."
        trip[field] = value.strip()

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
    return JsonResponse(trip)