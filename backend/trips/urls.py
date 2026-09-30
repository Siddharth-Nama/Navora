from django.urls import path

from trips.views import health, plan_trip

urlpatterns = [
    path("health/", health, name="health"),
    path("health", health),
    path("trips/plan/", plan_trip, name="plan-trip"),
    path("trips/plan", plan_trip),
]
