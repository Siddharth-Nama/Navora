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