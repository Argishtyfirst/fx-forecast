"""Contract: ECB press RSS, decision press release, meeting calendar and FM rate series."""

import datetime as dt

import pytest

from fxf.events import calendar, ecb
from fxf.events.text import parse_ecb_rates
from fxf.http import SchemaError


def test_press_rss_fixture_parses(fixtures_dir):
    items = ecb.parse_feed((fixtures_dir / "ecb_rss/press.xml").read_text())
    assert len(items) == 4 and all(i.link.startswith("https://www.ecb.europa.eu/") for i in items)
    assert not any(ecb.is_decision(i.title) for i in items)
    items = ecb.parse_feed((fixtures_dir / "ecb_rss/press_with_decision.xml").read_text())
    (dec,) = [i for i in items if ecb.is_decision(i.title)]
    assert dec.published_at == dt.datetime(2026, 9, 10, 12, 15, tzinfo=dt.UTC)
    assert ecb.item_day(dec) == dt.date(2026, 9, 10)


def test_press_rss_unknown_shape_raises():
    with pytest.raises(SchemaError):
        ecb.parse_feed("<html><body>Maintenance</body></html>")


def test_decision_page_parses_text_and_three_rates(fixtures_dir):
    st = ecb.parse_decision_page(
        (fixtures_dir / "ecb_decisions/mp260910.htm").read_text(),
        "https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html",
    )
    assert st.date == dt.date(2026, 9, 10)
    assert st.text.startswith(
        "The Governing Council today decided to raise the three key ECB interest rates"
    )
    assert parse_ecb_rates(st.text) == {"deposit": 2.5, "mro": 2.65, "mlf": 2.9}
    old = ecb.parse_decision_page(
        (fixtures_dir / "ecb_decisions/pr161208.htm").read_text(),
        "https://www.ecb.europa.eu/press/pr/date/2016/html/pr161208.en.html",
    )
    assert old.date == dt.date(2016, 12, 8)
    assert parse_ecb_rates(old.text) == {"mro": 0.0, "mlf": 0.25, "deposit": -0.4}


def test_decision_page_unknown_layout_raises():
    with pytest.raises(SchemaError):
        ecb.parse_decision_page("<html><main><div class='title'>Speech</div></main></html>", "u")


def test_schedule_and_listing_unknown_layout_raise():
    with pytest.raises(SchemaError):
        calendar.parse_ecb_schedule("<html><main><p>No list</p></main></html>")
    with pytest.raises(SchemaError):
        calendar.parse_ecb_decisions(
            "<dl><dt isoDate='2026-01-01'></dt><dd><div class='title'><a href='/x'>Speech</a></div></dd></dl>"
        )


def test_fm_series_contract(fixtures_dir):
    s = ecb.parse_fm_csv("DFR", (fixtures_dir / "ecb_decisions/fm_dfr.csv").read_text())
    assert s.index.is_monotonic_increasing and s.iloc[-1] == 2.5
    with pytest.raises(SchemaError):
        ecb.parse_fm_csv("DFR", "<html>ECB Data Portal gives an error</html>")
    with pytest.raises(SchemaError):
        ecb.parse_fm_csv("DFR", "KEY,TIME_PERIOD,OBS_VALUE\n")
