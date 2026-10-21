"""Backtest regression (spec: Test plan): metrics on the frozen real-data set stay within a set
tolerance of the golden file after each change.

    FXF_REGEN_GOLDEN=1 uv run pytest tests/regression    # rewrite tests/golden/backtest_frozen.json

Regenerate only for an intended model change, and bump params.MODEL_VERSIONS with it.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from fxf.backtest.runner import backtest
from fxf.constants import CENTER_CANDIDATES, HORIZONS, PAIRS, WINDOW_FULL, WINDOW_RECENT
from tests.regression.datasets import FROZEN_DIR, load_frozen

pytestmark = pytest.mark.db

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "backtest_frozen.json"
RUN_DATE = dt.date(2024, 12, 31)
START = dt.date(2021, 1, 1)
# Coverages and hit rates move in steps of 1/n; allow a couple of observations to flip on
# another platform (optimiser or LightGBM float differences). Continuous metrics: relative.
ABS_TOL = {"cov50": 0.012, "cov80": 0.012, "cov95": 0.012, "hit_rate": 0.012, "dm_pvalue": 0.02}
# GARCH fits converge to slightly different optima on different CPUs and BLAS builds
# (macOS arm64 vs the Linux CI runner differ by ~0.6% on USDAMD's flat managed float), so
# the relative tolerance allows 2%; real model changes move these metrics by far more.
REL_TOL = 2e-2
EXACT = ("n_obs", "start_date", "end_date")
METRICS = (
    "mae",
    "mae_ratio_rw",
    "hit_rate",
    "cov50",
    "cov80",
    "cov95",
    "pinball",
    "pinball_ref",
    "dm_pvalue",
)


def _key(r: dict) -> str:
    return f"{r['pair']}|{r['horizon_days']}|{r['model']}|{r['window']}"


def _serialise(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:
        out[_key(r)] = {
            **{k: (r[k].isoformat() if isinstance(r[k], dt.date) else r[k]) for k in EXACT},
            **{k: r[k] for k in METRICS},
        }
    return dict(sorted(out.items()))


def test_backtest_metrics_match_golden_on_frozen_dataset(session: Session):
    assert (FROZEN_DIR / "rates.csv").exists(), "run scripts/make_frozen_dataset.py"
    load_frozen(session)
    t0 = time.monotonic()
    res = backtest(session, RUN_DATE, start=START)
    session.commit()
    elapsed = time.monotonic() - t0
    got = _serialise(res.rows)
    expected_keys = {
        f"{p}|{h}|{m}|{w}"
        for p in PAIRS
        for h in HORIZONS
        for m in CENTER_CANDIDATES[h]
        for w in (WINDOW_RECENT, WINDOW_FULL)
        if not (PAIRS[p].quote == "AMD" and m == "forward")  # no CBA rate in the frozen set
    }
    assert set(got) == expected_keys
    assert elapsed < 60, f"backtest took {elapsed:.1f}s"

    if os.environ.get("FXF_REGEN_GOLDEN") == "1" or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(
                {"run_date": RUN_DATE.isoformat(), "start": START.isoformat(), "metrics": got},
                indent=1,
            )
            + "\n"
        )
        if os.environ.get("FXF_REGEN_GOLDEN") != "1":
            pytest.fail("golden file was missing and has been written; rerun the test")
        return

    golden = json.loads(GOLDEN.read_text())["metrics"]
    assert set(golden) == set(got)
    problems = []
    for key, exp in golden.items():
        cur = got[key]
        for k in EXACT:
            if cur[k] != exp[k]:
                problems.append(f"{key} {k}: {cur[k]} != {exp[k]}")
        for k in METRICS:
            a, b = cur[k], exp[k]
            if a is None or b is None:
                if a != b:
                    problems.append(f"{key} {k}: {a} != {b}")
                continue
            tol = ABS_TOL.get(k)
            ok = (
                abs(a - b) <= tol
                if tol is not None
                else math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-12)
            )
            if not ok:
                problems.append(f"{key} {k}: {a:.6g} != golden {b:.6g}")
    assert not problems, "\n".join(problems)
