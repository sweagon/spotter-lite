# Deploy runbook — how to ship Spotter from this machine

You'll need: a GitHub account, a Render account, and a Vercel account.
All configs are already committed in the repo (`backend/render.yaml`,
`vercel.json`, env-var handling in `backend/spotter_backend/settings.py` and
`frontend/src/App.jsx`).

## 1. Push to GitHub (do this first — Render & Vercel deploy from GitHub)

```bash
cd /home/morpheus/Projects/spotter
# create an empty repo on github.com first (no README/gitignore — we already have both)
git remote add origin git@github.com:YOUR_USERNAME/spotter.git
git push -u origin main
```

## 2. Backend on Render

1. Render dashboard → **New → Blueprint** (easiest, uses `backend/render.yaml`)
   or **New → Web Service**.
2. If using a Web Service instead of Blueprint:
   - Connect your GitHub repo.
   - **Root directory**: `backend`
   - **Build command**: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - **Start command**: `gunicorn spotter_backend.wsgi:application --bind 0.0.0.0:$PORT --workers 2`
   - **Plan**: Free.
   - **Health check path**: `/api/health/`
3. Env vars (Blueprint sets these for you except two):
   - `DJANGO_SECRET_KEY` — add any long random string (Blueprint auto-generates it)
   - `DJANGO_DEBUG` = `False`
   - `DJANGO_ALLOWED_HOSTS` = `spotter-backend.onrender.com,*.onrender.com,localhost,127.0.0.1`
     (keep this in sync with the actual service name Render gives you)
   - `DJANGO_CORS_ALLOW_ALL` = `True`
4. Deploy, wait for "live". Note your backend URL, e.g. `https://spotter-backend.onrender.com`.
5. Verify: open `https://spotter-backend.onrender.com/api/health/` → should return `{"status":"ok"}`.

> The public OSRM demo server and Nominatim are polite-to-fair-use. A free-tier
> Render instance is fine for a demo/assessment.

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

- Short trip: `Dallas, TX` → `Dallas, TX` → `Houston, TX`, cycle 30
  → expect ~238 mi, 2 log sheets.
- Long trip: `Los Angeles, CA` → `Los Angeles, CA` → `New York, NY`, cycle 60
  → expect 6 log sheets, a 34-hour restart on day 1–2, fuel stops, every day
  totaling 24.0.
- Open the Vercel URL, plan a trip, confirm map tiles, markers, and log sheets
  all render (CORS is permissive on the backend so the frontend origin is fine).

## If you hit trouble

- **Backend 500 / log shows geo/routing errors** — public Nominatim/OSRM can be
  flaky; the app returns clear errors and it's a free-tier constraint. Retry.
- **CORS errors in the browser** — confirm `DJANGO_CORS_ALLOW_ALL=True` on
  Render and redeploy.
- **Log sheet times look off** — the engine starts the trip at server local
  time; on Render UTC, so a trip planned "now" starts at UTC now. A real product
  would let you pick a start time (see README).
- **Health check failing** — Render hits `/api/health/` with GET; confirm that
  URL returns 200 on your deployed host.