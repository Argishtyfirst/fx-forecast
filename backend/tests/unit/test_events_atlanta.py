"""Atlanta Fed tracker -> expected midpoint after the next FOMC meeting."""

import datetime as dt

import pandas as pd
import pytest

from fxf.events import atlanta


def _windows(
    obs: dt.date, path: dict[dt.date, float], starts: list[dt.date], basis: float
) -> pd.DataFrame:
    """Window means implied by a known step path (percent), as the tracker would report them."""
    rows = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else s + dt.timedelta(days=91)
        days = pd.date_range(s, e - dt.timedelta(days=1))
        levels = []
        for d in days:
            lvl = [v for k, v in sorted(path.items()) if k <= d.date()]
            levels.append(lvl[-1] + basis)
        rows.append(
            {"date": obs, "ref_start": s, "mid": path[min(path)], "mean": sum(levels) / len(levels)}
        )
    return pd.DataFrame(rows)


STARTS = [
    dt.date(2026, 12, 16),
    dt.date(2027, 3, 17),
    dt.date(2027, 6, 16),
    dt.date(2027, 9, 15),
    dt.date(2027, 12, 15),
]
FOMC = [
    dt.date(2026, 10, 28),
    dt.date(2026, 12, 9),
    dt.date(2027, 1, 27),
    dt.date(2027, 3, 17),
    dt.date(2027, 4, 28),
    dt.date(2027, 6, 9),
    dt.date(2027, 7, 28),
    dt.date(2027, 9, 15),
    dt.date(2027, 10, 27),
    dt.date(2027, 12, 8),
]
OBS = dt.date(2026, 10, 19)


def test_flat_market_expects_no_change():
    w = _windows(OBS, {OBS: 3.875}, STARTS, basis=0.0)
    assert atlanta.expected_after_next(w, 3.875, 0.0, OBS, FOMC) == pytest.approx(3.875, abs=0.01)


def test_priced_hike_at_next_meeting_is_recovered_despite_sofr_basis():
    # The next meeting falls inside the first reference window, so its step is identified.
    obs = dt.date(2026, 10, 30)
    starts = [dt.date(2026, 11, 4), dt.date(2027, 2, 3), dt.date(2027, 5, 5), dt.date(2027, 8, 4)]
    fomc = [
        dt.date(2026, 11, 18),
        dt.date(2027, 1, 27),
        dt.date(2027, 3, 17),
        dt.date(2027, 4, 28),
        dt.date(2027, 6, 9),
    ]
    w = _windows(obs, {obs: 3.875, dt.date(2026, 11, 18): 4.125}, starts, basis=-0.05)
    assert atlanta.expected_after_next(w, 3.875, -0.05, obs, fomc) == pytest.approx(4.125, abs=0.02)


def test_two_meetings_before_first_window_share_the_priced_move():
    """Documented limitation: only the combined move of the October and December meetings is
    identified when both fall before the first listed window; the fit splits it."""
    path = {OBS: 3.875, dt.date(2026, 12, 9): 4.125}
    exp = atlanta.expected_after_next(_windows(OBS, path, STARTS, basis=0.0), 3.875, 0.0, OBS, FOMC)
    assert 3.875 < exp < 4.125


def test_expected_series_and_macro_rows_from_fixture(fixtures_dir):
    import json

    mpt = atlanta.parse_mpt((fixtures_dir / "atlanta_fed/mpt_histdata_trimmed.xlsx").read_bytes())
    sofr = atlanta.parse_sofr(json.loads((fixtures_dir / "atlanta_fed/sofr.json").read_text()))
    from fxf.events.calendar import load_seed

    fomc = [m.date for m in load_seed() if m.bank == "FED" and m.scheduled]
    s = atlanta.expected_series(mpt, sofr, fomc)
    assert list(s.index.date) == [
        dt.date(2024, 9, 16),
        dt.date(2024, 9, 17),
        dt.date(2026, 9, 14),
        dt.date(2026, 9, 15),
        dt.date(2026, 10, 19),
    ]
    # Before the 50 bp cut of 2024-09-18 the market priced roughly 35-40 bp.
    assert 4.9 < s[pd.Timestamp("2024-09-17")] < 5.1
    rows = atlanta.macro_rows(s, dt.datetime(2026, 10, 21, tzinfo=dt.UTC))
    assert rows[0]["series_id"] == "ATLFED_EXP_NEXT"
    assert rows[0]["published_at"] == dt.datetime(2024, 9, 17, 13, tzinfo=dt.UTC)
