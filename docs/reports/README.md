# Weekly reports

The weekly workflow (`.github/workflows/weekly.yml`) runs the walk-forward backtest every
Saturday, then writes `<date>.md` and `latest.md` here with `fxf report`:

- served models and band coverage over the last 250 trading days;
- the AI view's latest calls and live track record;
- pipeline health per source and job.

Committing the report is also repository activity, which stops GitHub from disabling the
scheduled workflows. GitHub does that after 60 days without activity in a public repository.
