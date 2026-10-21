"""Contract: Atlanta Fed Market Probability Tracker workbook and NY Fed SOFR API."""

import datetime as dt
import io
import json
import zipfile

import httpx
import pytest
import respx

from fxf.events import atlanta
from fxf.http import SchemaError


def test_tracker_workbook_fixture_parses(fixtures_dir):
    df = atlanta.parse_mpt((fixtures_dir / "atlanta_fed/mpt_histdata_trimmed.xlsx").read_bytes())
    assert set(df.columns) == {"date", "ref_start", "mid", "mean"}
    first = df[df["date"] == dt.date(2024, 9, 17)].sort_values("ref_start").iloc[0]
    assert first["ref_start"] == dt.date(2024, 12, 18)
    assert first["mid"] == 5.375 and first["mean"] == pytest.approx(4.0345)


def _workbook(header: list[str]) -> bytes:
    sheet = "".join(
        f'<c r="{c}1" t="inlineStr"><is><t>{h}</t></is></c>'
        for c, h in zip("ABCDE", header, strict=False)
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="DATA" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">{sheet}</row></sheetData></worksheet>',
        )
    return buf.getvalue()


@pytest.mark.parametrize(
    "data",
    [
        b"<html>Page not found</html>",
        _workbook(["date", "window", "range", "stat", "value"]),
        _workbook(["date", "reference_start", "target_range", "field", "value"]),
    ],
)
def test_tracker_unknown_shape_raises(data):
    with pytest.raises(SchemaError):
        atlanta.parse_mpt(data)


@respx.mock
def test_sofr_api_contract(fixtures_dir):
    respx.get(url__startswith=atlanta.SOFR_URL).mock(
        return_value=httpx.Response(
            200, json=json.loads((fixtures_dir / "atlanta_fed/sofr.json").read_text())
        )
    )
    s = atlanta.fetch_sofr(dt.date(2026, 9, 1), dt.date(2026, 10, 21))
    assert s.index.is_monotonic_increasing and s.iloc[-1] == 3.88
    with pytest.raises(SchemaError):
        atlanta.parse_sofr({"refRates": []})
    with pytest.raises(SchemaError):
        atlanta.parse_sofr({"rates": [{"date": "2026-10-20", "rate": 3.88}]})
