# Spotter — fleet trip planner with FMCSA hours-of-service logs

A company-ready trip planning app for trucking. Enter the driver's current
location, pickup, dropoff, and how much of the 70-hour / 8-day cycle they've
already used — Spotter routes the drive, simulates the trip against the
federal hours-of-service rules, and generates the daily driver's logs
(49 CFR Part 395 format) for the whole trip, then runs the load through a
driver/dispatcher lifecycle with a watchdog that flags drivers approaching
or breaching their hours.

Live demo URLs (frontend on Vercel, API on Render) can be dropped in here
when pinned; for now it runs fully locally — see **Running locally** below.
No API keys required.

---

## What it does

**Org layer** (new)
- Role-based sign-in: **driver**, **dispatcher**, **admin**, **auditor**.
- Drivers: their own trips, live HOS position (cycle used, truck), open
  watchdog flags, and the **driver cab** — the home view: signal rest / driving
  / on-duty from `DutyEvent`, and the live RODS log sheet draws itself as you
  roll through the day.
- Dispatchers: the **load board** (create / assign / advance statuses),
  fleet roster, Drivers/Vehicles tabs with cycle-reset, and the **watchdog**
  alert queue.
- Auditors: a read-only **safety & compliance** view (`/safety`) with the
  fleet board, open HOS flags, and a **one-click compliance packet** — every
  drawn log sheet as a single PDF (`/api/export/logs.pdf`).
- Admin: the SPA **AdminConsole** (`/admin`) for full fleet CRUD — drivers
  and vehicles, with name, role, truck, CDL, cycle used, active status.
- Trips persist to Postgres with per-day logs; every status change is
  **audited per user** (`TripEvent`).
- The **HOS watchdog** (`manage.py watch_hos`, run hourly on Render): a
  planning guardrail that projects each driver's position from their declared
  cycle + latest live load and raises alerts for 11 / 14 / 70 / over-hours,
  debounced so a frequent cron can't spam the same fire.
- **OpenAPI**: interactive schema at `/api/schema/`, Swagger UI at `/api/docs/`.
- Django admin (`/admin/`) for users, drivers, vehicles, trips, alerts, events.

**Planner core** (unchanged strength)
1. **Geocodes** the three locations (Nominatim / OpenStreetMap).
2. **Routes** pickup → dropoff (OSRM public demo server) and returns distance,
   driving time, and the full shape of the route.
3. **Simulates the trip** minute-by-minute against the FMCSA rules and returns
   per-day log data that the frontend draws as daily graph-grid log sheets.
4. **Shows it all on one page**: the route on a Leaflet map with markers for
   every stop, an instrument cluster (peak driving / window / cycle), a stop
   timeline, and one SVG log sheet per day.
5. A stateless public calculator stays live at `/explore` (no login).

### HOS rules implemented (the `11/14/8/70/34` rules)

| Rule | Notes |
| --- | --- |
| **11-hour driving limit** | after 11 cumulative driving hours, a 10-hour rest is required |
| **14-hour duty window** | from the start of the shift, the driver must be done within 14 hours; the window keeps ticking through breaks (does not "pause") |
| **30-minute break** | required after 8 cumulative hours of driving; logged off-duty but still counts against the 14-hour window |
| **70-hour / 8-day cycle** | if the plan would push the driver over 70 used hours, a **34-hour restart** is inserted and the cycle resets to 0 |
| **Fuel stops** | forced every ~1,000 miles, logged as 40 minutes on-duty (not driving) |
| **Pickup / dropoff** | 1 hour each of on-duty (not driving) at each end |

Deliberately __not__ implemented: sleeper-berth splitting, the 16-hour
short-haul exemption, adverse-driving-condition +2 hours, and the 60/7
alternative window.

## How the HOS engine works

Everything lives in `backend/tripplanner/hos_engine.py`, a pure function module
with no Django imports — you can import it and call `plan_trip(...)` from a unit
test or a REPL without touching the web framework.

The engine walks the route in one-minute ticks and at each moment checks, in
priority order:

1. would the 70-hour cycle cap be exceeded? → insert a 34-hour restart
2. do we hit the 11-hour driving limit or the end of the 14-hour window? → 10-hour rest
3. have we driven 8 hours since the last break? → 30-minute break
4. have we driven past the next 1,000-mile mark? → fuel stop (once)

Rest and restarts are logged as **sleeper berth** (the FMCSA-valid way to
record a non-driving rest period in that row of the grid). Plans are sliced
into calendar days and each day is padded with off-duty time so every row on
every log sheet sums to 24 hours.

## Running locally

### Backend (Django + DRF)

```bash
cd backend
python3 -m venv venv            # or reuse the one at ../venv
source ../venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo      # demo users, password spotter123
python manage.py runserver 0.0.0.0:8000
```

Demo accounts: `dispatch` (dispatcher), `auditor` (auditor), `danton` /
`bmiles` (drivers), `admin` (superuser) — all password `spotter123`. The
full roster — two admins, three dispatchers, an auditor, and five drivers
on varied cycle balances — is seeded by `python manage.py seed_demo`.

The stateless calculator (public):

```bash
curl -X POST http://localhost:8000/api/trip/plan/ \
  -H "Content-Type: application/json" \
  -d '{"current_location":"Dallas, TX","pickup_location":"Dallas, TX","dropoff_location":"Houston, TX","current_cycle_used":30}'
```

The persisted planner (authenticated, dispatcher):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"dispatch","password":"spotter123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access'])")

