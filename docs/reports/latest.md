# Weekly report, 2026-10-21

Statistical estimate. Not financial advice.

## Statistical models (last 250 trading days)

Backtest run 2026-10-21. Target: the 80% band holds 75-85% of outcomes.

| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |
|---|---|---|---|---|---|---|
| EUR/USD | 1D | random_walk | 79.6% | 49.2% | 94.8% | lightgbm (1.015, 0.89) |
| EUR/USD | 1W | random_walk | 78.8% | 43.6% | 94.4% | forward (1.001, 0.57) |
| EUR/USD | 1M | random_walk | 77.2% | 44.8% | 95.6% | forward (1.011, 0.66) |
| USD/AMD | 1D | random_walk | 79.6% | 52.4% | 94.0% | lightgbm (1.015, 0.64) |
| USD/AMD | 1W | random_walk | 79.6% | 44.0% | 96.8% | forward (1.256, 1.00) |
| USD/AMD | 1M | random_walk | 78.4% | 40.0% | 90.4% | lightgbm (0.975, 0.43) |
| EUR/AMD | 1D | random_walk | 82.4% | 51.6% | 96.4% | lightgbm (1.079, 1.00) |
| EUR/AMD | 1W | random_walk | 82.4% | 48.4% | 97.6% | forward (1.024, 0.93) |
| EUR/AMD | 1M | random_walk | 78.4% | 50.8% | 95.6% | lightgbm (1.047, 0.72) |

## AI view (live track record)

Scored only on forecasts made before the outcome was known. It decides the verdict only after 250 scored forecasts that meet the promotion rule.

| Pair | Horizon | Latest call | Chance better if wait | Confidence | Scored | Hit rate | Brier | MAE ratio | Promoted |
|---|---|---|---|---|---|---|---|---|---|
| EUR/USD | 1D | Leaning sell now (2026-10-21) | 47% | low | 0 of 250 | n/a | n/a | n/a | no |
| EUR/USD | 1W | Sell now (2026-10-21) | 43% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/USD | 1M | Sell now (2026-10-21) | 40% | high | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1D | Leaning sell now (2026-10-21) | 47% | low | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1W | Sell now (2026-10-21) | 44% | medium | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1M | Sell now (2026-10-21) | 39% | high | 0 of 250 | n/a | n/a | n/a | no |
| EUR/AMD | 1D | Leaning wait (2026-10-21) | 52% | low | 0 of 250 | n/a | n/a | n/a | no |
| EUR/AMD | 1W | Sell now (2026-10-21) | 45% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/AMD | 1M | Sell now (2026-10-21) | 40% | high | 0 of 250 | n/a | n/a | n/a | no |

Model and prompt: gemini-3.8-flash@ai-p4.

## Pipeline health

| Job | Last success (UTC) | Latest status |
|---|---|---|
| frankfurter_ecb | 2026-10-21 20:07 | success |
| frankfurter_cba | 2026-10-21 20:07 | success |
| fred | 2026-10-21 14:27 | failed |
| ecb_data_portal | 2026-10-21 20:07 | success |
| cba_rates | 2026-10-21 13:13 | success |
| fed_rss | 2026-10-21 20:50 | success |
| ecb_rss | 2026-10-21 20:50 | success |
| cba_news | 2026-10-21 13:14 | success |
| atlanta_fed | 2026-10-21 13:13 | success |
| forecast | 2026-10-21 20:52 | success |
| backtest | 2026-10-21 20:51 | success |
| score_statements | 2026-10-21 20:50 | success |
| ai_view | 2026-10-21 19:58 | failed |
| ai_analysis | 2026-10-21 20:52 | success |
