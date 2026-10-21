# FX Forecast Tool

Calibrated 1-day, 1-week and 1-month forecasts for **EUR/USD, USD/AMD and EUR/AMD**: a
central estimate with 50/80/95% probability bands, the drivers behind them, central bank
events, walk-forward backtests against a random walk, and a "Should I sell my EUR now?"
panel. Spec: [docs/SPEC.md](docs/SPEC.md).

**Live:** https://fx-forecast-eight.vercel.app

> Statistical estimate. Not financial advice. The bands are the forecast; the center line
> is not a promise.

## What it does

| | |
|---|---|
| Pairs | EUR/USD (ECB reference rate), USD/AMD and EUR/AMD (CBA daily average) |
| Horizons | 1, 5 and 21 trading days |
| Center models | Random walk, forward rate (covered interest parity), LightGBM |
| Bands | GARCH(1,1) Student-t, event widening for meetings inside the horizon, 1M empirical check, walk-forward calibration |
| Served model | The lowest-error model that beats the random walk (MAE ratio < 0.98 and Diebold-Mariano p < 0.10 over 250 days); otherwise the random walk with GARCH bands |
| Central banks | Fed, ECB and CBA: meeting calendars, decisions, surprises, statement diffs and hawkish scores |
| Sell indicator (FR-17) | Sell now / Wait / No clear edge, with the chance of a better rate, the risk of waiting and the interest difference. It leans only when a model has proven an edge. |
| AI view | Experimental. Gemini reads the same context daily. It is scored live only and decides the verdict only after 250 scored forecasts meet the promotion rule. |

## Architecture

```
GitHub Actions cron ──► fxf daily / hourly / weekly ──► Postgres (Neon) ◄── FastAPI (read-only) ◄── React dashboard
  ingest: Frankfurter, FRED, ECB Data Portal           7 tables              Vercel function        Vercel, same origin
  events: Fed/ECB RSS, cba.am, ARKA/Interfax, Atlanta Fed
  forecast → AI view (Gemini, optional) · weekly backtest
```

No job calls another job directly; every job reads and writes Postgres and records a
`job_runs` row. The API only reads.

| Path | Contents |
|---|---|
| `backend/src/fxf/ingest` | Rates and macro series, with point-in-time `published_at` |
| `backend/src/fxf/events` | Calendars, decisions, statements, diff, hawkish scorer |
| `backend/src/fxf/forecast`, `backtest` | Models, bands, calibration, selection, walk-forward backtest |
| `backend/src/fxf/ai` | Experimental Gemini AI view and its live track record |
| `backend/src/fxf/api` | FastAPI app, health and stale rules, sell indicator |
| `frontend/` | React, TypeScript, Vite and visx dashboard |

## Run it locally

```bash
docker compose up -d db
```

```bash
cd backend && uv sync && uv run fxf init-db && uv run fxf backfill
```

```bash
cd backend && uv run fxf weekly
```

```bash
cd frontend && npm ci && npm run build
```

```bash
cd backend && uv run fxf serve
```

Open http://localhost:8000. For frontend work, use `npm run dev` in `frontend/` on port
5173 (it proxies `/api` to 8000), or `npm run dev:mock` to work without a backend.

| Command | What it does |
|---|---|
| `fxf daily` | Ingest, events, forecast, then the AI view. Runs only on working days after 17:00 CET; `--force` overrides. |
| `fxf hourly` | Central bank RSS and news poll, and statement scoring (FR-05) |
| `fxf weekly` | Walk-forward backtest, then today's forecast with the new served models |
| `fxf backfill` | Full history for every source |
| `fxf ai` | The AI view only (needs `GEMINI_API_KEY`) |
| `fxf report` | Weekly Markdown report in `docs/reports/`: models, AI track record, pipeline health |
| `fxf status` | Recent job runs |
| `fxf worker` | APScheduler alternative to GitHub Actions cron |

## Deploy

- **Dashboard and API:** the Vercel project `fx-forecast`, with Root Directory `backend`.
  `backend/app.py` is the entrypoint, and `scripts/vercel_build.sh` builds the dashboard
  into the function. Redeploy with `vercel deploy --prod` from the repo root.
