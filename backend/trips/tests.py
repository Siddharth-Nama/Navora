import json

from django.test import Client, TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"])
class TripInputTests(TestCase):
    def setUp(self):
        self.client = Client()

    def post_plan(self, body):
        return self.client.post(
            "/api/trips/plan/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_missing_pickup_is_rejected(self):
        response = self.post_plan(
            {
                "dropoff_location": "Houston, TX",
                "current_cycle_used": 5,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("pickup_location", response.json()["error"])

    def test_cycle_hours_too_high(self):
        response = self.post_plan(
            {
                "pickup_location": "Austin, TX",
                "dropoff_location": "Houston, TX",
                "current_cycle_used": 80,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("current_cycle_used", response.json()["error"])

    def test_cycle_hours_negative(self):
        response = self.post_plan(
            {
                "pickup_location": "Austin, TX",
                "dropoff_location": "Houston, TX",
                "current_cycle_used": -1,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("current_cycle_used", response.json()["error"])

    def test_accepts_geolocation_coordinates(self):
        from trips.views import read_trip_input

        trip, error = read_trip_input(
            json.dumps(
                {
                    "pickup_location": {"lat": 30.2672, "lng": -97.7431},
                    "dropoff_location": "Denver, CO",
                    "current_cycle_used": 12,
                }
            ).encode()
        )
        self.assertIsNone(error)
        self.assertEqual(trip["pickup_location"]["lat"], 30.2672)
        self.assertEqual(trip["dropoff_location"], "Denver, CO")
        self.assertNotIn("current_location", trip)

    def test_missing_cycle_hours_defaults_to_zero(self):
        from trips.views import read_trip_input

        trip, error = read_trip_input(
            json.dumps(
                {
                    "pickup_location": "Austin, TX",
                    "dropoff_location": "Houston, TX",
                }
            ).encode()
        )
        self.assertIsNone(error)
        self.assertEqual(trip["current_cycle_used"], 0.0)

    def test_empty_pickup_is_rejected(self):
        response = self.post_plan(
            {
                "pickup_location": "   ",
                "dropoff_location": "Houston, TX",
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("pickup_location", response.json()["error"])

    def test_out_of_range_coordinates_are_rejected(self):
        response = self.post_plan(
            {
                "pickup_location": {"lat": 120, "lng": -97.7431},
                "dropoff_location": {"lat": 29.7604, "lng": -95.3698},
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("out of range", response.json()["error"])

    def test_same_pickup_and_dropoff_are_rejected(self):
        response = self.post_plan(
            {
                "pickup_location": {"lat": 30.2672, "lng": -97.7431},
                "dropoff_location": {"lat": 30.2672, "lng": -97.7431},
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be different", response.json()["error"])

    def test_malformed_json_is_rejected(self):
        response = self.client.post(
            "/api/trips/plan/",
            data="{bad",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON", response.json()["error"])

    def test_get_method_is_rejected(self):
        response = self.client.get("/api/trips/plan/")
        self.assertEqual(response.status_code, 405)

    def test_plan_url_works_without_trailing_slash(self):
        response = self.client.post(
            "/api/trips/plan",
            data=json.dumps(
                {
                    "pickup_location": "",
                    "dropoff_location": "Houston, TX",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("pickup_location", response.json()["error"])


class BreakRuleTests(TestCase):
    def test_thirty_minute_break_after_eight_hours_driving(self):
        from trips.planner import build_timeline

        distance = {
            "miles": 600,
            "minutes": 600,
            "legs": [{"miles": 600, "minutes": 600}],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        types = [event["type"] for event in events]
        self.assertIn("break", types)

        break_event = next(
            event for event in events if event["type"] == "break"
        )
        self.assertEqual(break_event["status"], "off_duty")
        self.assertAlmostEqual(break_event["end"] - break_event["start"], 0.5)


class DrivingLimitTests(TestCase):
    def test_driving_stops_at_eleven_hours(self):
        from trips.planner import build_timeline

        distance = {
            "miles": 900,
            "minutes": 900,
            "legs": [{"miles": 900, "minutes": 900}],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        types = [event["type"] for event in events]
        self.assertIn("reset", types)

        drive_before_reset = 0.0
        for event in events:
            if event["type"] == "reset":
                break
            if event["status"] == "driving":
                drive_before_reset += event["end"] - event["start"]
        self.assertLessEqual(drive_before_reset, 11.0 + 1e-6)
        self.assertGreater(drive_before_reset, 10.0)


class DutyWindowTests(TestCase):
    def test_duty_window_stops_at_fourteen_hours(self):
        from trips.planner import DriverClocks

        clocks = DriverClocks(0)
        clocks.add_drive(8)
        clocks.take_break()
        clocks.add_drive(2)
        clocks.add_on_duty(3.5)

        self.assertAlmostEqual(clocks.window, 14.0)
        self.assertTrue(clocks.hit_duty_window())
        self.assertEqual(clocks.stop_reason(), "duty_window")
        self.assertEqual(clocks.drive_until_limit(), 0.0)


class ResetTests(TestCase):
    def test_ten_hour_reset_opens_a_new_window(self):
        from trips.planner import DriverClocks

        clocks = DriverClocks(cycle_used=20)
        clocks.add_drive(11)
        self.assertTrue(clocks.hit_driving_limit())

        event = clocks.take_reset()
        self.assertEqual(event["type"], "reset")
        self.assertAlmostEqual(event["end"] - event["start"], 10.0)
        self.assertEqual(clocks.drive, 0.0)
        self.assertEqual(clocks.window, 0.0)
        self.assertEqual(clocks.since_break, 0.0)
        self.assertEqual(clocks.cycle, 31.0)
        self.assertEqual(clocks.drive_until_limit(), 8.0)


class CycleRestartTests(TestCase):
    def test_thirty_four_hour_restart_when_cycle_is_full(self):
        from trips.planner import DriverClocks, build_timeline

        clocks = DriverClocks(cycle_used=69)
        clocks.add_drive(1)
        self.assertTrue(clocks.hit_cycle())
        self.assertEqual(clocks.stop_reason(), "cycle")

        event = clocks.take_restart()
        self.assertEqual(event["type"], "restart")
        self.assertAlmostEqual(event["end"] - event["start"], 34.0)
        self.assertEqual(clocks.cycle, 0.0)
        self.assertEqual(clocks.drive, 0.0)
        self.assertEqual(clocks.drive_until_limit(), 8.0)

        distance = {
            "miles": 200,
            "minutes": 200,
            "legs": [{"miles": 200, "minutes": 200}],
        }
        events, _ = build_timeline(distance, cycle_used=70)
        types = [item["type"] for item in events]
        self.assertIn("restart", types)


class FuelStopTests(TestCase):
    def test_fuel_stop_near_each_thousand_miles(self):
        from trips.planner import build_timeline, fuel_stop_miles

        self.assertEqual(fuel_stop_miles(2500), [1000, 2000])
        self.assertEqual(fuel_stop_miles(900), [])

        distance = {
            "miles": 2200,
            "minutes": 2200,
            "legs": [{"miles": 2200, "minutes": 2200}],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        fuel_events = [
            event for event in events if event["type"] == "fuel"
        ]
        self.assertEqual(len(fuel_events), 2)
        self.assertAlmostEqual(fuel_events[0]["miles"], 1000, delta=1)
        self.assertAlmostEqual(fuel_events[1]["miles"], 2000, delta=1)
        for event in fuel_events:
            self.assertEqual(event["status"], "on_duty")
            self.assertAlmostEqual(event["end"] - event["start"], 0.5)


class PickupDropoffTests(TestCase):
    def test_pickup_and_dropoff_are_one_hour_each(self):
        from trips.planner import build_timeline

        distance = {
            "miles": 300,
            "minutes": 300,
            "legs": [{"miles": 300, "minutes": 300}],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        pickup = next(event for event in events if event["type"] == "pickup")
        dropoff = next(event for event in events if event["type"] == "dropoff")

        self.assertEqual(pickup["status"], "on_duty")
        self.assertEqual(dropoff["status"], "on_duty")
        self.assertAlmostEqual(pickup["end"] - pickup["start"], 1.0)
        self.assertAlmostEqual(dropoff["end"] - dropoff["start"], 1.0)
        self.assertLess(pickup["start"], dropoff["start"])


class MapTimeoutTests(TestCase):
    def test_map_timeout_uses_env_value(self):
        import os

        from trips.maps import map_timeout

        previous = os.environ.get("MAP_TIMEOUT_SECONDS")
        os.environ["MAP_TIMEOUT_SECONDS"] = "5"
        try:
            timeout = map_timeout()
            self.assertEqual(timeout.read, 5.0)
            self.assertEqual(timeout.connect, 3.0)
        finally:
            if previous is None:
                os.environ.pop("MAP_TIMEOUT_SECONDS", None)
            else:
                os.environ["MAP_TIMEOUT_SECONDS"] = previous


class EndToEndFlowTimingTests(TestCase):
    def test_flow_timing_and_external_calls(self):
        import time
        from unittest.mock import patch

        import httpx
        from trips import maps
        from trips.maps import (
            geocode_stops,
            point_at_mile,
            route,
            route_distance,
            route_geometry,
        )
        from trips.planner import build_timeline, split_daily_logs, summarize_trip
        from trips.views import read_trip_input

        maps._cache.clear()
        calls = []
        real_get = httpx.get

        def timed_get(*args, **kwargs):
            url = str(args[0] if args else kwargs.get("url", ""))
            started = time.perf_counter()
            response = real_get(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
            supplier = (
                "nominatim"
                if "nominatim" in url
                else "osrm"
                if "osrm" in url
                else "other"
            )
            calls.append({"supplier": supplier, "ms": elapsed_ms, "url": url[:120]})
            return response

        body = {
            "pickup_location": "Austin, TX",
            "dropoff_location": "Houston, TX",
            "current_cycle_used": 5,
        }

        with patch("trips.maps.httpx.get", side_effect=timed_get):
            maps._route_cache.clear()
            stages = {}

            t0 = time.perf_counter()
            trip, error = read_trip_input(json.dumps(body).encode())
            stages["validate_ms"] = (time.perf_counter() - t0) * 1000
            self.assertIsNone(error)

            t0 = time.perf_counter()
            stops, error = geocode_stops(trip)
            stages["geocode_ms"] = (time.perf_counter() - t0) * 1000
            self.assertIsNone(error)

            t0 = time.perf_counter()
            road, error = route(stops)
            stages["route_ms"] = (time.perf_counter() - t0) * 1000
            self.assertIsNone(error)

            t0 = time.perf_counter()
            distance = route_distance(road)
            geometry = route_geometry(road)
            events, clocks = build_timeline(distance, trip["current_cycle_used"])
            logs = split_daily_logs(events)
            summary = summarize_trip(events, distance, clocks)
            stages["planner_ms"] = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            for event in events:
                if event["status"] != "driving":
                    point_at_mile(geometry, event["miles"])
            stages["markers_ms"] = (time.perf_counter() - t0) * 1000

        stages["total_ms"] = sum(
            stages[key]
            for key in (
                "validate_ms",
                "geocode_ms",
                "route_ms",
                "planner_ms",
                "markers_ms",
            )
        )
        nominatim_calls = [call for call in calls if call["supplier"] == "nominatim"]
        osrm_calls = [call for call in calls if call["supplier"] == "osrm"]

        print("\n=== END-TO-END FLOW TIMING ===")
        for key, value in stages.items():
            print(f"{key}: {value:.1f}")
        print(f"nominatim_calls: {len(nominatim_calls)}")
        print(f"osrm_calls: {len(osrm_calls)}")
        print(f"summary: {summary}")
        print("=== END ===\n")

        self.assertEqual(len(nominatim_calls), 2)
        self.assertEqual(len(osrm_calls), 1)
        self.assertLess(stages["planner_ms"], 50)
        self.assertGreater(stages["geocode_ms"] + stages["route_ms"], stages["planner_ms"])

    def test_coordinates_skip_nominatim(self):
        from unittest.mock import patch

        import httpx
        from trips import maps
        from trips.maps import geocode_stops, route
        from trips.views import read_trip_input

        maps._cache.clear()
        calls = []
        real_get = httpx.get

        def count_get(*args, **kwargs):
            url = str(args[0] if args else kwargs.get("url", ""))
            calls.append(url)
            return real_get(*args, **kwargs)

        body = {
            "pickup_location": {"lat": 30.2672, "lng": -97.7431},
            "dropoff_location": {"lat": 29.7604, "lng": -95.3698},
            "current_cycle_used": 5,
        }

        with patch("trips.maps.httpx.get", side_effect=count_get):
            maps._route_cache.clear()
            trip, error = read_trip_input(json.dumps(body).encode())
            self.assertIsNone(error)
            stops, error = geocode_stops(trip)
            self.assertIsNone(error)
            road, error = route(stops)
            self.assertIsNone(error)

        nominatim = [url for url in calls if "nominatim" in url]
        osrm = [url for url in calls if "osrm" in url]
        print(f"\ncoords path: nominatim={len(nominatim)} osrm={len(osrm)}\n")
        self.assertEqual(len(nominatim), 0)
        self.assertEqual(len(osrm), 1)


class RouteErrorTests(TestCase):
    def setUp(self):
        from trips import maps

        maps._cache.clear()
        maps._route_cache.clear()
        self.client = Client()

    def test_route_timeout_returns_502(self):
        from unittest.mock import patch

        import httpx

        def raise_timeout(*args, **kwargs):
            raise httpx.TimeoutException("slow")

        with patch("trips.maps.httpx.get", side_effect=raise_timeout):
            response = self.client.post(
                "/api/trips/plan/",
                data=json.dumps(
                    {
                        "pickup_location": {"lat": 30.2672, "lng": -97.7431},
                        "dropoff_location": {"lat": 29.7604, "lng": -95.3698},
                    }
                ),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("timed out", response.json()["error"])

    def test_no_route_returns_400(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "NoRoute", "routes": []}

        with patch("trips.maps.httpx.get", return_value=mock_response):
            response = self.client.post(
                "/api/trips/plan/",
                data=json.dumps(
                    {
                        "pickup_location": {"lat": 30.2672, "lng": -97.7431},
                        "dropoff_location": {"lat": 29.7604, "lng": -95.3698},
                    }
                ),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("No road route", response.json()["error"])