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

    def test_missing_current_location_uses_default(self):
        from trips.views import DEFAULT_CURRENT_LOCATION, read_trip_input

        trip, error = read_trip_input(
            json.dumps(
                {
                    "pickup_location": "Austin, TX",
                    "dropoff_location": "Houston, TX",
                }
            ).encode()
        )
        self.assertIsNone(error)
        self.assertEqual(trip["current_location"]["lat"], DEFAULT_CURRENT_LOCATION["lat"])
        self.assertEqual(trip["current_location"]["lng"], DEFAULT_CURRENT_LOCATION["lng"])
        self.assertEqual(trip["current_cycle_used"], 0.0)

    def test_cycle_hours_too_high(self):
        response = self.post_plan(
            {
                "current_location": "Dallas, TX",
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
                "current_location": "Dallas, TX",
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
                    "current_location": {"lat": 32.7767, "lng": -96.797},
                    "pickup_location": {"lat": 30.2672, "lng": -97.7431},
                    "dropoff_location": "Denver, CO",
                    "current_cycle_used": 12,
                }
            ).encode()
        )
        self.assertIsNone(error)
        self.assertEqual(trip["current_location"]["lat"], 32.7767)
        self.assertEqual(trip["current_location"]["lng"], -96.797)
        self.assertEqual(trip["pickup_location"]["lat"], 30.2672)
        self.assertEqual(trip["dropoff_location"], "Denver, CO")

    def test_missing_cycle_hours_defaults_to_zero(self):
        from trips.views import read_trip_input

        trip, error = read_trip_input(
            json.dumps(
                {
                    "current_location": {"lat": 32.7767, "lng": -96.797},
                    "pickup_location": "Austin, TX",
                    "dropoff_location": "Houston, TX",
                }
            ).encode()
        )
        self.assertIsNone(error)
        self.assertEqual(trip["current_cycle_used"], 0.0)


class BreakRuleTests(TestCase):
    def test_thirty_minute_break_after_eight_hours_driving(self):
        from trips.planner import build_timeline

        distance = {
            "miles": 600,
            "minutes": 600,
            "legs": [
                {"miles": 100, "minutes": 100},
                {"miles": 500, "minutes": 500},
            ],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        labels = [event["label"] for event in events]
        self.assertIn("30-minute break", labels)

        break_event = next(
            event for event in events if event["label"] == "30-minute break"
        )
        self.assertEqual(break_event["status"], "off_duty")
        self.assertAlmostEqual(break_event["end"] - break_event["start"], 0.5)


class DrivingLimitTests(TestCase):
    def test_driving_stops_at_eleven_hours(self):
        from trips.planner import build_timeline

        distance = {
            "miles": 900,
            "minutes": 900,
            "legs": [
                {"miles": 100, "minutes": 100},
                {"miles": 800, "minutes": 800},
            ],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        labels = [event["label"] for event in events]
        self.assertIn("10-hour reset", labels)

        drive_before_reset = 0.0
        for event in events:
            if event["label"] == "10-hour reset":
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
        self.assertEqual(event["label"], "10-hour reset")
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
        self.assertEqual(event["label"], "34-hour cycle restart")
        self.assertAlmostEqual(event["end"] - event["start"], 34.0)
        self.assertEqual(clocks.cycle, 0.0)
        self.assertEqual(clocks.drive, 0.0)
        self.assertEqual(clocks.drive_until_limit(), 8.0)

        distance = {
            "miles": 200,
            "minutes": 200,
            "legs": [
                {"miles": 50, "minutes": 50},
                {"miles": 150, "minutes": 150},
            ],
        }
        events, _ = build_timeline(distance, cycle_used=70)
        labels = [item["label"] for item in events]
        self.assertIn("34-hour cycle restart", labels)


class FuelStopTests(TestCase):
    def test_fuel_stop_near_each_thousand_miles(self):
        from trips.planner import build_timeline, fuel_stop_miles

        self.assertEqual(fuel_stop_miles(2500), [1000, 2000])
        self.assertEqual(fuel_stop_miles(900), [])

        distance = {
            "miles": 2200,
            "minutes": 2200,
            "legs": [
                {"miles": 200, "minutes": 200},
                {"miles": 2000, "minutes": 2000},
            ],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        fuel_events = [
            event for event in events if event["label"].startswith("Fuel stop")
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
            "legs": [
                {"miles": 100, "minutes": 100},
                {"miles": 200, "minutes": 200},
            ],
        }
        events, _clocks = build_timeline(distance, cycle_used=0)
        pickup = next(event for event in events if event["label"] == "Pickup")
        dropoff = next(event for event in events if event["label"] == "Dropoff")

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
            self.assertEqual(map_timeout(), 5.0)
        finally:
            if previous is None:
                os.environ.pop("MAP_TIMEOUT_SECONDS", None)
            else:
                os.environ["MAP_TIMEOUT_SECONDS"] = previous