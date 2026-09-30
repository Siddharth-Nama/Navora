from django.urls import path

from trips.views import health, plan_trip

urlpatterns = [
    path("health/", health, name="health"),
    path("trips/plan/", plan_trip, name="plan-trip"),
]