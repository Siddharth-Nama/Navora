# Navora

Django backend built for the **Spotter Labs** assessment use case: US long-haul **spot-market trucking**, not a general trip planner.

Spotter focuses on autonomous dispatching for property-carrying trucks ([Spotter Labs](https://www.linkedin.com/company/spotter-labs/), [spotter.ai](https://spotter.ai/)). This API mirrors that domain: pickup to dropoff routing, FMCSA-style Hours of Service planning, fuel stops on the route, and ELD-style daily duty logs for dispatch and drivers.

## What it is for

- Long-haul truck loads with a pickup and a dropoff
- Property-carrying driver HOS clocks (11h drive, 14h window, 30-min break, 70h/8-day cycle, 10h reset, 34h restart)
- Fuel stops about every 1,000 miles along the planned road route
- One hour on duty at pickup and one hour at dropoff
- JSON duty timeline and daily logs a dispatcher can review (not a certified ELD product)

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python backend\manage.py runserver
```

Health check:

```text
GET http://127.0.0.1:8000/api/health/
GET http://127.0.0.1:8000/api/health
```

## Plan a truck trip

Both URLs work (with or without the trailing slash):

```text
POST http://127.0.0.1:8000/api/trips/plan/
POST http://127.0.0.1:8000/api/trips/plan
```

Use geolocation coordinates (`lat` / `lng`) for stops. You can also put a city name instead of coordinates.

```json
{
  "pickup_location": { "lat": 30.2672, "lng": -97.7431 },
  "dropoff_location": { "lat": 39.7392, "lng": -104.9903 },
  "current_cycle_used": 12
}
```

Same trip with city names:

```json
{
  "pickup_location": "Austin, TX",
  "dropoff_location": "Denver, CO",
  "current_cycle_used": 12
}
```

### Optional fields

- `current_cycle_used` is optional. Default is `0` (hours already used in the 70-hour cycle before this load).

Minimum body:

```json
{
  "pickup_location": { "lat": 30.2672, "lng": -97.7431 },
  "dropoff_location": { "lat": 39.7392, "lng": -104.9903 }
}
```

### Errors

| Status | When |
| --- | --- |
| `400` | Missing/invalid input, unknown place, same pickup/dropoff, or no road route |
| `405` | Method is not `POST` |
| `502` | Map or route provider timed out or failed |

A successful response includes geocoded stops, the truck road route, HOS duty events, map markers, daily logs, and a summary.

Exact miles and hours depend on the live map route.

## How the plan stays fast

- One OSRM road route for pickup and dropoff. No extra route calls for breaks or fuel.
- Place-name geocoding and repeated routes are cached in memory. Coordinates skip geocoding.
- Route geometry uses OSRM `simplified` overview to keep payloads smaller.
- Hours of service math runs in plain Python with no database.
- Daily logs are JSON duty segments. The API does not render log sheet images.
- Map HTTP calls use connect + read timeouts from `MAP_TIMEOUT_SECONDS`.

## Tests

```powershell
.\.venv\Scripts\python backend\manage.py test trips
```

HOS rules are covered with mocked distances so map outages do not break planner tests.