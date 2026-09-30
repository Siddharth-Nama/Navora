# Navora

Trip planning API for property-carrying drivers. Django backend only.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python backend\manage.py runserver
```

Open http://127.0.0.1:8000/api/health/

The health check returns `{"status": "ok"}`.

## Plan a trip

`POST /api/trips/plan/`

Use geolocation coordinates (`lat` / `lng`) for stops. You can also put a city name instead of coordinates.

```json
{
  "current_location": { "lat": 32.7767, "lng": -96.797 },
  "pickup_location": { "lat": 30.2672, "lng": -97.7431 },
  "dropoff_location": { "lat": 39.7392, "lng": -104.9903 },
  "current_cycle_used": 12
}
```

Same trip with city names:

```json
{
  "current_location": "Dallas, TX",
  "pickup_location": "Austin, TX",
  "dropoff_location": "Denver, CO",
  "current_cycle_used": 12
}
```

### Optional fields

- `current_location` is optional. Default geolocation is Dallas, TX: `{ "lat": 32.7767, "lng": -96.797 }`.
- `current_cycle_used` is optional. Default is `0`.

Minimum body:

```json
{
  "pickup_location": { "lat": 30.2672, "lng": -97.7431 },
  "dropoff_location": { "lat": 39.7392, "lng": -104.9903 }
}
```

A successful response includes geocoded stops, the road route, duty events, map markers, daily logs, and a summary like:

```json
{
  "miles": 1112.0,
  "drive_hours": 20.1,
  "total_hours": 33.5,
  "days": 2,
  "fuel_stops": 1,
  "warnings": [
    "2 required 30-minute break(s).",
    "1 10-hour reset(s).",
    "1 fuel stop(s)."
  ]
}
```

Exact miles and hours depend on the live map route.

## Tests

```powershell
.\.venv\Scripts\python backend\manage.py test trips
```