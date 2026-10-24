# Weekly report, 2026-10-24

Statistical estimate. Not financial advice.

## Statistical models (last 250 trading days)

Backtest run 2026-10-24. Target: the 80% band holds 75-85% of outcomes.

| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |
|---|---|---|---|---|---|---|
| EUR/AMD | 1D | random_walk | 82.4% | 51.6% | 96.4% | lightgbm (1.074, 1.00) |
| EUR/AMD | 1W | random_walk | 82.4% | 48.0% | 97.6% | forward (1.024, 0.93) |
| EUR/AMD | 1M | random_walk | 77.6% | 50.8% | 95.6% | lightgbm (1.041, 0.70) |
| USD/AMD | 1D | random_walk | 80.0% | 52.4% | 94.0% | lightgbm (1.013, 0.62) |
| USD/AMD | 1W | random_walk | 79.6% | 44.0% | 96.8% | forward (1.258, 1.00) |
| USD/AMD | 1M | random_walk | 78.0% | 39.2% | 90.4% | lightgbm (0.963, 0.39) |
| RUB/AMD | 1D | random_walk | 79.6% | 50.0% | 96.8% | lightgbm (1.014, 0.71) |
| RUB/AMD | 1W | random_walk | 74.0% | 40.0% | 96.8% | lightgbm (0.990, 0.44) |
| RUB/AMD | 1M | random_walk | 70.4% | 46.4% | 88.4% | forward (1.028, 0.68) |
| GBP/AMD | 1D | random_walk | 82.4% | 56.4% | 95.2% | lightgbm (1.085, 1.00) |
| GBP/AMD | 1W | random_walk | 84.8% | 50.0% | 96.8% | forward (1.008, 0.78) |
| GBP/AMD | 1M | random_walk | 81.6% | 56.0% | 94.4% | lightgbm (0.945, 0.26) |
| EUR/USD | 1D | random_walk | 80.0% | 49.2% | 94.8% | lightgbm (1.015, 0.89) |
| EUR/USD | 1W | random_walk | 78.8% | 43.2% | 94.4% | forward (1.001, 0.60) |
| EUR/USD | 1M | random_walk | 76.8% | 44.4% | 95.6% | forward (1.011, 0.66) |
| GBP/USD | 1D | random_walk | 82.0% | 51.6% | 94.0% | lightgbm (1.025, 0.99) |
| GBP/USD | 1W | random_walk | 83.6% | 52.4% | 97.6% | forward (1.000, 0.71) |
| GBP/USD | 1M | random_walk | 84.4% | 53.2% | 99.2% | forward (1.002, 0.77) |
| RUB/USD | 1D | random_walk | 80.4% | 46.4% | 95.6% | lightgbm (1.007, 0.64) |
| RUB/USD | 1W | random_walk | 71.2% | 35.6% | 92.4% | forward (1.018, 0.84) |
| RUB/USD | 1M | random_walk | 64.0% | 39.2% | 90.4% | forward (1.040, 0.70) |

## AI view (live track record)

Scored only on forecasts made before the outcome was known. It decides the verdict only after 250 scored forecasts that meet the promotion rule.

| Pair | Horizon | Latest call | Chance better if wait | Confidence | Scored | Hit rate | Brier | MAE ratio | Promoted |
|---|---|---|---|---|---|---|---|---|---|
| EUR/AMD | 1D | Sell now (2026-10-23) | 44% | low | 1 of 250 | 100.0% | 0.212 | 0.820 | no |
| EUR/AMD | 1W | Sell now (2026-10-23) | 40% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/AMD | 1M | Sell now (2026-10-23) | 38% | medium | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1D | Sell now (2026-10-23) | 44% | low | 1 of 250 | 100.0% | 0.185 | 0.620 | no |
| USD/AMD | 1W | Sell now (2026-10-23) | 42% | medium | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1M | Sell now (2026-10-23) | 39% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/AMD | 1D | Leaning wait (2026-10-23) | 53% | low | 1 of 250 | 100.0% | 0.212 | 0.798 | no |
| RUB/AMD | 1W | Leaning sell now (2026-10-23) | 46% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/AMD | 1M | Sell now (2026-10-23) | 43% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/AMD | 1D | Leaning sell now (2026-10-23) | 48% | low | 1 of 250 | 100.0% | 0.230 | 0.597 | no |
| GBP/AMD | 1W | Sell now (2026-10-23) | 44% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/AMD | 1M | Sell now (2026-10-23) | 40% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/USD | 1D | Leaning sell now (2026-10-23) | 47% | low | 1 of 250 | 100.0% | 0.221 | 0.533 | no |
| EUR/USD | 1W | Sell now (2026-10-23) | 43% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/USD | 1M | Sell now (2026-10-23) | 41% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/USD | 1D | Leaning sell now (2026-10-23) | 48% | low | 1 of 250 | 100.0% | 0.221 | 0.164 | no |
| GBP/USD | 1W | Sell now (2026-10-23) | 43% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/USD | 1M | Sell now (2026-10-23) | 44% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/USD | 1D | Leaning wait (2026-10-23) | 52% | low | 1 of 250 | 100.0% | 0.212 | 0.774 | no |
| RUB/USD | 1W | Sell now (2026-10-23) | 43% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/USD | 1M | Sell now (2026-10-23) | 44% | medium | 0 of 250 | n/a | n/a | n/a | no |

Model and prompt: gemini-3.8-flash@ai-p5.

## Pipeline health

| Job | Last success (UTC) | Latest status |
|---|---|---|
| frankfurter_ecb | 2026-10-23 20:04 | success |
| frankfurter_cba | 2026-10-23 20:05 | success |
| fred | 2026-10-23 20:05 | success |
| ecb_data_portal | 2026-10-23 20:05 | success |
| boe_cbr_rates | 2026-10-23 20:05 | success |
| cba_rates | 2026-10-24 01:32 | success |
| fed_rss | 2026-10-24 07:11 | success |
| ecb_rss | 2026-10-24 07:11 | success |
| cba_news | 2026-10-24 01:32 | success |
| atlanta_fed | 2026-10-24 01:32 | success |
| forecast | 2026-10-24 09:22 | success |
| backtest | 2026-10-24 09:21 | success |
| score_statements | 2026-10-24 07:11 | success |
| ai_view | 2026-10-23 19:23 | failed |
| ai_analysis | 2026-10-21 20:52 | failed |