- **Database:** Neon Postgres (free, Frankfurt), provisioned through the Vercel
  Marketplace. Vercel injects `DATABASE_URL`, and `postgres://` URLs are normalised to
  psycopg 3.
- **Jobs:** GitHub Actions cron in `.github/workflows`. They skip until the secrets exist. The
  Saturday job commits a report to [docs/reports](docs/reports). That commit also keeps GitHub
  from disabling the schedules, which it does after 60 days without repository activity.

Add the repository secrets under GitHub → Settings → Secrets and variables → Actions:

| Secret | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Neon's pooled connection string, the same value Vercel has |
| `GEMINI_API_KEY` | no | Turns on the AI view and scores statements with Gemini. `FXF_AI_MODEL` (a repository variable) defaults to `gemini-3.8-flash`, with thinking at `high` (`FXF_AI_THINKING`). |
| `FRED_API_KEY` | no | FRED API instead of the public `fredgraph.csv` |
| `ANTHROPIC_API_KEY` | no | Claude hawkish scorer, used only when `GEMINI_API_KEY` is not set |
| `SLACK_WEBHOOK_URL` | no | Failure alerts (NFR-04) |

To copy the database URL from the Vercel-provisioned file without pasting it anywhere:

```bash
grep '^DATABASE_URL=' .env.vercel | cut -d= -f2- | tr -d '"' | gh secret set DATABASE_URL --repo Argishtyfirst/fx-forecast
```

## Tests

```bash
cd backend && uv run pytest
```

```bash
cd frontend && npm run typecheck && npm test && npm run test:e2e
```

The backend tests cover unit, contract (recorded fixtures), property (Hypothesis),
leakage, backtest regression (golden file) and integration levels. They use a
throwaway Postgres database per session. Acceptance tests are named after their
requirement, for example `test_fr03_ingest_is_idempotent`.

## Results (run 2026-10-21, last 250 trading days)

- **Served model:** the random walk everywhere. No model met the promotion rule; the
  closest was LightGBM at 1M with MAE ratio 0.97 and DM p 0.29. This is the usual finding
  for FX at these horizons.
- **80% band coverage:** 0.78–0.84 for every pair and horizon (target 75–85%), and about
  0.80 over 2010–2026.
- **Runtime:** the forecast takes about 2 s and the backtest about 50 s, well inside the
  18:00 CET deadline.

## Decisions and deviations from the spec

- **Hosting:** Vercel Hobby plus Neon plus GitHub Actions. Fly.io no longer has a free
  tier, and Render's free Postgres expires after 30 days. Neon runs Postgres 18; local
  dev and CI use 16.
- **Raw responses:** kept 30 days as GitHub Actions artifacts. Runners have no persistent
  disk.
- **Band calibration:** one factor per band level, from the trailing 500 origins with
  outcomes known by the cutoff, clamped to [0.5, 1.5]. It is applied after event widening.
- **Event widening:** applies at every horizon (FR-12). For the AMD pairs, meeting days
  are historically calmer than normal days, so the widening is zero; the meetings are
  still listed.
- **Modelling conventions:** τ = h/252 for covered interest parity. Rolling
  1000-trading-day windows for the AMD pairs. In the backtest, GARCH is refit every 21
  days and LightGBM every 63 days.
- **Point in time:** a feature is visible only if `published_at` is strictly before the
  cutoff (16:00 UTC on the run date). Decisions count from the next day.
- **Scorers:** without keys, FRED is read from `fredgraph.csv` and statements are scored
  by a deterministic lexicon (`lexicon@v1`).

## Known limitations

- The AI view is unproven until it has 250 scored live forecasts, about a year.
- On the 250-day window, 50% coverage misses ±5 points in four cells. Every cell is
  within 3 points over the full history.
- GitHub cron can start late at busy times, so four daily attempts are scheduled.
- Vercel Hobby is for personal, non-commercial use.

## Data sources

European Central Bank (reference rates, key rates, €STR, HICP via the ECB Data Portal) ·
Central Bank of Armenia (AMD rates, policy rates, Board decisions) · FRED, Federal Reserve
Bank of St. Louis (Fed target range, yields, dollar index, Brent) · Federal Reserve press
releases · Federal Reserve Bank of Atlanta Market Probability Tracker · Frankfurter (open
API for the ECB and CBA daily rates).