curl -X POST http://localhost:8000/api/trips/plan/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"current_location":"Dallas, TX","pickup_location":"Dallas, TX","dropoff_location":"Houston, TX","current_cycle_used":42.5,"driver_id":1,"vehicle_id":1}'
```

API surface (all under `/api/`): `auth/login|refresh|logout`, `me`,
`duty` (GET current + POST events), `drivers` (+ `drivers/create`),
`drivers/<id>` (GET / PATCH admin-only), `drivers/<id>/reset-cycle`,
`vehicles` (+ POST admin-only) + `vehicles/<id>` (PATCH admin-only),
`trips` (+ `trips/plan`), `trips/<id>` (PATCH = guarded status transitions),
`alerts`, `alerts/<id>/resolve`, `export/logs.pdf` (compliance packet),
plus the public `trip/plan` and `geocode/suggest`, and `schema/` + `docs/`
(OpenAPI/Swagger).

Watchdog test:

```bash
python manage.py watch_hos
```

Run the test suite (**81 tests**: engine rules, API, auth, permissions, trip
persistence, watchdog + debounce, audit events, auditor read-only, PDF export,
duty events + reg safety, driver self-PATCH, admin CRUD):

```bash
python manage.py test tripplanner
```

Browser end-to-end smoke (**10 checks**: driver cab / live RODS, admin CRUD,
dispatcher tabs, auditor safety):

```bash
node frontend/e2e/smoke.mjs
```

Mobile viewport suite (**6 checks**, 390×844):

```bash
node frontend/e2e/mobile.mjs
```

### Frontend (React + Vite + Leaflet)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Unauthenticated visits land on `/login`;
`/explore` is the public calculator. Override the backend with
`VITE_API_BASE_URL` in a `.env` file if it's not at `http://localhost:8000`.

### Configuration (backend, via env vars)

| Var | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | sqlite (dev) | Postgres connection string in prod |
| `DJANGO_SECRET_KEY` | dev key (insecure) | set a real one in prod |
| `DJANGO_DEBUG` | `True` | set `False` in prod |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,...` | comma-separated |
| `CORS_ALLOWED_ORIGINS` | localhost + Vercel origins | comma-separated; add prod |

## Deployment

- **Backend** → Render. `backend/render.yaml` is a Blueprint: managed
  **Postgres**, the **API web service** (gunicorn, `/api/health/` — which now
  pings the DB), and an **hourly `watch_hos` cron**. Run `python manage.py
  seed_demo` once in the Render shell after first deploy. Full steps in
  `DEPLOY.md`.
- **Frontend** → Vercel. `vercel.json` points Vercel at the `frontend` folder;
  set `VITE_API_BASE_URL` to the Render URL.

Geocoding and routing happen on the backend so no API keys ever reach the
browser — both services are key-free anyway.

## How Spotter compares to spotter.ai and Synergy ELD

(Excluding the AI features both commercial products lead with, since Spotter has none.)

| Capability | **Spotter** | **spotter.ai** | **Synergy ELD** |
| --- | --- | --- | --- |
| HOS planning before dispatch | Yes — 11/14/70 trip simulation, per-day log sheets | TMS dating/appointment logic, not planning-grade RODS | Primarily tracking, not pre-dispatch planning |
| Live duty status in the cab | Yes — 4-state FMCSA duty log, 24h self-balancing RODS | Driver app records HOS once driving | Full ELD — GPS-linked, engine-linked events |
| Compliance paperwork | Auditor safety view + one-click 395.8 log-sheet PDF packet | App + integration-led | Built-in roadside inspection view |
| Fleet/watchdog alerts | Rule-based 70/11/14 watchdog flags, driver-facing | MVR/PSP *monitoring* (background checks) | ELD violation alerts + dashcam |
| Driver/dispatch roles | Role-scoped UI (driver cab, dispatch board, auditor) | Driver app + fleet dashboard | Fleet + driver portals |
| FMCSA hardware & licensing | **None** — planning-grade, no ELD certification | No hardware (app-based HOS assist) | **Yes** — certified devices installed per truck |
| Cost model | Runs anywhere (Django/Vite, no API keys) | SaaS subscription | Hardware + monthly per-truck fees |

Where Spotter punches above its size: the trip planner *designs a legal day*
before anyone leaves the yard (the 10/10 rule tests exist for precisely this),
the compliance packet is a single click, and the whole thing runs without a
single API key or installed device. The honest gap is the big one: neither
Spotter's duty log nor its watchdog is an FMCSA-certified ELD — a planning
*guardrail* today, not an auditable electronic record, which is exactly why
the roadmap's next step is a real GPS/ELD feed.

## Assumptions

- **US only.** Nominatim requests are restricted with `countrycodes=us`.
- The driver starts the clock at the moment of the request; first log day
  begins "today" at the server's local midnight.
- Current location vs. pickup: if they differ, the route is planned
  pickup → dropoff (the driver is assumed to be *at* the pickup).
- Fuel at ~1,000-mile intervals; stop coordinates interpolated along the route.
- Rest/restarts are single continuous sleeper-berth blocks.
- **The watchdog is a planning guardrail, not an audited ELD record** — it
  reasons from declared hours + the latest persisted plan. Real GPS/ELD feed is
  the stated next step.

## What I'd do differently with more time

- **Optimize the engine.** Minute-by-minute ticking is easy to verify but slow
  on very long routes; an event-based simulation would be near-instant.
- **Cache results.** Store geocode + route responses keyed by input so repeat
  trips don't hammer Nominatim/OSRM.
- **Robust geocoding.** Let the user pick from the top-N matches and set start
  date/time rather than assuming "now" and the first hit.
- **Rest coords.** Snap interpolated rest markers to nearby facilities.
- **Non-US support** via a country selector, plus the 60/7 cycle.

---

Built with Django + DRF, React + Vite, Leaflet, Nominatim, OSRM, Postgres, and
JWT auth — no API keys.