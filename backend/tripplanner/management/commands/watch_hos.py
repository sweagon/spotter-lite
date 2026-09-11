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
the WATCH_HOS_FIRE_MINUTES setting (env, default 20) adds a debounce window:
no (driver, rule) fires twice inside one window even across clear/refire, so
the job can be scheduled every few minutes in production without spamming.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Prefetch
from django.utils import timezone

from tripplanner import duty
from tripplanner.models import Alert, Driver, Trip

DRIVE_LIMIT = 11.0
WINDOW_LIMIT = 14.0
CYCLE_LIMIT = 70.0
# how close to a limit counts as "about to be" (planning intent, not a rule)
WARN_MARGIN = 2.0

logger = logging.getLogger("tripplanner.watch_hos")


class Command(BaseCommand):
    help = "flag drivers projected to breach HOS planning guardrails"

    def handle(self, *args, **options):
        fired = 0
        window = getattr(settings, "WATCH_HOS_FIRE_MINUTES", 20)
        since = timezone.now() - timezone.timedelta(minutes=window)

        # a (driver, rule) is "quiet" if any alert — open or recently cleared —
        # exists inside the debounce window.
        recent_cases = set(
            Alert.objects.filter(triggered_at__gte=since)
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

            # hours a driver actually logged driving today (self-declared
            # duty events) — the watchdog treats that as real on top of the
            # plan projection, so an already-driving driver can't be handed
            # another full load.
            actual_today = duty.today_driving_hours(driver)
            drive_pos = actual_today
            if actual_today > 0:
                detail.append(f"actual {actual_today:.1f}h driving today")

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

                drive_pos += projected_drive
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
                if (driver.id, rule) in recent_cases:
                    continue  # inside the debounce window, don't re-fire
                Alert.objects.create(
                    driver=driver,
                    rule=rule,
                    detail=" ".join(detail) + f" | {msg}",
                    triggered_at=timezone.now(),
                )
                recent_cases.add((driver.id, rule))
                fired += 1
                logger.warning(
                    "watch_hos alert driver=%s rule=%s window_min=%d fired=%s :: %s",
                    driver.user.username, rule, window, msg, "|".join(detail),
                )

        logger.info("watch_hos run driver_count=%d fired=%d", drivers.count(), fired)
        self.stdout.write(self.style.SUCCESS(f"[watch_hos] raised {fired} new alert(s)"))