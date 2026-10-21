# FX Forecast Tool Spec

Oct 21, 2026 · @Argishti Stepanyan

## Overview

The tool forecasts EUR/USD, USD/AMD, and EUR/AMD for 1 day, 1 week, and 1 month ahead. It shows a central estimate with calibrated probability bands. It does not promise an exact rate.

**Goals**

- Give a calibrated range for each pair and horizon.
- Show the drivers of each forecast: rate differentials, central bank events, and volatility.
- For someone converting the base currency (for example selling EUR for AMD), say whether the evidence favours converting now, waiting, or neither, with a confidence level (FR-17).
- Prove the value of each model against a random walk baseline in walk-forward backtests.

**Non-goals**

- Order execution or financial advice. The FR-17 indicator is a statistical summary of the forecast and its backtest evidence, not advice, and it leans only when a model beats the random walk.
- Intraday or tick-level forecasts.
- Paid data sources in version 1.

**Success criteria**

- The 80% band contains the actual rate on 75% to 85% of the last 250 trading days, per pair and horizon.
- At 1 week and 1 month, the central estimate MAE is equal to or lower than the random walk MAE.
- The daily pipeline completes before 18:00 CET on each working day.

## Scope

Version 1 covers three pairs, three horizons, and three central banks, with daily data only.

| Item | Version 1 |
| --- | --- |
| Currency pairs | EUR/USD, USD/AMD, EUR/AMD |
| Horizons | 1 trading day, 5 trading days, 21 trading days |
| Data frequency | Daily reference rates |
| Output | Central estimate, 50/80/95% bands, driver breakdown |
| Central banks | Fed (FOMC), ECB (Governing Council), CBA (Board) |
| Users | Single user, no authentication |

EUR/USD uses the ECB reference rate. USD/AMD and EUR/AMD use the CBA daily average rates (the CBA publishes EUR/AMD directly, so it is not derived as a cross). The sources fix at different times, so the model treats each pair as a separate daily series.

## Functional requirements

Each requirement has an ID. Each acceptance test in the test plan references one ID.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-01 | On each working day, the system fetches the latest EUR/USD, USD/AMD, and EUR/AMD rates. | Given a working day, when the job runs after 17:00 CET, then the database holds that day's rate for every pair. |
| FR-02 | On first run, the system loads the full history for every pair. | The row count for each pair equals the count in the source time series response. |
| FR-03 | Ingest is idempotent. | When the job runs twice for the same date, the database holds one row per pair and date. |
| FR-04 | The system fetches macro series from FRED, the ECB Data Portal, and the CBA on each working day. | Each series stores its value and its publication date. |
| FR-05 | The system records each central bank decision as one event. | When a bank publishes a decision, the event row exists within 2 hours. |
| FR-06 | The system stores the full statement text and a diff against the previous statement of the same bank. | The diff shows added and removed sentences. |
| FR-07 | The system scores each statement from -1 (dovish) to +1 (hawkish). | Each score stores the scorer model name and prompt version. |
| FR-08 | After ingest, the system produces forecasts for each pair and horizon. | 9 served forecast rows (3 pairs × 3 horizons) exist for each run date. |
| FR-09 | Each forecast includes 50%, 80%, and 95% bands. | The quantiles are in ascending order. |
| FR-10 | The system always produces a random walk forecast beside each model forecast. | Each run date has a random walk row for each pair and horizon. |
| FR-11 | For each pair and horizon, the system serves the model with the lowest rolling backtest error. | If no model beats the random walk, the system serves the random walk center with GARCH bands. |
| FR-12 | When a central bank meeting falls inside the horizon, the system widens the bands and flags the meeting. | The forecast response lists each meeting date inside the horizon. |
| FR-13 | The system runs a walk-forward backtest each week. | The run stores metrics per pair, horizon, and model. |
| FR-14 | The dashboard shows a fan chart for each pair. | The chart shows 90 days of history and the bands for all 3 horizons. |
| FR-15 | The dashboard shows the drivers of each forecast. | The panel shows the rate differential, forward rate, last surprise, hawkish score, and volatility. |
| FR-16 | When a source fails, the dashboard shows a stale data warning. | The warning shows the last successful update time for that source. |
| FR-17 | For each pair and horizon, the dashboard answers "Should I sell my <base> now?" with "sell now", "wait", or "no clear edge", the probability of a better rate if you wait, the 1-in-10 downside, and a confidence level. | The answer is "no clear edge" unless the served model meets the promotion rule and its directional hit rate is above 50%. Confidence comes from the hit rate and the size of the edge. The disclaimer is shown. |

