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

    def test_missing_current_location(self):
        response = self.post_plan(
            {
                "pickup_location": "Austin, TX",
                "dropoff_location": "Houston, TX",
                "current_cycle_used": 5,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("current_location", response.json()["error"])

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