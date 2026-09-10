# Spotter — trip planner with FMCSA hours-of-service logs

A full-stack trip planning app for trucking. Enter the driver's current
location, pickup, dropoff, and how much of the 70-hour / 8-day cycle they've
already used — Spotter routes the drive and generates the daily driver's
logs (49 CFR Part 395 format) for the whole trip.

Live demo: **TODO-frontend-url** · API: **TODO-backend-url**

---

## What it does

1. **Geocodes** the three locations (Nominatim / OpenStreetMap).
2. **Routes** pickup → dropoff (OSRM public demo server) and returns distance,
   driving time, and the full shape of the route.
3. **Simulates the trip** minute-by-minute against the FMCSA rules and returns
   per-day log data that the frontend draws as daily graph-grid log sheets.
4. **Shows it all on one page**: the route on a Leaflet map with markers for
   every stop, a stop list, summary stats, and one SVG log sheet per day.

There's no database, no accounts, no persistence. One POST, one response.

### HOS rules implemented (the `11/14/8/70/34` rules)

| Rule | Notes |
| --- | --- |
| **11-hour driving limit** | after 11 cumulative driving hours, a 10-hour rest is required |
| **14-hour duty window** | from the start of the shift, the driver must be done within 14 hours; the window keeps ticking through breaks (does not “pause”) |
| **30-minute break** | required after 8 cumulative hours of driving; logged off-duty but still counts against the 14-hour window |
| **70-hour / 8-day cycle** | if the plan would push the driver over 70 used hours, a **34-hour restart** is inserted and the cycle resets to 0 |
| **Fuel stops** | forced every ~1,000 miles, logged as 40 minutes on-duty (not driving) |
| **Pickup / dropoff** | 1 hour each of on-duty (not driving) at each end |

Deliberately __not__ implemented: sleeper-berth splitting, the 16-hour
short-haul exemption, adverse-driving-condition +2 hours, and the 60/7
alternative window. The scope of this task only asks for the rules above.

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
record a non-driving rest period in that row of the grid). The trip plan then
gets sliced into calendar days; each day is padded with off-duty time
(midnight → first activity, last activity → midnight) so every row on every log
sheet sums to 24 hours — which is what the grid shows, and what inspectors read.

The minute-by-minute approach makes the reasoning easy to audit but slow for
long routes (a 2,800-mile trip is ~5,000 simulated minutes). Within those
limits it's fine for a single request. See “What I'd do differently” below.

## Running locally

### Backend (Django + DRF)

```bash
cd backend
python3 -m venv venv            # or reuse the one at ../venv
source ../venv/bin/activate
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
```

API base: `http://localhost:8000`. Test it:

```bash
curl -X POST http://localhost:8000/api/trip/plan/ \
  -H "Content-Type: application/json" \
  -d '{"current_location":"Dallas, TX","pickup_location":"Dallas, TX","dropoff_location":"Houston, TX","current_cycle_used":30}'
```

Run the test suite (12 tests, including a long trip that triggers a recent
restart):

```bash
python manage.py test tripplanner
```

### Frontend (React + Vite + Leaflet)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The app targets `http://localhost:8000` by
default; override with `VITE_API_BASE_URL` in a `.env` file if your backend
lives elsewhere.

### Configuration (backend, via env vars)

| Var | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | dev key (insecure) | set a real one in prod |
| `DJANGO_DEBUG` | `True` | set `False` in prod |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,...` | comma-separated |
| `DJANGO_CORS_ALLOW_ALL` | `""` (off) | `True` allows any frontend origin |

## Deployment

- **Backend** → Render. `backend/render.yaml` is a Blueprint: Web Service,
  Python, free tier, `gunicorn spotter_backend.wsgi`, `/api/health/` health
  check, auto-generated secret key.
- **Frontend** → Vercel. `vercel.json` points Vercel at the `frontend` folder
  and builds with Vite; set `VITE_API_BASE_URL` to the Render URL as an
  environment variable.

Geocoding and routing happen on the backend so no API keys ever reach the
browser — both services are key-free anyway.

## Assumptions

- **US only.** Nominatim requests are restricted with `countrycodes=us`.
- The driver starts the clock at the moment of the request; the first log day
  begins "today" at the server's local midnight (times shown in local/naive
  time from the server).
- Current location vs. pickup: if they differ, the route is still planned
  pickup → dropoff (the driver is assumed to be *at* the pickup). In practice
  route both legs if you want an accurate deadhead.
- A truck burns fuel around every 1,000 miles; stops and rest break coordinates
  are interpolated along the route shape so the map markers sit on the road.
- When the 70-hour cap trips mid-shift, we start the 34-hour restart
  immediately and resume the *remaining* trip after it — cycle resets to 0.
- Breaks/rest are single continuous blocks (no sleeper splitting), which is
  valid Federal representation of this plan.
- Rest periods are logged as sleeper berth since this app is about OTR
  long-haul trucking.

## What I'd do differently with more time

- **Optimize the engine.** Minute-by-minute ticking is easy to verify but slow
  on very long routes. I'd collapse the timeline into event-based jumps
  (compute the next boundary analytically instead of stepping to it) — same
  output, near-instant.
- **Cache results.** Store geocode + route responses keyed by input so repeat
  trips don't hammer Nominatim/OSRM (both are polite-to-fair-use services).
- **Robust geocoding.** Let the user pick from the top-N matches and edit the
  trip's start date/time rather than assuming "now" and the first hit.
- **Determine rest coords properly.** The interpolation places a marker on the
  straight segment; a real system would snap it to nearby facilities and the
  exact road position.
- **Non-US support** via a country selector, and the 60/7 cycle option for
  carriers that run under it.

---

Built with Django + DRF, React + Vite, Leaflet, Nominatim, and OSRM — no API
keys, no database, no signups.