## Data sources and ingestion

All version 1 sources are free. Only FRED needs an API key.

| Source | Data | Access | Schedule |
| --- | --- | --- | --- |
| [Frankfurter, ECB provider](https://frankfurter.dev/providers/ecb/) | EUR/USD reference rate, 1999 to now | Free, no key | Daily, 17:00 CET |
| [Frankfurter, CBA provider](https://frankfurter.dev/providers/cba/) | USD/AMD, EUR/AMD, and RUB/AMD daily average, 2000 to now | Free, no key | Daily, 17:00 CET |
| FRED | DFEDTARU, DFEDTARL, DFF, FEDTARMD, DGS2, DCOILBRENTEU, DTWEXBGS | Free, API key | Daily |
| ECB Data Portal | Deposit facility rate, €STR, HICP | Free, no key | Daily |
| CBA website | Refinancing, Lombard repo, and deposit rates | Free, scraping | After each Board meeting |
| [Fed RSS feeds](https://federalreserve.gov/feeds) | Monetary policy press releases, speeches | Free | Hourly poll |
| ECB RSS feeds | Press releases, press conferences | Free | Hourly poll |
| [Atlanta Fed Market Probability Tracker](https://www.atlantafed.org/RSS.aspx) | Market-implied Fed rate path | Free, download | Daily |
| ARKA, Interfax | CBA decision news, fallback source | Free, scraping | Hourly on CBA meeting days |

Example requests:

```
GET https://api.frankfurter.dev/v2/rate/EUR/USD?providers=ECB
GET https://api.frankfurter.dev/v2/rate/USD/AMD?providers=CBA
```

**Ingestion rules**

- Each job retries 3 times with exponential backoff.
- Each row stores `fetched_at` and, for macro data, `published_at`.
- Each raw response is stored for 30 days for replay and debugging.
- A schema check rejects responses with an unknown shape. The job then fails and sends an alert.

## Central bank events

The model uses the surprise of each decision, not the decision itself. The market already prices expected decisions.

| Bank | Meetings per year | Decision and text source | Expected value in version 1 | Main pair |
| --- | --- | --- | --- | --- |
| Fed (FOMC) | 8 | RSS, then statement, minutes, and projections pages | Atlanta Fed market-implied path | EUR/USD, USD/AMD |
| ECB (Governing Council) | 8 | RSS, then statement, press conference, and accounts pages | Previous rate (no change) | EUR/USD |
| CBA (Board) | About 8 | cba.am press release, ARKA and Interfax fallback | Previous rate (no change) | USD/AMD |

**Rules**

- The system stores the published meeting calendar for each bank at least 6 months ahead.
- The surprise equals the actual rate minus the expected rate, in basis points.
- For the CBA, the event stores all 3 rates: refinancing, Lombard repo, and deposit.
- The statement diff compares sentences with the previous statement of the same bank.
- The LLM scorer gets the statement and the diff. It returns a score from -1 to +1 and a one-line reason.
- When the scorer model or prompt changes, the system scores all historical statements again.

**Features for the model**

- Days until the next meeting, per bank.
- Surprise and hawkish score of the last meeting, per bank.
- Rate differentials: Fed minus ECB for EUR/USD, CBA minus Fed for USD/AMD, CBA minus ECB for EUR/AMD.

## Forecasting models

The system builds each forecast from a center model and a band model. All models predict the log return over the horizon, then convert it to a rate.

| Horizon | Center candidates | Bands |
| --- | --- | --- |
| 1 day | Random walk, LightGBM | GARCH |
| 1 week | Random walk, forward rate, LightGBM | GARCH with event widening |
| 1 month | Random walk, forward rate, LightGBM | GARCH with event widening, empirical quantile check |

**Random walk.** The center equals the last known rate. Every other model must beat it in backtests.

**Forward rate.** The center uses covered interest parity with policy rates as a proxy for money market rates:

```latex
F_{t,h} = S_t \cdot \frac{1 + i_{quote}\,\tau}{1 + i_{base}\,\tau}
```

τ is the horizon in years. For EUR/USD, the base rate is the ECB deposit rate and the quote rate is the Fed target midpoint. For USD/AMD, the base rate is the Fed target midpoint and the quote rate is the CBA refinancing rate. For EUR/AMD, the base rate is the ECB deposit rate and the quote rate is the CBA refinancing rate.

**GARCH bands.** A GARCH(1,1) model with Student-t errors runs on daily log returns. The horizon variance is the sum of the daily variance forecasts. The bands use the Student-t quantiles of that variance.

**Event widening.** For each bank, the system calculates the ratio of realized variance on meeting days to normal days. When a meeting falls inside the horizon, the system adds that extra variance.

**LightGBM.** One model per pair and horizon predicts the log return. Features:

- Lagged returns over 1, 5, 21, and 63 days.
- Realized volatility over 5 and 21 days.
- Rate differentials and their 21-day change.
- Central bank features from the events section.
- DTWEXBGS, Brent, and US 2-year yield changes.
- RUB/AMD return, for the AMD pairs only.

**AMD pair notes.** The CBA manages the float, and the series has regime breaks, for example in 2022. The model trains on a rolling window and uses Student-t errors for jumps.

## Evaluation and backtesting

A model goes live only when it beats the random walk in a walk-forward backtest. The backtest uses only data that was public at forecast time.

**Method**

1. Train on all data up to day t.
2. Forecast day t + h.
3. Move forward 1 trading day and repeat.
4. Use `published_at` for every feature. A value that was published after day t is not visible on day t.

**Metrics per pair, horizon, and model**

| Metric | What it measures | Target |
| --- | --- | --- |
| MAE ratio vs random walk | Center accuracy | Below 1.00 |
| Directional hit rate | Correct sign of the return | Above 50% |
| Band coverage at 50/80/95% | Band calibration | Within 5 points of nominal |
| Pinball loss | Quality of all quantiles | Lower than GARCH-only bands |
| Diebold-Mariano p-value | Significance vs random walk | Below 0.10 |

**Promotion rule.** A model replaces the served model when its MAE ratio is below 0.98 and its Diebold-Mariano p-value is below 0.10 over the last 250 trading days.

**Windows.** Each weekly run reports the last 250 trading days and the full history.

## Architecture

Scheduled Python jobs write all data and forecasts to one Postgres database. The API and frontend only read from it.

&#91;embedded content: system architecture · 9 components, 1 database\]

The forecast engine and the backtest runner read rates and features from Postgres, then write their outputs back. No job calls another job directly.

| Layer | Choice |
| --- | --- |
| Backend language | Python 3.12 |
| API | FastAPI |
| Database | Postgres 16, SQLAlchemy, Alembic |
| Models | statsmodels, arch, LightGBM |
| Ingest | httpx, feedparser, BeautifulSoup |
| LLM scoring | Gemini (the AI view's model, gemini-3.8-flash, free tier); Claude API as fallback, then a deterministic lexicon |
| Scheduler | GitHub Actions cron (APScheduler `fxf worker` as the alternative) |
| Frontend | React, TypeScript, Vite, visx for the fan chart |
| Hosting | Vercel Hobby (dashboard and API), Neon Postgres via the Vercel Marketplace, GitHub Actions cron for jobs (all free tiers; Fly.io no longer has a free tier and Render's free Postgres expires after 30 days) |

## Data model

Postgres holds 7 tables. Rates and quantiles use `NUMERIC(18,8)`. All timestamps are UTC.

| Table | Primary key | Main columns | Purpose |
| --- | --- | --- | --- |
| `rates` | pair, date | rate, source, fetched\_at | Daily rate history |
| `macro_series` | series\_id, date | value, source, published\_at, fetched\_at | Point-in-time macro data |
| `cb_meetings` | bank, date | scheduled, source\_url | Meeting calendar |
| `cb_events` | id | bank, date, rate\_type, rate\_before, rate\_after, expected, surprise\_bps, statement\_url, statement\_text, statement\_diff, hawkish\_score, scorer\_version | Decisions and text |
| `forecasts` | id | run\_date, pair, horizon\_days, model, center, q025, q10, q25, q75, q90, q975, served, meetings\_in\_horizon, git\_sha, features\_json | All model outputs |
| `backtest_metrics` | run\_date, pair, horizon\_days, model, window | mae, mae\_ratio\_rw, hit\_rate, cov50, cov80, cov95, pinball, dm\_pvalue | Backtest results |
| `job_runs` | id | job, started\_at, finished\_at, status, rows\_written, error | Pipeline health |

The `forecasts` table keeps every model output, not only the served one. This lets the backtest compare models on the same dates.

## API

A read-only REST API serves the frontend. Pair IDs use the form `EURUSD`, `USDAMD`, and `EURAMD`.

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/pairs` | Supported pairs and horizons |
| GET | `/api/rates/{pair}?from=&to=` | Daily rate history |
| GET | `/api/forecasts/{pair}/latest` | Served forecast for all horizons, with drivers and the FR-17 signal |
| GET | `/api/forecasts/{pair}?run_date=` | All model outputs for one run date |
| GET | `/api/backtests/{pair}?horizon=` | Backtest metrics per model |
| GET | `/api/events?bank=&from=` | Central bank decisions and upcoming meetings |
| GET | `/api/health` | Last successful run per job and source |

Example response for `/api/forecasts/EURUSD/latest`:

```json
{
  "pair": "EURUSD",
  "as_of": "2026-10-21",
  "spot": 1.1600,
  "horizons": [
    {
      "days": 21,
      "model": "forward",
      "center": 1.1619,
      "bands": { "50": [1.1460, 1.1780], "80": [1.1300, 1.1900], "95": [1.1150, 1.2080] },
      "meetings": [{ "bank": "ECB", "date": "2026-10-29" }],
      "drivers": { "rate_diff_bps": 200, "garch_vol_annual": 0.07, "last_surprise_bps": { "FED": 0, "ECB": 0 } }
    }
  ],
  "stale_sources": []
}
```

The values in the example are for illustration only.

## Frontend

The frontend is a React and TypeScript single-page app with 4 views. The bands are the main visual element, not the center line.

| View | Content | Requirements |
| --- | --- | --- |
| Pair | "Sell <base> now?" panel per horizon. Fan chart with 90 days of history and 50/80/95% bands for 3 horizons. Horizon cards with the center and the 80% range. Upcoming meetings inside each horizon. | FR-12, FR-14, FR-17 |
| Drivers | Rate differential, forward rate, GARCH volatility, last surprise, and hawkish score per bank. Served model name per horizon. | FR-11, FR-15 |
| Events | List of past decisions and upcoming meetings for the Fed, ECB, and CBA. Statement diff and score for each decision. | FR-05, FR-06, FR-07 |
| Backtest | Band coverage, MAE ratio, and hit rate per model and horizon, against the targets. | FR-13 |

**Rules**

- Each view shows the last update time per source and the stale data warning from FR-16.
- Each forecast shows this text: "Statistical estimate. Not financial advice."
- The app supports light and dark mode and works on a 380 px wide screen.

## Non-functional requirements

| ID | Area | Requirement |
| --- | --- | --- |
| NFR-01 | Freshness | Forecasts for the current day are available by 18:00 CET on each working day. |
| NFR-02 | Reproducibility | Each forecast stores the git SHA, model version, and feature snapshot. Random seeds are fixed. |
| NFR-03 | Point-in-time data | No feature uses a value with `published_at` later than the forecast cutoff. |
| NFR-04 | Reliability | A failed job sends an alert to a Slack webhook or email. The last good forecast stays visible. |
| NFR-05 | Observability | Each job logs structured JSON and exposes duration, rows written, and status as metrics. |
| NFR-06 | Security | API keys live in environment secrets only. The system stores no personal data. |
| NFR-07 | Cost | Hosting stays on free tiers. LLM scoring costs less than 1 USD per month. |
| NFR-08 | Attribution | The dashboard credits the ECB, the CBA, FRED, and Frankfurter as data sources. |

## Test plan

Development is test-first. Each FR and NFR gets a failing acceptance test before the implementation starts.

| Level | What it checks | Tools |
| --- | --- | --- |
| Unit | Source parsers, forward rate formula, GARCH horizon variance, surprise calculation, trading-day calendars for TARGET2, US, and Armenian holidays | pytest |
| Contract | Each external response matches its expected schema. An unknown shape fails the test. | pydantic, recorded fixtures |
| Property | Quantiles are in ascending order. Event widening never makes a band narrower. The center sits inside the 50% band. | Hypothesis |
| Leakage | No feature timestamp is at or after the forecast cutoff. | pytest on a fixed historical date |
| Backtest regression | Metrics on a frozen dataset stay within a set tolerance after each change. | pytest, golden files |
| Integration | One full daily run on recorded fixtures writes the expected rows in all tables. | pytest, Postgres in Docker |
| Frontend | The fan chart renders bands, meetings, and the stale warning. | Vitest, Testing Library, Playwright |

Each acceptance test name starts with its requirement ID, for example `test_fr03_ingest_is_idempotent`.

## Milestones

Each milestone ends with a working, deployed slice. The order puts the baselines before any ML.

1. **Data foundation.** Rate backfill, daily ingest, Postgres schema, job runs, and `/api/health`. Exit: FR-01 to FR-04 and FR-16 pass.
2. **Baselines.** Random walk, forward rate, GARCH bands, and the backtest runner. Exit: FR-08 to FR-10 and FR-13 pass, with a coverage report for both pairs.
3. **Central bank events.** Calendars, decisions, RSS readers, CBA scraper, and the surprise calculation. Exit: FR-05 and FR-12 pass.
4. **Frontend version 1.** Pair, Events, and Backtest views. Exit: FR-14 and FR-16 pass in Playwright.
5. **ML layer.** LightGBM features, model selection, and the promotion rule. Exit: FR-11 passes. A model goes live only if it meets the promotion rule.
6. **Statement text.** Statement diff and LLM score as features, and the Drivers view. Exit: FR-06, FR-07, and FR-15 pass. The backtest shows whether the score adds value.

## Risks and open questions

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Frankfurter stops or changes its API | No new rates | Self-host Frankfurter in Docker, or read the ECB and CBA sources directly |
| CBA website changes its layout | No CBA decisions | ARKA and Interfax fallback, contract tests that fail loudly |
| USD/AMD regime break | Bands too narrow | Rolling training window, Student-t errors, coverage alert below 70% |
| Overfitting or data leakage | Backtest looks better than reality | Walk-forward only, point-in-time data, promotion rule |
| Users read the center as a promise | Bad decisions | Bands first in the UI, disclaimer on each forecast |
| LLM scores drift after a model change | Inconsistent feature | Store scorer version, score all history again on change |

**Open questions**

- [ ] ECB expected value: keep "no change", or derive it from the €STR forward curve?
- [x] What time does Frankfurter publish the CBA rate each day? Before 14:00 CET on 2026-10-21, so the 17:00 CET job sees both fixes.
- [ ] USD/AMD training window: full history, or 2022 to now only?
- [x] Add EUR/AMD as a third pair? Yes, from the CBA's published EUR/AMD rate, not derived.
- [x] Scheduler: GitHub Actions cron (free; four weekday attempts cover CET and CEST).
