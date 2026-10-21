"""Contract: CBA rate export, press releases (new and old site), EMPS PDF, calendar link,
and the ARKA / Interfax fallback feeds."""

import datetime as dt
import json

import httpx
import pytest
import respx

from fxf.events import cba
from fxf.http import SchemaError


def test_rates_export_fixture_parses(fixtures_dir):
    rows = cba.parse_rates_export(json.loads((fixtures_dir / "cba/rates_export.json").read_text()))
    assert rows[0].date == dt.date(2004, 3, 8)
    assert rows[-1].as_dict() == {"refinancing": 6.75, "lombard": 8.25, "deposit": 5.25}
    assert len(rows) > 140


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"a": [], "b": []},
        {
            "value": [{"Indicators": "Refinancing rate (%)", "2026-01-01": 6.5}]
        },  # lombard/deposit rows missing
        {"value": [{"Indicators": "Repo rate (%)", "2026-01-01": 6.5}]},
        {"value": [{"Indicators": "Refinancing rate (%)", "01/02/2026": 6.5}]},
    ],
)
def test_rates_export_unknown_shape_raises(payload):
    with pytest.raises(SchemaError):
        cba.parse_rates_export(payload)


@respx.mock
def test_rates_export_through_http_layer(fixtures_dir):
    respx.get(url__startswith=cba.RATES_URL).mock(
        return_value=httpx.Response(
            200, json=json.loads((fixtures_dir / "cba/rates_export.json").read_text())
        )
    )
    assert cba.fetch_rates_export()[-1].date == dt.date(2026, 9, 15)


def test_press_list_fixture_parses(fixtures_dir):
    items = cba.parse_press_list((fixtures_dir / "cba/press_list.htm").read_text())
    rate = [i for i in items if cba.is_rate_decision(i.title)]
    assert [i.id for i in rate] == [10606, 10429]
    assert rate[0].published_at == dt.datetime(2026, 9, 15, 8, 0, tzinfo=dt.UTC)  # 12:00 Yerevan


def test_press_list_unknown_layout_raises():
    with pytest.raises(SchemaError):
        cba.parse_press_list("<html><body><ul><li>No releases</li></ul></body></html>")


def test_press_release_new_and_2009_wording(fixtures_dir):
    new = cba.parse_press_release(
        (fixtures_dir / "cba/press_10606.htm").read_text(),
        "https://www.cba.am/en/press-releases/10606/",
    )
    assert new.date == dt.date(2026, 9, 15)
    assert cba.decision_from_release(new) == {"refinancing": 6.75, "lombard": 8.25, "deposit": 5.25}
    assert new.pdf_urls == (
        "https://www.cba.am/file_manager/Monetary%20policy%20en/Statement/EMPS_Q3_2026_Eng.pdf",
    )
    old = cba.parse_press_release(
        (fixtures_dir / "cba/press_1466.htm").read_text(),
        "https://www.cba.am/en/press-releases/1466/",
    )
    assert cba.decision_from_release(old) == {"refinancing": 6.75}


def test_press_release_unknown_layout_raises():
    with pytest.raises(SchemaError):
        cba.parse_press_release("<html><body><h1>Moved</h1></body></html>", "u")


def test_old_site_release_and_inline_emps(fixtures_dir):
    url = "https://old.cba.am/EN/News/Pages/news_18032025.aspx"
    rel = cba.parse_old_press((fixtures_dir / "cba/old_news_18032025.htm").read_text(), url)
    assert rel.date == dt.date(2025, 3, 18)
    assert cba.decision_from_release(rel) == {"refinancing": 6.75, "lombard": 8.25, "deposit": 5.25}
    assert "In case of using the Press Release" not in rel.text
    with respx.mock:
        respx.get(cba.old_emps_url(url)).mock(
            return_value=httpx.Response(
                200, text=(fixtures_dir / "cba/old_news_18032025_01.htm").read_text()
            )
        )
        text = cba.statement_text(rel)
    assert text.startswith(
        "The Board of the CBA decided today to keep the Refinancing Rate unchanged at 6.75%."
    )
    assert "B. Summary of Economic Conditions" not in text and "Approved by the Board" not in text
    with pytest.raises(SchemaError):
        cba.parse_old_press("<html></html>", url)


def test_emps_pdf_section_a(fixtures_dir):
    text = cba.emps_text((fixtures_dir / "cba/emps_q3_2026_eng.pdf").read_bytes())
    assert text.startswith(
        "The Board of the CBA decided today to increase the policy rate by 0.25 percentage points to 6.75%."
    )
    assert "Armenia’s country risk premium" in text  # text drawn with a Type0 font (ToUnicode CMap)
    assert "Summary of Economic Conditions" not in text
    assert cba.emps_text(b"%PDF-1.7 not really a pdf") is None


def test_calendar_link_contract(fixtures_dir):
    url = cba.find_calendar_url((fixtures_dir / "cba/decision_making_process.htm").read_text())
    assert url == "https://www.cba.am/file_manager/Interest-rate-calendar-2026-2028-eng.pdf"
    with pytest.raises(SchemaError):
        cba.find_calendar_url("<html><body>No link</body></html>")


def test_fallback_feeds(fixtures_dir):
    arka = cba.parse_news_feed("arka", (fixtures_dir / "arka/rss.xml").read_text())
    hits = [cba.news_decision(i) for i in arka]
    assert hits == [{"refinancing": 6.75, "lombard": 8.25, "deposit": 5.25}, None]
    ifx = cba.parse_news_feed("interfax", (fixtures_dir / "interfax/rss.xml").read_text())
    assert [cba.news_decision(i) for i in ifx] == [None, None, None]
    ifx = cba.parse_news_feed(
        "interfax", (fixtures_dir / "interfax/rss_with_cba_decision.xml").read_text()
    )
    assert cba.news_decision(ifx[0]) == {"refinancing": 6.75}
    with pytest.raises(SchemaError):
        cba.parse_news_feed("arka", "<html><title>Attention Required! | Cloudflare</title></html>")
