"""Contract: Federal Reserve sources (RSS, statement page, calendars, fredgraph CSV)."""

import datetime as dt

import httpx
import pytest
import respx

from fxf.constants import SOURCE_FED_RSS
from fxf.events import calendar, fed
from fxf.http import SchemaError

STATEMENT = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"


def test_rss_fixture_parses(fixtures_dir):
    items = fed.parse_rss(SOURCE_FED_RSS, (fixtures_dir / "fed/press_monetary.xml").read_text())
    stmts = [i for i in items if fed.is_fomc_statement(i.title)]
    assert len(stmts) == 1
    assert stmts[0].link == STATEMENT
    assert stmts[0].published_at == dt.datetime(2026, 9, 16, 18, 0, tzinfo=dt.UTC)
    assert fed.item_day(stmts[0]) == dt.date(2026, 9, 16)
    assert not fed.is_fomc_statement(
        "Minutes of the Federal Open Market Committee, September 15-16, 2026"
    )


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>Service unavailable</body></html>",
        '{"items": []}',
        "<rss><channel></channel></rss>",
    ],
)
def test_rss_unknown_shape_raises(body):
    with pytest.raises(SchemaError):
        fed.parse_rss(SOURCE_FED_RSS, body)


@respx.mock
def test_statement_page_parses_text_and_rates(fixtures_dir):
    respx.get(STATEMENT).mock(
        return_value=httpx.Response(
            200, text=(fixtures_dir / "fed/monetary20260916a.htm").read_text()
        )
    )
    st = fed.fetch_statement(STATEMENT)
    assert st.date == dt.date(2026, 9, 16)
    assert st.title == "Federal Reserve issues FOMC statement"
    assert st.text.startswith("The Federal Open Market Committee approved the following statement")
    assert "For media inquiries" not in st.text and "Implementation Note" not in st.text
    from fxf.events.text import parse_fed_target_range

    assert parse_fed_target_range(st.text) == (3.75, 4.0)


def test_statement_unknown_layout_raises():
    with pytest.raises(SchemaError):
        fed.parse_statement(
            "<html><body><div id='main'><p>Moved</p></div></body></html>", STATEMENT
        )


def test_calendar_unknown_layout_raises():
    with pytest.raises(SchemaError):
        calendar.parse_fed_calendar(
            "<html><body><div class='panel'><h4>Meetings</h4></div></body></html>"
        )
    with pytest.raises(SchemaError):
        calendar.parse_fed_historical(
            "<html><body><h5>Totally new heading - 2019</h5></body></html>", 2019
        )


def test_fredgraph_csv_contract():
    s = fed.parse_fredgraph(
        "DFEDTARU", "observation_date,DFEDTARU\n2026-09-16,3.75\n2026-09-17,4.00\n2026-09-18,.\n"
    )
    assert s.tolist() == [3.75, 4.0]
    with pytest.raises(SchemaError):
        fed.parse_fredgraph("DFEDTARU", "<html>error</html>")
