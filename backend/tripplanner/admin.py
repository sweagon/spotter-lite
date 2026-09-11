from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Alert, Driver, DutyEvent, Trip, TripEvent, User, Vehicle


@admin.register(User)
class SpotterUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    fieldsets = UserAdmin.fieldsets + (("Org", {"fields": ("role", "home_terminal")}),)


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("user", "vehicle", "cycle_used", "active")
    list_filter = ("active",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "cdl_number")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("unit_no", "vehicle_type", "current_odometer", "active")
    list_filter = ("vehicle_type", "active")
    search_fields = ("unit_no", "vin")


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pickup_location",
        "dropoff_location",
        "driver",
        "vehicle",
        "status",
        "created_by",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("pickup_location", "dropoff_location", "driver__user__username")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("driver", "rule", "triggered_at", "cleared", "cleared_by")
    list_filter = ("rule", "cleared")
    search_fields = ("driver__user__username",)


@admin.register(TripEvent)
class TripEventAdmin(admin.ModelAdmin):
    list_display = ("trip", "user", "from_status", "to_status", "at")
    list_filter = ("to_status",)
    search_fields = ("trip__pickup_location", "user__username")


@admin.register(DutyEvent)
class DutyEventAdmin(admin.ModelAdmin):
    list_display = ("driver", "status", "started_at", "ended_at", "location")
    list_filter = ("status",)
    search_fields = ("driver__user__username", "location")