from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Alert, Driver, Trip, Vehicle

User = get_user_model()


class TripPlanRequestSerializer(serializers.Serializer):
    """payload for the planner — the three places + the driver's cycle used.
    extended with an optional driver/vehicle so a dispatcher can persist the
    plan as an assigned trip."""

    current_location = serializers.CharField(max_length=200)
    pickup_location = serializers.CharField(max_length=200)
    dropoff_location = serializers.CharField(max_length=200)
    current_cycle_used = serializers.FloatField(min_value=0, max_value=70)
    driver_id = serializers.IntegerField(required=False, allow_null=True)
    vehicle_id = serializers.IntegerField(required=False, allow_null=True)


class UserSummarySerializer(serializers.ModelSerializer):
    role = serializers.CharField(source="get_role_display")

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "role", "home_terminal"]


class VehicleSerializer(serializers.ModelSerializer):
    # empty-string-ish formatting so the unit shows cleanly in dropdowns
    label = serializers.SerializerMethodField()
    assigned_driver = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "unit_no",
            "vin",
            "vehicle_type",
            "current_odometer",
            "active",
            "label",
            "assigned_driver",
        ]
        read_only_fields = ["id", "created_at"]

    def get_label(self, obj):
        return f"{obj.unit_no} · {obj.get_vehicle_type_display()}"

    def get_assigned_driver(self, obj):
        d = getattr(obj, "driver", None)
        return d.user.username if d else None


class DriverSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    vehicle_unit = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            "id",
            "user",
            "vehicle_unit",
            "cdl_number",
            "cycle_used",
            "active",
        ]
        read_only_fields = ["id"]

    def get_vehicle_unit(self, obj):
        return obj.vehicle.unit_no if obj.vehicle_id else None


class AlertSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            "id",
            "driver_name",
            "rule",
            "detail",
            "triggered_at",
            "cleared",
            "cleared_at",
        ]

    def get_driver_name(self, obj):
        return str(obj.driver)


class TripSerializer(serializers.ModelSerializer):
    driver = DriverSerializer(read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    daily_logs = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            "id",
            "created_by_username",
            "driver",
            "vehicle",
            "current_location",
            "pickup_location",
            "dropoff_location",
            "status",
            "status_label",
            "distance_miles",
            "driving_minutes",
            "usage",
            "highways",
            "stops",
            "route_geometry",
            "daily_logs",
            "cycle_used_planned",
            "actual_pickup_at",
            "actual_delivery_at",
            "actual_miles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_daily_logs(self, obj):
        return [
            {
                "day_number": log.day_number,
                "date": log.date.isoformat(),
                "segments": log.segments,
                "totals": log.totals,
            }
            for log in obj.daily_logs.all()
        ]