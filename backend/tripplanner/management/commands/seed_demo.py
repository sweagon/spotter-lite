"""
seed_demo - idempotent demo data for local dev and the Render first-run.

creates: an admin (superuser), a dispatcher, and two drivers each tied to a
vehicle. works with default passwords so a reviewer (or the walkthrough) can
log straight in; change them in production.

    python manage.py seed_demo
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from tripplanner.models import Driver, Vehicle

User = get_user_model()


@transaction.atomic
class Command(BaseCommand):
    help = "create demo users, drivers and vehicles for first run"

    def add_arguments(self, parser):
        parser.add_argument("--password", default="spotter123",
                            help="password for every demo account")

    def handle(self, *args, **options):
        pw = options["password"]

        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "role": "admin",
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Sasha",
                "last_name": "Admin",
            },
        )
        admin.set_password(pw)
        admin.save()

        disp, _ = User.objects.get_or_create(
            username="dispatch",
            defaults={"role": "dispatcher", "first_name": "Dana", "last_name": "Dispatch"},
        )
        disp.set_password(pw)
        disp.save()

        seed_drivers = [
            ("danton", "Dora", "Anton", "D-1", "sleeper", 42.5),
            ("bmiles", "Bryce", "Miles", "D-2", "sleeper", 12.0),
        ]
        for username, first, last, unit, vtype, cycle in seed_drivers:
            driver_user, created = User.objects.get_or_create(
                username=username,
                defaults={"role": "driver", "first_name": first, "last_name": last},
            )
            driver_user.set_password(pw)
            driver_user.save()
            vehicle, _ = Vehicle.objects.get_or_create(
                unit_no=unit, defaults={"vehicle_type": vtype}
            )
            profile, _ = Driver.objects.get_or_create(
                user=driver_user,
                defaults={"vehicle": vehicle, "cycle_used": cycle},
            )
            if profile.vehicle_id is None:
                profile.vehicle = vehicle
                profile.cycle_used = cycle
                profile.save()

        self.stdout.write(self.style.SUCCESS(
            f"demo ready: admin / dispatch / {[d[0] for d in seed_drivers]} (password: {pw})"
        ))