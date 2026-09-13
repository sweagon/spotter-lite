"""the FMCSA hours-of-service rules Spotter plans against, kept in one place
so every violation message can quote the exact regulation instead of an
approximation.

These are the actual 49 CFR Part 395 texts (as of the 2022 HOS amendments).
We use them two ways:

1. The planner *designs a legal day* — the engine auto-inserts the required
   rest and restart, and
2. The duty-status endpoint *refuses* a self-declared status that would put
   the driver over a limit right now, quoting the exact rule and telling the
   driver why.

The caps here must stay in sync with `hos_engine.py` (the sim) and
`watch_hos.py` (the fleet watchdog) — any drift means the planner, the
record, and the alerts disagree about the rules.
"""

LIMITS = {
    "drive_11": {
        "title": "11-hour driving limit",
        "limit_hours": 11.0,
        "cite": "49 CFR § 395.3(a)(1)",
        "text": (
            "Except as provided in paragraph (b) of this section, no driver shall "
            "drive more than 11 hours following 10 consecutive hours off duty."
        ),
    },
    "duty_14": {
        "title": "14-hour duty window",
        "limit_hours": 14.0,
        "cite": "49 CFR § 395.3(a)(2)",
        "text": (
            "Except as provided in paragraph (b) of this section, no driver shall "
            "drive after having been on duty 14 or more hours following 10 "
            "consecutive hours off duty."
        ),
    },
    "cycle_70": {
        "title": "70-hour / 8-day cycle",
        "limit_hours": 70.0,
        "cite": "49 CFR § 395.3(b)(1)",
        "text": (
            "No motor carrier shall permit or require a driver to drive, nor shall "
            "any driver drive, after having been on duty 70 hours in any period of "
            "8 consecutive days."
        ),
    },
    "rest_10": {
        "title": "10-hour rest",
        "cite": "49 CFR § 395.2 (off-duty time; sleeper berth)",
        "text": (
            "\u201cOff-duty time\u201d includes any time when a driver is off duty for 10 "
            "consecutive hours or, alternatively, at least 10 consecutive hours in a "
            "sleeper berth. A driver may not drive after being on duty for 11 hours "
            "unless 10 consecutive hours off duty have been accumulated."
        ),
    },
}

# Long-horizon wins when several rules trip at once, so the message stays
# stable and doesn't bounce between regs across runs.
PRECEDENCE = ("cycle_70", "duty_14", "drive_11")


def cite(rule):
    """The regulation line for a rule key, e.g. cite("drive_11") returns the
    49 CFR § 395.3(a)(1) sentence with its citation prefixed."""
    entry = LIMITS[rule]
    return f'{entry["cite"]} \u2014 {entry["text"]}'


def violation(rule, current, limit, extra=""):
    """A human violation message: what was attempted, what the rule says, and
    the exact regulation text. `extra` is where callers slip in facts like
    `driving today: 11.6h`."""
    entry = LIMITS[rule]
    line = f'This put the driver over the {entry["title"].lower()} (had ~{current:.1f}h of {limit:.0f}h allowed).'
    if extra:
        line = f"{line} {extra}"
    return "\n".join([line, cite(rule)])