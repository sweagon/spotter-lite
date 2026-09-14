# Deploy runbook — how to ship Spotter from this machine

You'll need: a GitHub account, a Render account, and a Vercel account.
All configs are already committed in the repo (`render.yaml`, `vercel.json`,
env-var handling in `backend/spotter_backend/settings.py` and
`frontend/src/api.js`).

## 1. Push to GitHub (do this first — Render & Vercel deploy from GitHub)

```bash
cd /home/morpheus/Projects/spotter
# create an empty repo on github.com first (no README/gitignore — we already have both)
git remote add origin git@github.com:YOUR_USERNAME/spotter.git
git push -u origin main
```

The render blueprint creates three things in one go: a Postgres database,
the API web service, and the hourly HOS-watchdog cron.

## 2. Backend on Render (blueprint)

1. Render dashboard → **New → Blueprint** → pick the GitHub repo → it reads
   `render.yaml` automatically.
2. Confirm the three resources it creates:
   - **spotter-db** (Postgres, free)
   - **spotter-backend** (web service)
   - **spotter-hos-watch** (scheduled `0 * * * *`)
3. After the first build, run the one-time seed so there are accounts to log
   into. In the Render dashboard, **spotter-backend → Shell**, then:
   ```bash
   python manage.py seed_demo
   ```
   (creates `admin` / `dispatch` / `danton` / `bmiles`, each password
   `spotter123`. If the seed ran but the build is mid-migration, run
   `python manage.py migrate` first.)
4. In Render, add the frontend origin to CORS: set the env var
   `CORS_ALLOWED_ORIGINS` on **spotter-backend** to
   `https://spotter-trip-planner.vercel.app` (once Vercel exists) and redeploy.
   The blueprint already sets this to both known Vercel origins.
5. Verify: open `https://spotter-backend.onrender.com/api/health/` →
   should return `{"status":"ok","database":"ok"}`.

> Never set `DJANGO_CORS_ALLOW_ALL=True` in prod — protected org endpoints
> come CORS-locked by default now.

## 3. Frontend on Vercel

1. Vercel dashboard → **New Project** → import your GitHub repo.
2. **Root directory**: `frontend` (Vercel reads `vercel.json` which sets this,
   but pick it in the UI too).
3. **Build command**: leave as detected (`npm install && npm run build`).
4. **Output directory**: `dist`.
5. Add an environment variable:
   - `VITE_API_BASE_URL` = `https://spotter-backend.onrender.com`
6. Deploy. You'll get `https://spotter-<something>.vercel.app`.

## 4. Final checks

- Open the Vercel URL → `/` redirects to the **sign-in** screen.
- Log in as `dispatch / spotter123` → the dispatcher board; open the seeded
  trip, advance statuses, plan + assign a new load.
- Log in as `danton / spotter123` → driver home with the HOS position, alerts,
  and that driver's trip list.
- Watchdog: assign a load with a high cycle to a driver, then run
  `python manage.py watch_hos` from the Render shell — the dispatcher board's
  **watchdog** rail shows the new alert. The hourly cron keeps it fresh.
- Public demo still live at `/explore` (no login): `Dallas, TX` →
  `Houston, TX` → expect ~238 mi and 2 log sheets.

## If you hit trouble

- **WATCHDOG / seed DB not connected** — confirm `DATABASE_URL` env var is set
  on both services (blueprint wires it from `spotter-db`).
- **Backend 500 / log shows geo/routing errors** — public Nominatim/OSRM can be
  flaky; the app returns clear errors and it's a free-tier constraint. Retry.
- **CORS errors in the browser** — the frontend origin must be in
  `CORS_ALLOWED_ORIGINS` on Render. Add the final Vercel URL and redeploy
  (do **not** enable the allow-all fallback).
- **Log sheet times look off** — the engine starts the trip at server local
  time; on Render UTC, so a trip planned "now" starts at UTC now. A real fleet
  tool would let you pick a start time (see README).
- **Health check failing** — Render hits `/api/health/` with GET; confirm that
  URL returns 200 (it now also pings the database, so a broken DB will show
  `"database":"unreachable"`)