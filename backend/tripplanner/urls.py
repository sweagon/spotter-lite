from django.urls import path
from .views import TripPlanView, HealthView, SuggestView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("geocode/suggest/", SuggestView.as_view(), name="geocode-suggest"),
    path("trip/plan/", TripPlanView.as_view(), name="trip-plan"),
]
