"""
watch_hos - the "tracker agent".

a periodic guardrail job that projects each active driver's hours-of-service
position from what the org actually knows (their declared cycle balance plus
the most recent persisted plan) and raises alerts when a 49 cfr limit is
breached or about to be.

honest framing: with no ELD/hardware feed, this is a *planning guardrail*,
not an audited hours record. it exists so a dispatcher learns that a driver
scheduled for a long load is going to be over-hours before the load is
assigned, not after. run it on a cron (Render schedules jobs on the free
tier):

    python manage.py watch_hos

alerts are idempotent: an open alert for the same driver+rule is not re-fired,
and a cleared alert can fire again if the condition is still true next time.
"""

from django.core.management.base import BaseCommand
from django.db.models import Prefetch
from django.utils import timezone

from tripplanner.models import Alert, Driver, Trip

DRIVE_LIMIT = 11.0
WINDOW_LIMIT = 14.0
CYCLE_LIMIT = 70.0
# how close to a limit counts as "about to be" (planning intent, not a rule)
WARN_MARGIN = 2.0


class Command(BaseCommand):
    help = "flag drivers projected to breach HOS planning guardrails"

    def handle(self, *args, **options):
        fired = 0
        open_cases = set(
            Alert.objects.filter(cleared=False)
            .values_list("driver_id", "rule")
        )

        drivers = Driver.objects.filter(active=True).select_related("user").prefetch_related(
            Prefetch(
                "trips",
                queryset=Trip.objects.filter(status__in=["en_route", "stopped"]),
                to_attr="live_trips",
            )
        )

        for driver in drivers:
            # the authority for today: the most recent live planned load, if any.
            last = None
            if driver.live_trips:
                last = max(driver.live_trips, key=lambda t: t.created_at)

            cycle_pos = driver.cycle_used
            drive_pos = 0.0
            window_pos = 0.0
            detail = []

            if last is not None:
                usage = last.usage if isinstance(last.usage, dict) else {}
                projected_drive = usage.get("driving_hours", 0.0) or 0.0
                projected_window = usage.get("window_hours", 0.0) or 0.0
                projected_cycle = usage.get("cycle_hours", 0.0) or 0.0

                # a fresh trip plan starts from the *declared* cycle balance;
                # if that has moved since, re-project the peak onto reality.
                if last.cycle_used_planned:
                    delta = driver.cycle_used - last.cycle_used_planned
                    projected_cycle += delta

                drive_pos = projected_drive
                window_pos = projected_window
                cycle_pos = max(cycle_pos, projected_cycle)
                detail.append(
                    f"last live load #{last.id} projects "
                    f"{projected_drive:.1f}/{projected_window:.1f}/{projected_cycle:.1f} h"
                )

            hits = []
            if drive_pos > DRIVE_LIMIT:
                hits.append(("drive_11", f"{drive_pos:.1f}h driving vs 11h limit"))
            elif drive_pos > DRIVE_LIMIT - WARN_MARGIN:
                hits.append(("drive_11", f"{drive_pos:.1f}h driving — within 2h of the 11h limit"))
            if window_pos > WINDOW_LIMIT:
                hits.append(("duty_14", f"{window_pos:.1f}h duty vs 14h limit"))
            elif window_pos > WINDOW_LIMIT - WARN_MARGIN:
                hits.append(("duty_14", f"{window_pos:.1f}h duty — within 2h of the 14h limit"))
            if cycle_pos > CYCLE_LIMIT:
                hits.append(("cycle_70", f"{cycle_pos:.1f}h cycle vs 70h limit"))
            if last is not None and driver.cycle_used + drive_pos > CYCLE_LIMIT:
                hits.append(("over_hours", f"declared {driver.cycle_used:.1f}h + planned {drive_pos:.1f}h drive"))

            for rule, msg in hits:
                if (driver.id, rule) in open_cases:
                    continue  # already flagged, don't spam
                Alert.objects.create(
                    driver=driver,
                    rule=rule,
                    detail=" ".join(detail) + f" | {msg}",
                    triggered_at=timezone.now(),
                )
                open_cases.add((driver.id, rule))
                fired += 1
                self.stdout.write(f"[watch_hos] {driver.user.username}: {rule} — {msg}")

        self.stdout.write(self.style.SUCCESS(f"[watch_hos] raised {fired} new alert(s)"))