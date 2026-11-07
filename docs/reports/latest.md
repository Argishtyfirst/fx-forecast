# Weekly report, 2026-11-07

Statistical estimate. Not financial advice.

## Statistical models (last 250 trading days)

Backtest run 2026-11-07. Target: the 80% band holds 75-85% of outcomes.

| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |
|---|---|---|---|---|---|---|
| EUR/AMD | 1D | random_walk | 81.2% | 50.8% | 96.4% | lightgbm (1.081, 1.00) |
| EUR/AMD | 1W | random_walk | 83.2% | 47.6% | 97.6% | forward (1.024, 0.92) |
| EUR/AMD | 1M | random_walk | 76.0% | 50.0% | 95.6% | lightgbm (1.051, 0.77) |
| USD/AMD | 1D | random_walk | 78.8% | 50.4% | 94.0% | lightgbm (1.014, 0.63) |
| USD/AMD | 1W | random_walk | 78.4% | 41.6% | 96.8% | forward (1.254, 1.00) |
| USD/AMD | 1M | random_walk | 76.0% | 35.2% | 90.4% | lightgbm (0.904, 0.22) |
| RUB/AMD | 1D | random_walk | 79.6% | 52.0% | 96.8% | lightgbm (1.012, 0.68) |
| RUB/AMD | 1W | random_walk | 73.6% | 39.2% | 96.8% | lightgbm (0.998, 0.48) |
| RUB/AMD | 1M | random_walk | 70.4% | 44.0% | 88.4% | forward (1.025, 0.66) |
| GBP/AMD | 1D | random_walk | 81.6% | 56.0% | 95.2% | lightgbm (1.080, 1.00) |
| GBP/AMD | 1W | random_walk | 85.6% | 51.6% | 97.2% | forward (1.005, 0.68) |
| GBP/AMD | 1M | random_walk | 83.6% | 57.6% | 94.4% | lightgbm (0.917, 0.14) |
| EUR/USD | 1D | random_walk | 78.4% | 48.4% | 94.4% | lightgbm (1.012, 0.85) |
| EUR/USD | 1W | random_walk | 79.2% | 44.0% | 94.4% | forward (1.002, 0.61) |
| EUR/USD | 1M | random_walk | 75.2% | 44.0% | 95.6% | forward (1.010, 0.64) |
| GBP/USD | 1D | random_walk | 81.2% | 52.0% | 94.0% | lightgbm (1.028, 0.99) |
| GBP/USD | 1W | random_walk | 84.4% | 53.2% | 97.6% | forward (1.000, 0.59) |
| GBP/USD | 1M | random_walk | 85.6% | 54.0% | 99.2% | forward (1.001, 0.68) |
| RUB/USD | 1D | random_walk | 80.0% | 48.0% | 95.6% | lightgbm (1.009, 0.67) |
| RUB/USD | 1W | random_walk | 70.0% | 35.2% | 92.4% | forward (1.017, 0.83) |
| RUB/USD | 1M | random_walk | 64.0% | 37.6% | 90.4% | forward (1.037, 0.69) |

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
| frankfurter_ecb | 2026-11-06 21:45 | success |
| frankfurter_cba | 2026-11-06 21:45 | success |
| fred | 2026-11-06 21:45 | success |
| ecb_data_portal | 2026-11-06 21:45 | success |
| boe_cbr_rates | 2026-11-06 21:45 | success |
| cba_rates | 2026-11-07 02:42 | success |
| fed_rss | 2026-11-07 09:55 | success |
| ecb_rss | 2026-11-07 09:55 | success |
| cba_news | 2026-11-07 02:43 | success |
| atlanta_fed | 2026-11-07 02:43 | success |
| forecast | 2026-11-07 11:35 | success |
| backtest | 2026-11-07 11:34 | success |
| score_statements | 2026-10-28 15:55 | failed |
| ai_view | 2026-10-23 19:23 | failed |
| ai_analysis | 2026-10-21 20:52 | failed |
