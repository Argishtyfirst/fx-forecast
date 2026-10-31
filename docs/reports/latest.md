# Weekly report, 2026-10-31

Statistical estimate. Not financial advice.

## Statistical models (last 250 trading days)

Backtest run 2026-10-31. Target: the 80% band holds 75-85% of outcomes.

| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |
|---|---|---|---|---|---|---|
| EUR/AMD | 1D | random_walk | 81.6% | 51.2% | 96.4% | lightgbm (1.079, 1.00) |
| EUR/AMD | 1W | random_walk | 82.0% | 46.8% | 97.6% | forward (1.027, 0.95) |
| EUR/AMD | 1M | random_walk | 76.0% | 48.8% | 95.6% | lightgbm (1.033, 0.69) |
| USD/AMD | 1D | random_walk | 79.6% | 52.8% | 94.0% | lightgbm (1.016, 0.65) |
| USD/AMD | 1W | random_walk | 79.2% | 42.8% | 97.2% | forward (1.261, 1.00) |
| USD/AMD | 1M | random_walk | 76.4% | 37.2% | 90.4% | lightgbm (0.929, 0.29) |
| RUB/AMD | 1D | random_walk | 80.0% | 51.6% | 96.8% | lightgbm (1.018, 0.75) |
| RUB/AMD | 1W | random_walk | 73.6% | 40.0% | 96.8% | forward (1.006, 0.67) |
| RUB/AMD | 1M | random_walk | 70.4% | 46.0% | 88.4% | forward (1.027, 0.67) |
| GBP/AMD | 1D | random_walk | 82.4% | 55.2% | 95.2% | lightgbm (1.080, 1.00) |
| GBP/AMD | 1W | random_walk | 84.8% | 50.4% | 96.8% | forward (1.007, 0.77) |
| GBP/AMD | 1M | random_walk | 81.6% | 56.8% | 94.4% | lightgbm (0.927, 0.17) |
| EUR/USD | 1D | random_walk | 80.0% | 49.6% | 94.8% | lightgbm (1.015, 0.89) |
| EUR/USD | 1W | random_walk | 80.0% | 43.2% | 94.4% | forward (1.001, 0.56) |
| EUR/USD | 1M | random_walk | 75.2% | 44.0% | 95.6% | forward (1.010, 0.65) |
| GBP/USD | 1D | random_walk | 82.0% | 52.0% | 94.0% | lightgbm (1.028, 1.00) |
| GBP/USD | 1W | random_walk | 85.2% | 53.6% | 97.6% | forward (1.000, 0.69) |
| GBP/USD | 1M | random_walk | 85.6% | 54.8% | 99.2% | forward (1.001, 0.73) |
| RUB/USD | 1D | random_walk | 80.8% | 48.0% | 95.6% | lightgbm (1.009, 0.67) |
| RUB/USD | 1W | random_walk | 70.4% | 35.6% | 92.4% | forward (1.017, 0.83) |
| RUB/USD | 1M | random_walk | 64.0% | 38.8% | 90.4% | forward (1.039, 0.70) |

## AI view (live track record)

Scored only on forecasts made before the outcome was known. It decides the verdict only after 250 scored forecasts that meet the promotion rule.

| Pair | Horizon | Latest call | Chance better if wait | Confidence | Scored | Hit rate | Brier | MAE ratio | Promoted |
|---|---|---|---|---|---|---|---|---|---|
| EUR/AMD | 1D | Sell now (2026-10-23) | 44% | low | 2 of 250 | 100.0% | 0.203 | 0.715 | no |
| EUR/AMD | 1W | Sell now (2026-10-23) | 40% | medium | 2 of 250 | 100.0% | 0.168 | 0.659 | no |
| EUR/AMD | 1M | Sell now (2026-10-23) | 38% | medium | 0 of 250 | n/a | n/a | n/a | no |
| USD/AMD | 1D | Sell now (2026-10-23) | 44% | low | 2 of 250 | 100.0% | 0.189 | 0.679 | no |
| USD/AMD | 1W | Sell now (2026-10-23) | 42% | medium | 2 of 250 | 100.0% | 0.168 | 0.698 | no |
| USD/AMD | 1M | Sell now (2026-10-23) | 39% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/AMD | 1D | Leaning wait (2026-10-23) | 53% | low | 2 of 250 | 50.0% | 0.246 | 0.969 | no |
| RUB/AMD | 1W | Leaning sell now (2026-10-23) | 46% | medium | 2 of 250 | 100.0% | 0.203 | 0.491 | no |
| RUB/AMD | 1M | Sell now (2026-10-23) | 43% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/AMD | 1D | Leaning sell now (2026-10-23) | 48% | low | 2 of 250 | 100.0% | 0.230 | 0.786 | no |
| GBP/AMD | 1W | Sell now (2026-10-23) | 44% | medium | 2 of 250 | 50.0% | 0.254 | 0.952 | no |
| GBP/AMD | 1M | Sell now (2026-10-23) | 40% | medium | 0 of 250 | n/a | n/a | n/a | no |
| EUR/USD | 1D | Leaning sell now (2026-10-23) | 47% | low | 2 of 250 | 100.0% | 0.221 | 0.411 | no |
| EUR/USD | 1W | Sell now (2026-10-23) | 43% | medium | 2 of 250 | 100.0% | 0.185 | 0.598 | no |
| EUR/USD | 1M | Sell now (2026-10-23) | 41% | medium | 0 of 250 | n/a | n/a | n/a | no |
| GBP/USD | 1D | Leaning sell now (2026-10-23) | 48% | low | 2 of 250 | 100.0% | 0.226 | 0.523 | no |
| GBP/USD | 1W | Sell now (2026-10-23) | 43% | medium | 2 of 250 | 50.0% | 0.255 | 1.045 | no |
| GBP/USD | 1M | Sell now (2026-10-23) | 44% | medium | 0 of 250 | n/a | n/a | n/a | no |
| RUB/USD | 1D | Leaning wait (2026-10-23) | 52% | low | 2 of 250 | 50.0% | 0.241 | 0.896 | no |
| RUB/USD | 1W | Sell now (2026-10-23) | 43% | medium | 2 of 250 | 0.0% | 0.308 | 1.791 | no |
| RUB/USD | 1M | Sell now (2026-10-23) | 44% | medium | 0 of 250 | n/a | n/a | n/a | no |

Model and prompt: gemini-3.8-flash@ai-p5.

## Pipeline health

| Job | Last success (UTC) | Latest status |
|---|---|---|
| frankfurter_ecb | 2026-10-30 21:02 | success |
| frankfurter_cba | 2026-10-30 21:02 | success |
| fred | 2026-10-30 21:02 | success |
| ecb_data_portal | 2026-10-30 21:02 | success |
| boe_cbr_rates | 2026-10-30 21:03 | success |
| cba_rates | 2026-10-31 05:23 | success |
| fed_rss | 2026-10-31 05:23 | success |
| ecb_rss | 2026-10-31 05:23 | success |
| cba_news | 2026-10-31 05:23 | success |
| atlanta_fed | 2026-10-31 05:23 | success |
| forecast | 2026-10-31 10:49 | success |
| backtest | 2026-10-31 10:48 | success |
| score_statements | 2026-10-28 15:55 | failed |
| ai_view | 2026-10-23 19:23 | failed |
| ai_analysis | 2026-10-21 20:52 | failed |
