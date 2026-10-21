"""Minimal streaming .xlsx reader (openpyxl is not installed): zipfile + lxml iterparse.

Returns cell values as strings (shared and inline strings resolved), with empty cells as
None and columns placed by their cell reference, so gaps keep their position.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator

from lxml import etree

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class XlsxError(ValueError):
    pass


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return -1
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = etree.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(si.itertext()) for si in root.iter(f"{_NS}si")]


def sheet_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        wb = etree.fromstring(z.read("xl/workbook.xml"))
        return [s.get("name") or "" for s in wb.iter(f"{_NS}sheet")]


def iter_rows(data: bytes, sheet: str) -> Iterator[list[str | None]]:
    """Rows of the named sheet. Raises XlsxError if the file or sheet is not readable."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("not an xlsx file") from exc
    with z:
        wb = etree.fromstring(z.read("xl/workbook.xml"))
        rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") or "" for r in rels}
        path = None
        for s in wb.iter(f"{_NS}sheet"):
            if s.get("name") == sheet:
                target = targets.get(s.get(f"{_REL_NS}id"), "")
                path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        if path is None or path not in z.namelist():
            raise XlsxError(f"sheet {sheet!r} not found")
        strings = _shared_strings(z)
        with z.open(path) as fh:
            for _, row in etree.iterparse(fh, tag=f"{_NS}row"):
                values: list[str | None] = []
                for c in row.iter(f"{_NS}c"):
                    idx = _col_index(c.get("r") or "")
                    if idx < 0:
                        idx = len(values)
                    while len(values) < idx:
                        values.append(None)
                    t = c.get("t")
                    v = c.find(f"{_NS}v")
                    if t == "inlineStr":
                        is_ = c.find(f"{_NS}is")
                        values.append("".join(is_.itertext()) if is_ is not None else None)
                    elif v is None or v.text is None:
                        values.append(None)
                    elif t == "s":
                        values.append(strings[int(v.text)])
                    else:
                        values.append(v.text)
                row.clear()
                yield values
