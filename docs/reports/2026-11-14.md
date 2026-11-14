# Weekly report, 2026-11-14

Statistical estimate. Not financial advice.

## Statistical models (last 250 trading days)

Backtest run 2026-11-14. Target: the 80% band holds 75-85% of outcomes.

| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |
|---|---|---|---|---|---|---|
| EUR/AMD | 1D | random_walk | 81.2% | 49.6% | 96.0% | lightgbm (1.082, 1.00) |
| EUR/AMD | 1W | random_walk | 82.0% | 47.6% | 97.6% | forward (1.027, 0.95) |
| EUR/AMD | 1M | random_walk | 76.0% | 49.2% | 95.6% | lightgbm (1.046, 0.71) |
| USD/AMD | 1D | random_walk | 79.2% | 50.8% | 94.0% | lightgbm (1.028, 0.74) |
| USD/AMD | 1W | random_walk | 78.4% | 42.0% | 96.8% | forward (1.245, 1.00) |
| USD/AMD | 1M | random_walk | 76.0% | 33.6% | 90.4% | lightgbm (0.851, 0.12) |
| RUB/AMD | 1D | random_walk | 78.8% | 51.2% | 96.8% | lightgbm (1.005, 0.57) |
| RUB/AMD | 1W | random_walk | 73.6% | 38.0% | 96.4% | lightgbm (0.971, 0.31) |
| RUB/AMD | 1M | random_walk | 70.4% | 43.2% | 88.4% | forward (1.028, 0.68) |
| GBP/AMD | 1D | random_walk | 81.2% | 55.2% | 94.8% | lightgbm (1.083, 1.00) |
| GBP/AMD | 1W | random_walk | 84.0% | 50.4% | 97.2% | forward (1.006, 0.73) |
| GBP/AMD | 1M | random_walk | 83.6% | 58.0% | 94.4% | lightgbm (0.898, 0.14) |
| EUR/USD | 1D | random_walk | 78.4% | 48.0% | 94.0% | lightgbm (1.008, 0.78) |
| EUR/USD | 1W | random_walk | 78.4% | 43.6% | 94.4% | forward (1.003, 0.69) |
| EUR/USD | 1M | random_walk | 75.2% | 43.6% | 95.6% | lightgbm (0.991, 0.44) |
| GBP/USD | 1D | random_walk | 81.2% | 50.4% | 94.4% | lightgbm (1.029, 1.00) |
| GBP/USD | 1W | random_walk | 83.2% | 52.0% | 96.8% | forward (1.000, 0.59) |
| GBP/USD | 1M | random_walk | 85.6% | 55.2% | 99.2% | forward (1.001, 0.65) |
| RUB/USD | 1D | random_walk | 80.0% | 50.0% | 96.4% | lightgbm (1.028, 0.84) |
| RUB/USD | 1W | random_walk | 73.2% | 36.8% | 96.8% | lightgbm (0.954, 0.20) |
| RUB/USD | 1M | random_walk | 66.8% | 42.0% | 96.8% | forward (1.040, 0.71) |

## AI view (live track record)

Scored only on forecasts made before the outcome was known. It decides the verdict only after 250 scored forecasts that meet the promotion rule.

| Pair | Horizon | Latest call | Chance better if wait | Confidence | Scored | Hit rate | Brier | MAE ratio | Promoted |
|---|---|---|---|---|---|---|---|---|---|
| EUR/AMD | 1D | Sell now (2026-11-13) | 45% | low | 6 of 250 | 83.3% | 0.217 | 0.896 | no |
| EUR/AMD | 1W | Sell now (2026-11-13) | 41% | medium | 2 of 250 | 100.0% | 0.168 | 0.659 | no |
| EUR/AMD | 1M | Sell now (2026-11-13) | 38% | medium | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1D | Leaning sell now (2026-11-13) | 48% | low | 6 of 250 | 40.0% | 0.240 | 1.097 | no |
| USD/AMD | 1W | Sell now (2026-11-13) | 44% | medium | 2 of 250 | 100.0% | 0.168 | 0.698 | no |
| USD/AMD | 1M | Sell now (2026-11-13) | 40% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/AMD | 1D | Leaning sell now (2026-11-13) | 47% | low | 6 of 250 | 66.7% | 0.235 | 0.960 | no |
| RUB/AMD | 1W | Sell now (2026-11-13) | 45% | low | 2 of 250 | 100.0% | 0.203 | 0.491 | no |
| RUB/AMD | 1M | Sell now (2026-11-13) | 42% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/AMD | 1D | Leaning sell now (2026-11-13) | 46% | low | 6 of 250 | 100.0% | 0.221 | 0.828 | no |
| GBP/AMD | 1W | Sell now (2026-11-13) | 42% | medium | 2 of 250 | 50.0% | 0.254 | 0.952 | no |
| GBP/AMD | 1M | Sell now (2026-11-13) | 38% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/USD | 1D | Leaning sell now (2026-11-13) | 46% | medium | 6 of 250 | 66.7% | 0.230 | 0.911 | no |
| EUR/USD | 1W | Sell now (2026-11-13) | 43% | medium | 2 of 250 | 100.0% | 0.185 | 0.598 | no |
| EUR/USD | 1M | Sell now (2026-11-13) | 40% | high | 0 of 250 | n/a | n/a | n/a | no |
| GBP/USD | 1D | Leaning sell now (2026-11-13) | 47% | low | 6 of 250 | 83.3% | 0.229 | 0.867 | no |
| GBP/USD | 1W | Sell now (2026-11-13) | 43% | medium | 2 of 250 | 50.0% | 0.255 | 1.045 | no |
| GBP/USD | 1M | Sell now (2026-11-13) | 41% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/USD | 1D | Leaning sell now (2026-11-13) | 47% | low | 6 of 250 | 66.7% | 0.238 | 0.963 | no |
| RUB/USD | 1W | Sell now (2026-11-13) | 45% | low | 2 of 250 | 0.0% | 0.308 | 1.791 | no |
| RUB/USD | 1M | Sell now (2026-11-13) | 42% | medium | 0 of 250 | n/a | n/a | n/a | no |

Model and prompt: gemini-3.8-flash@ai-p5.

## Pipeline health

| Job | Last success (UTC) | Latest status |
|---|---|---|
| frankfurter_ecb | 2026-11-13 22:10 | success |
| frankfurter_cba | 2026-11-13 22:10 | success |
| fred | 2026-11-13 22:11 | success |
| ecb_data_portal | 2026-11-13 22:11 | success |
| boe_cbr_rates | 2026-11-13 22:11 | success |
| cba_rates | 2026-11-14 03:04 | success |
| fed_rss | 2026-11-14 10:13 | success |
| ecb_rss | 2026-11-14 10:13 | success |
| cba_news | 2026-11-14 03:05 | success |
| atlanta_fed | 2026-11-14 03:04 | success |
| forecast | 2026-11-14 12:01 | success |
| backtest | 2026-11-14 12:00 | success |
| score_statements | 2026-11-14 10:13 | success |
| ai_view | 2026-11-13 22:12 | success |
| ai_analysis | 2026-11-14 12:03 | success |
