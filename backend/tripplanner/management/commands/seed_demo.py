"""
seed_demo - idempotent demo data for local dev and the Render first-run.

creates every account in users.txt: an admin superuser, org admins,
dispatchers, drivers (each tied to a vehicle with a varied 70-hour cycle
balance) and a read-only auditor for the safety view. works with default
passwords so a reviewer (or the walkthrough) can log straight in; change
them in production.

    python manage.py seed_demo
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from tripplanner.models import Driver, Vehicle

User = get_user_model()

# (username, first, last, role, vehicle unit, vehicle type, cycle used)
ACCOUNTS = [
    ("admin", "Sasha", "Admin", "admin", None, None, None),
    ("test_admin", "Ari", "Test", "admin", None, None, None),
    ("dispatch", "Dana", "Dispatch", "dispatcher", None, None, None),
    ("kumar_d", "Kumar", "Diaz", "dispatcher", None, None, None),
    ("jrivera_d", "Jules", "Rivera", "dispatcher", None, None, None),
    ("auditor", "Avery", "Audit", "auditor", None, None, None),
    ("danton", "Dora", "Anton", "driver", "D-1", "sleeper", 42.5),
    ("bmiles", "Bryce", "Miles", "driver", "D-2", "sleeper", 12.0),
    ("rnavarro", "Rosa", "Navarro", "driver", "D-3", "sleeper", 8.5),
    ("twilson", "Tyrone", "Wilson", "driver", "D-4", "dryvan", 27.0),
    ("lkim", "Lauren", "Kim", "driver", "D-5", "sleeper", 55.0),
]


@transaction.atomic
class Command(BaseCommand):
    help = "create demo users, drivers and vehicles for first run"

    def add_arguments(self, parser):
        parser.add_argument("--password", default="spotter123",
                            help="password for every demo account")

    def handle(self, *args, **options):
        pw = options["password"]

        for username, first, last, role, unit, vtype, cycle in ACCOUNTS:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "first_name": first, "last_name": last},
            )
            user.role = role
            user.first_name = first
            user.last_name = last
            user.is_staff = role == "admin"
            user.is_superuser = role == "admin"
            user.set_password(pw)
            user.save()

            if unit:
                vehicle, _ = Vehicle.objects.get_or_create(
                    unit_no=unit, defaults={"vehicle_type": vtype}
                )
                profile, _ = Driver.objects.get_or_create(
                    user=user,
                    defaults={"vehicle": vehicle, "cycle_used": cycle},
                )
                if profile.vehicle_id is None:
                    profile.vehicle = vehicle
                profile.cycle_used = cycle
                profile.save()

        self.stdout.write(self.style.SUCCESS(
            "demo ready: "
            + ", ".join(f"{u[0]} ({u[3]})" for u in ACCOUNTS)
            + f" (password: {pw})"
        ))