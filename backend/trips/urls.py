from django.urls import path

from trips.views import health

urlpatterns = [
    path("health/", health, name="health"),
]
