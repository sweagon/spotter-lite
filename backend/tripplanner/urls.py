from django.urls import path
from .views import TripPlanView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("trip/plan/", TripPlanView.as_view(), name="trip-plan"),
]
