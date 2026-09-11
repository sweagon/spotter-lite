from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AlertListView,
    AlertResolveView,
    CreateDriverView,
    DriverDetailView,
    DriverListView,
    ExportLogsPDFView,
    HealthView,
    LoginView,
    LogoutView,
    MeView,
    SuggestView,
    TripDetailView,
    TripListView,
    TripPlanPersistView,
    TripPlanView,
    VehicleListView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("geocode/suggest/", SuggestView.as_view(), name="geocode-suggest"),

    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="me"),

    path("drivers/", DriverListView.as_view(), name="driver-list"),
    path("drivers/create/", CreateDriverView.as_view(), name="driver-create"),
    path("drivers/<int:pk>/", DriverDetailView.as_view(), name="driver-detail"),
    path("vehicles/", VehicleListView.as_view(), name="vehicle-list"),

    path("trips/", TripListView.as_view(), name="trip-list"),
    path("trips/plan/", TripPlanPersistView.as_view(), name="trip-plan-persist"),
    path("trips/<int:pk>/", TripDetailView.as_view(), name="trip-detail"),

    # the public, stateless calculator
    path("trip/plan/", TripPlanView.as_view(), name="trip-plan"),

    path("alerts/", AlertListView.as_view(), name="alert-list"),
    path("alerts/<int:pk>/resolve/", AlertResolveView.as_view(), name="alert-resolve"),

    path("export/logs.pdf", ExportLogsPDFView.as_view(), name="export-logs-pdf"),
]