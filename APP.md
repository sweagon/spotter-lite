# Spotter — app specification

**Spotter** — a single-company, internal HOS (hours-of-service) trip planner for fleet dispatchers and truck drivers. Give it current location, pickup, and drop-off; it routes the trip, simulates the drive minute-by-minute against federal duty rules, and outputs a compliant daily-log package (FMCSA 395.8 grid sheets + remarks + recap) with an hour-by-hour duty timeline. Built on a **Django 5.2 + DRF** backend (`backend/`) and a **React 19 + Vite** SPA (`frontend/`), styled with a bespoke petrol/coral/mint brand system.

## Version & build history

- **Version:** `0.0.0` (frontend `package.json`; backend has no version file) — i.e. **pre-1.0 internal prototype**. Deployable to Render (Postgres + API + hourly cron) and Vercel/static.
- **Build timeline:** all commits (12) are dated **2026-09-11** — one continuous build session across three eras:
  1. FMCSA engine + public assessment prototype.
  2. Brand redesign (petrol/coral/mint system, contrast-derived tokens).
  3. Company-ready org layer (auth, fleet, watchdog, log-grid fidelity) + this spec pass.

## Features & usage, complete

### 1. HOS engine (core)
- Real routeless simulation: takes route distance + driving time, walks a timeline minute-by-minute.
- Enforces the governor rules — **11-hr driving**, **14-hr on-duty window**, **30-min break before hour 8 driving**, **70-hr / 8-day cycle** with inter-day carry-over.
- Emits flat duty segments (`off duty / sleeper berth / driving / on duty not driving`) each with a **location string**, plus stop list (fuel, pickup, dropoff, break) and **peak statistical values** (driving/window/cycle) for the instrument gauges.
- Location interpolation from route geometry; auto mid-trip rests when needed.

### 2. Trip planning (stateless + persisted)
- **`/api/trip/plan/`** — public, stateless calculator: returns route, usage peaks, stops, and daily logs.
- **`/api/trips/plan/`** — persisted: dispatcher can assign any driver/vehicle (trip → `assigned`); a **driver can self-plan** onto their own truck (trip → `draft`, pending dispatcher approval).
- **`/api/suggest/`** — location autocomplete (Nominatim), with fallback to free-text.

### 3. Fleet & access
- Custom `User` with **roles admin / dispatcher / driver**; JWT login (rotated refresh tokens).
- **Drivers**: see only their own trips (404-hiding), their HOS position, own-vehicle-only planning, open watchdog alerts.
- **Dispatchers**: full fleet board — drivers, vehicles, all trips with **guarded status transitions** (`assigned → en route → stopped → delivered`, cancel) each recorded as a **`TripEvent` audit row** (who/when).
- **Admin**: Django admin for every model.
- Route guards in the SPA (`/login`, `/`, `/dispatch`, `/explore`); tokens in localStorage (documented trade-off).
- Demo seed: 10 test users (2 admin / 3 dispatcher / 5 drivers) on trucks D-1…D-5 with varied cycle balances — documented in `users.txt` (password `spotter123`).

### 4. HOS watchdog ("tracker agent")
- `manage.py watch_hos` — hourly planning guardrail projecting each driver's position from declared cycle + latest live plan; idempotent alerts for **drive-11 / duty-14 / cycle-70 / over-hours**, resolveable from the board; honest framing (planning-derived hours, not an ELD record) with an hourly cron in `render.yaml`.

### 5. Daily log sheets (the compliance output)
- Faithful FMCSA 395.8 grid: **4 fixed rows** (off duty / sleeper / driving / on-duty-not-driving) over a 0–1440 min axis; **25 full-height hour lines** labeled `midnight…noon…midnight`; **3 quarter-hour ticks per hour per row**, rows 1–2 hanging down / rows 3–4 rising up, `:30` longer than `:15/:45`.
- **One continuous step-function duty line**, connectors colored toward the status being entered.
- **Remarks lane** ticked + labeled (place names from engine) at every status change.
- **Ruled totals column** and a programmatic **checksum — the four totals must equal 24.00** (shown as `✓ 24.00` or a delta); compact shipping + 70-hr recap strip.
- Geometry lives in a pure module validated by 8 `node --test` cases, including a reproduction of the FMCSA reference example (10 + 1.75 + 7.75 + 4.5 = 24.00).

### 6. Presentation layer
- Shared `PlannerForm`/`PlanResults` render routes, maps, and logs identically across public demo, driver self-plan, and dispatch assign.
- **RouteMap** (Leaflet polyline, auto-fit, stop markers), **HoursCluster** gauges (driving/window/cycle peaks), **StopTimeline**, road-shield highway labels, geocoding autocomplete.
- **Full-width layout** (no content cap), brand tokens with contrast-derived shades, colorblind-friendly dash patterns on the log.

### 7. Ops & testing
- **Postgres** via `DATABASE_URL` (sqlite fallback), fail-closed CORS, throttling (`plan` 20/hr, `suggest` 60/min), `/api/health/` DB ping, whitenoise static serving.
- **37 Django tests** (engine + auth + permissions + persistence + watchdog + audit) and **8 frontend geometry spec tests** all passing; 20-point Playwright browser suite + live dispatcher/driver E2E with zero JS errors.

## Known limits (by design)
- Free OSRM/Nominatim (flaky under load), GPS/deadhead/load-tracking deferred, hours are **planning-derived, not ELD-certified**, single-company only.