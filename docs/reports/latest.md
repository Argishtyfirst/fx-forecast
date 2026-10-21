# Weekly report, 2026-10-21

Statistical estimate. Not financial advice.

## Statistical models (last 250 trading days)

Backtest run 2026-10-21. Target: the 80% band holds 75-85% of outcomes.

| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |
|---|---|---|---|---|---|---|
| EUR/USD | 1D | random_walk | 80.0% | 49.2% | 95.2% | lightgbm (1.015, 0.89) |
| EUR/USD | 1W | random_walk | 78.4% | 44.8% | 94.8% | forward (1.001, 0.57) |
| EUR/USD | 1M | random_walk | 77.6% | 45.2% | 95.6% | forward (1.011, 0.66) |
| USD/AMD | 1D | random_walk | 79.6% | 52.4% | 93.6% | lightgbm (1.006, 0.56) |
| USD/AMD | 1W | random_walk | 79.2% | 43.2% | 97.2% | forward (1.256, 1.00) |
| USD/AMD | 1M | random_walk | 77.6% | 40.0% | 90.4% | lightgbm (0.974, 0.42) |
| EUR/AMD | 1D | random_walk | 83.2% | 52.8% | 96.0% | lightgbm (1.051, 1.00) |
| EUR/AMD | 1W | random_walk | 84.4% | 52.8% | 98.4% | forward (1.020, 0.92) |
| EUR/AMD | 1M | random_walk | 81.2% | 56.4% | 96.0% | lightgbm (0.982, 0.43) |

## AI view (live track record)

The AI view has not run yet (it needs GEMINI_API_KEY).

## Pipeline health

| Job | Last success (UTC) | Latest status |
|---|---|---|
| frankfurter_ecb | 2026-10-21 14:26 | success |
| frankfurter_cba | 2026-10-21 14:26 | success |
| fred | 2026-10-21 14:27 | success |
| ecb_data_portal | 2026-10-21 14:27 | success |
| cba_rates | 2026-10-21 13:13 | success |
| fed_rss | 2026-10-21 14:27 | success |
| ecb_rss | 2026-10-21 14:27 | success |
| cba_news | 2026-10-21 13:14 | success |
| atlanta_fed | 2026-10-21 13:13 | success |
| forecast | 2026-10-21 16:32 | success |
| backtest | 2026-10-21 16:32 | success |
| score_statements | 2026-10-21 14:27 | success |
| ai_view | 2026-10-21 14:28 | success |
