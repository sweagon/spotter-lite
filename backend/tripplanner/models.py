from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """auth user for the org tool. role drives what the API exposes."""

    ROLE_CHOICES = (
        ("driver", "Driver"),
        ("dispatcher", "Dispatcher"),
        ("admin", "Admin"),
        # read-only safety/audit role: can inspect the fleet board, saved
        # trips, alerts and export compliance PDFs — never mutates.
        ("auditor", "Auditor"),
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="driver",
        help_text="Role gates API surface: drivers see only their own trips.",
    )
    home_terminal = models.CharField(max_length=120, blank=True, default="")

    def __str__(self):
        return self.username

    @property
    def is_dispatcher(self):
        # mutations flow through this check, so auditor stays read-only.
        return self.role in ("dispatcher", "admin")

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_auditor(self):
        return self.role == "auditor"

    @property
    def can_manage_fleet(self):
        # read-side fleet access (board, alerts, exports): dispatch staff
        # and the read-only auditor can all see it; drivers cannot.
        return self.role in ("dispatcher", "admin", "auditor")


class Vehicle(models.Model):
    """a truck/unit in the fleet. dispatched to a driver on a trip."""

    unit_no = models.CharField(max_length=20, unique=True)
    vin = models.CharField(max_length=17, blank=True, default="")
    vehicle_type = models.CharField(
        max_length=40,
        choices=(
            ("sleeper", "Sleeper"),
            ("daycab", "Day Cab"),
            ("dryvan", "Dry Van"),
            ("reefer", "Reefer"),
            ("flatbed", "Flatbed"),
        ),
        default="sleeper",
    )
    current_odometer = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["unit_no"]

    def __str__(self):
        return self.unit_no


class Driver(models.Model):
    """fleet driver. user (login) + hos profile + the truck they're driving."""

    user = models.OneToOneField(
        "User", on_delete=models.CASCADE, related_name="driver_profile"
    )
    vehicle = models.OneToOneField(
        "Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="driver",
    )
    cdl_number = models.CharField(max_length=30, blank=True, default="")
    # a planning guardrail, kept in sync by the watchdog + trip planner:
    # hours used toward the 70/8 before this driver's next trip.
    cycle_used = models.FloatField(default=0.0)
    last_cycle_reset = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Trip(models.Model):
    """a planned/assigned load. the planner's snapshot is stored so the
    original plan is re-openable even after the load has run."""

    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("assigned", "Assigned"),
        ("en_route", "En Route"),
        ("stopped", "Stopped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    )

    created_by = models.ForeignKey(
        "User", on_delete=models.PROTECT, related_name="created_trips"
    )
    driver = models.ForeignKey(
        "Driver",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="trips",
        db_index=True,
    )
    vehicle = models.ForeignKey(
        "Vehicle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="trips",
        db_index=True,
    )

    current_location = models.CharField(max_length=200)
    pickup_location = models.CharField(max_length=200)
    dropoff_location = models.CharField(max_length=200)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True
    )

    # snapshot of what the planner produced at plan time
    distance_miles = models.FloatField(default=0)
    driving_minutes = models.FloatField(default=0)
    usage = models.JSONField(default=dict, blank=True)
    route_geometry = models.JSONField(default=list, blank=True)
    highways = models.JSONField(default=list, blank=True)
    stops = models.JSONField(default=list, blank=True)
    # current cycle balance the plan was built against
    cycle_used_planned = models.FloatField(default=0)

    actual_pickup_at = models.DateTimeField(null=True, blank=True)
    actual_delivery_at = models.DateTimeField(null=True, blank=True)
    actual_miles = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pickup_location} -> {self.dropoff_location} ({self.status})"


class DailyLog(models.Model):
    """one persisted 'graph day' generated by the planner for a trip.
    kept so a driver can pull up yesterday's sheets without re-planning."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="daily_logs")
    day_number = models.PositiveIntegerField()
    date = models.DateField()
    segments = models.JSONField()
    totals = models.JSONField()

    class Meta:
        ordering = ["trip", "day_number"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "day_number"], name="uniq_log_per_trip_day")
        ]

    def __str__(self):
        return f"{self.trip} day {self.day_number}"


class TripEvent(models.Model):
    """audit trail: who moved a load from one status to another, and when."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="events", db_index=True)
    user = models.ForeignKey(
        "User", on_delete=models.PROTECT, related_name="trip_events"
    )
    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["at"]

    def __str__(self):
        return f"#{self.trip_id} {self.from_status}->{self.to_status} by {self.user}"


class Alert(models.Model):
    """watchdog output: a driver crossing an HOS planning guardrail."""

    RULE_CHOICES = (
        ("drive_11", "Daily drive 11h"),
        ("duty_14", "Daily duty 14h"),
        ("cycle_70", "Cycle 70h"),
        ("over_hours", "Over hours"),
    )
    driver = models.ForeignKey(
        "Driver", on_delete=models.CASCADE, related_name="alerts", db_index=True
    )
    rule = models.CharField(
        max_length=20, choices=RULE_CHOICES, db_index=True
    )
    detail = models.CharField(max_length=255, blank=True, default="")
    triggered_at = models.DateTimeField(db_index=True)
    cleared = models.BooleanField(default=False)
    cleared_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True
    )
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]

    def __str__(self):
        return f"{self.driver} {self.rule}@{self.triggered_at}"