"""Minimal PDF reading for the CBA documents (no PDF library is installed).

Supports what the CBA's Word-generated PDFs use: FlateDecode content streams, literal and
hex strings, simple (WinAnsi) fonts, Type0 fonts with a ToUnicode CMap, object streams.

- `text_lines(data)` returns the page text as lines, ordered top to bottom.
- `image_cells(data)` returns the image XObjects drawn inside table cells, with their
  bitmap signature. The CBA meeting calendar PDF draws its dates as images of rendered
  text, so `fxf.events.cba` decodes them through a table of known glyph signatures.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from collections import defaultdict
from dataclasses import dataclass

_OBJ = re.compile(rb"(\d+)\s+0\s+obj\b")
_STREAM = re.compile(rb"stream\r?\n")


@dataclass(frozen=True)
class PdfObject:
    num: int
    head: bytes  # the object's dictionary/text before any stream
    stream: bytes | None  # raw (still encoded) stream bytes


@dataclass(frozen=True)
class ImageUse:
    page: int
    cell_x: float  # clip rectangle origin of the enclosing table cell
    cell_y: float
    x: float  # where the image is drawn
    y: float
    width: float  # drawn width (user space)
    name: str  # XObject resource name, e.g. "Image21"
    signature: str  # sha1 of the decoded bitmap (or its soft mask)


def inflate(raw: bytes) -> bytes | None:
    try:
        return zlib.decompressobj().decompress(raw)
    except zlib.error:
        return None


def objects(data: bytes) -> dict[int, PdfObject]:
    out: dict[int, PdfObject] = {}
    starts = [(m.start(), int(m.group(1)), m.end()) for m in _OBJ.finditer(data)]
    for i, (_, num, body_start) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(data)
        chunk = data[body_start:end]
        sm = _STREAM.search(chunk)
        endobj = chunk.find(b"endobj")
        if sm and (endobj < 0 or sm.start() < endobj):
            head = chunk[: sm.start()]
            length = re.search(rb"/Length\s+(\d+)(?!\s+0\s+R)", head)
            s0 = sm.end()
            if length:
                stream = chunk[s0 : s0 + int(length.group(1))]
            else:
                stream = chunk[s0 : chunk.find(b"endstream", s0)]
            out[num] = PdfObject(num, head, stream)
        else:
            out[num] = PdfObject(num, chunk[: endobj if endobj >= 0 else len(chunk)], None)
    # Objects packed in object streams (PDF 1.5).
    for obj in list(out.values()):
        if obj.stream is None or b"/ObjStm" not in obj.head:
            continue
        dec = inflate(obj.stream)
        first = re.search(rb"/First\s+(\d+)", obj.head)
        if dec is None or not first:
            continue
        f = int(first.group(1))
        nums = [int(x) for x in dec[:f].split()]
        pairs = list(zip(nums[0::2], nums[1::2], strict=False))
        for j, (onum, off) in enumerate(pairs):
            stop = pairs[j + 1][1] if j + 1 < len(pairs) else len(dec) - f
            out.setdefault(onum, PdfObject(onum, dec[f + off : f + stop], None))
    return out


def _ref(head: bytes, key: bytes) -> int | None:
    m = re.search(rb"/" + key + rb"\s+(\d+)\s+0\s+R", head)
    return int(m.group(1)) if m else None


def _parse_cmap(text: bytes) -> dict[int, str]:
    cmap: dict[int, str] = {}

    def u(hexstr: bytes) -> str:
        raw = bytes.fromhex(hexstr.decode())
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            cmap[int(src, 16)] = u(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, rest in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block
        ):
            a, b = int(lo, 16), int(hi, 16)
            if rest.startswith(b"["):
                for k, dst in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", rest)):
                    cmap[a + k] = u(dst)
            else:
                base = u(rest[1:-1])
                if base:
                    for k in range(b - a + 1):
                        cmap[a + k] = base[:-1] + chr(ord(base[-1]) + k)
    return cmap


def _fonts(objs: dict[int, PdfObject]) -> dict[str, dict[int, str] | None]:
    """Font resource name -> ToUnicode map (None for simple 1-byte fonts)."""
    fonts: dict[str, dict[int, str] | None] = {}
    for obj in objs.values():
        for m in re.finditer(rb"/Font\s*(<<.*?>>|\d+\s+0\s+R)", obj.head, re.S):
            body = m.group(1)
            if body.endswith(b"R"):
                target = objs.get(int(body.split()[0]))
                body = target.head if target else b""
            for name, num in re.findall(rb"/([A-Za-z0-9_+.\-]+)\s+(\d+)\s+0\s+R", body):
                font = objs.get(int(num))
                if font is None:
                    continue
                cmap = None
                tu = _ref(font.head, b"ToUnicode")
                if tu is not None and tu in objs and objs[tu].stream is not None:
                    dec = inflate(objs[tu].stream or b"")
                    if dec:
                        cmap = _parse_cmap(dec)
                fonts[name.decode()] = cmap if b"/Type0" in font.head else None
    return fonts


_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _unescape(lit: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(lit):
        c = lit[i : i + 1]
        if c == b"\\" and i + 1 < len(lit):
            n = lit[i + 1 : i + 2]
            if n in _ESC:
                out += _ESC[n]
                i += 2
            elif n.isdigit():
                m = re.match(rb"[0-7]{1,3}", lit[i + 1 : i + 4])
                assert m
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
            elif n in b"\r\n":
                i += 2
            else:
                out += n
                i += 2
        else:
            out += c
            i += 1
    return bytes(out)


def _decode(raw: bytes, cmap: dict[int, str] | None) -> str:
    if cmap is None:
        return raw.decode("cp1252", errors="replace")
    return "".join(
        cmap.get(int.from_bytes(raw[k : k + 2], "big"), "") for k in range(0, len(raw), 2)
    )


_TOKENS = re.compile(
    rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>]+|-?\d*\.?\d+|[A-Za-z'\"*]+",
    re.S,
)


_OPERATOR = re.compile(rb"[A-Za-z'\"*]+")


def _num(tok: bytes, default: float) -> float:
    try:
        return float(tok)
    except ValueError:
        return default


def _decoded(obj: PdfObject) -> bytes:
    if obj.stream is None:
        return b""
    if b"FlateDecode" in obj.head:
        return inflate(obj.stream) or b""
    return obj.stream


def _page_order(objs: dict[int, PdfObject]) -> list[int]:
    """Page object numbers in document order (root /Pages -> /Kids, depth first)."""
    nodes = {n: o for n, o in objs.items() if re.search(rb"/Type\s*/Pages\b", o.head)}
    roots = [n for n, o in nodes.items() if b"/Parent" not in o.head] or list(nodes)
    order: list[int] = []

    def walk(n: int, depth: int = 0) -> None:
        o = objs.get(n)
        if o is None or depth > 32:
            return
        if re.search(rb"/Type\s*/Page\b", o.head) and not re.search(rb"/Type\s*/Pages\b", o.head):
            order.append(n)
            return
        kids = re.search(rb"/Kids\s*\[([^\]]*)\]", o.head)
        for k in re.findall(rb"(\d+)\s+0\s+R", kids.group(1) if kids else b""):
            walk(int(k), depth + 1)

    for r in roots:
        walk(r)
    return order


def _content_streams(objs: dict[int, PdfObject]) -> list[bytes]:
    """One content buffer per page (a page may use several streams)."""
    pages = []
    for n in _page_order(objs):
        head = objs[n].head
        m = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", head)
        refs = re.findall(rb"(\d+)\s+0\s+R", m.group(1)) if m else []
        pages.append(b"\n".join(_decoded(objs[int(r)]) for r in refs if int(r) in objs))
    if pages:
        return pages
    out = []
    for obj in sorted(objs.values(), key=lambda o: o.num):
        if obj.stream is None or b"/Subtype" in obj.head or b"/ObjStm" in obj.head:
            continue
        dec = _decoded(obj)
        if dec and (b"Tj" in dec or b"TJ" in dec or b" Do" in dec):
            out.append(dec)
    return out


def text_lines(data: bytes) -> list[str]:
    """Text of all content streams, as lines ordered by stream then top-to-bottom, left-to-right."""
    objs = objects(data)
    fonts = _fonts(objs)
    lines: list[str] = []
    for content in _content_streams(objs):
        frags: dict[float, list[tuple[float, str]]] = defaultdict(list)
        cmap: dict[int, str] | None = None
        x = y = 0.0
        stack: list[bytes] = []
        for tok in _TOKENS.findall(content):
            if tok in (b"[", b"]"):
                continue
            if not _OPERATOR.fullmatch(tok):
                stack.append(tok)
                continue
            if tok == b"Tf" and len(stack) >= 2:
                cmap = fonts.get(stack[-2].lstrip(b"/").decode(errors="replace"))
            elif tok == b"Tm" and len(stack) >= 6:
                x, y = _num(stack[-2], x), _num(stack[-1], y)
            elif tok in (b"Td", b"TD") and len(stack) >= 2:
                x, y = x + _num(stack[-2], 0.0), y + _num(stack[-1], 0.0)
            elif tok in (b"Tj", b"'", b'"', b"TJ"):
                text = ""
                for item in stack:
                    if item.startswith(b"("):
                        text += _decode(_unescape(item[1:-1]), cmap)
                    elif item.startswith(b"<"):
                        hexs = re.sub(rb"\s", b"", item[1:-1])
                        if len(hexs) % 2:
                            hexs += b"0"
                        text += _decode(bytes.fromhex(hexs.decode()), cmap)
                    elif tok == b"TJ" and _num(item, 0.0) < -200:
                        text += " "
                if text:
                    frags[round(y)].append((x, text))
                    x += 0.001  # keep later fragments on the same line after earlier ones
            stack = []
        for yy in sorted(frags, reverse=True):
            line = "".join(t for _, t in sorted(frags[yy], key=lambda f: f[0]))
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                lines.append(line)
    return lines


def _bitmap_signature(objs: dict[int, PdfObject], num: int) -> str:
    obj = objs[num]
    smask = _ref(obj.head, b"SMask")
    target = objs.get(smask) if smask is not None else obj
    if target is None or target.stream is None:
        return ""
    raw = inflate(target.stream) or target.stream
    w = re.search(rb"/Width\s+(\d+)", target.head)
    h = re.search(rb"/Height\s+(\d+)", target.head)
    dims = f"{w.group(1).decode() if w else '?'}x{h.group(1).decode() if h else '?'}"
    return hashlib.sha1(dims.encode() + raw).hexdigest()


def image_cells(data: bytes) -> list[ImageUse]:
    """Every image XObject drawn, with the clip rectangle (table cell) it is drawn in."""
    objs = objects(data)
    xobjects: dict[str, int] = {}
    for obj in objs.values():
        for m in re.finditer(rb"/XObject\s*<<(.*?)>>", obj.head, re.S):
            for name, num in re.findall(rb"/([A-Za-z0-9_]+)\s+(\d+)\s+0\s+R", m.group(1)):
                xobjects[name.decode()] = int(num)
    sigs: dict[str, str] = {}
    uses: list[ImageUse] = []
    pat = re.compile(
        rb"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re\s+W\*? n"
        rb"|([-\d.]+) 0 0 ([-\d.]+) ([-\d.]+) ([-\d.]+) cm\s*/([A-Za-z0-9_]+) Do"
    )
    for page, content in enumerate(_content_streams(objs)):
        clip: tuple[float, float] | None = None
        for m in pat.finditer(content):
            if m.group(1) is not None:
                clip = (float(m.group(1)), float(m.group(2)))
                continue
            name = m.group(9).decode()
            if name not in xobjects:
                continue
            if name not in sigs:
                sigs[name] = _bitmap_signature(objs, xobjects[name])
            x, y = float(m.group(7)), float(m.group(8))
            cx, cy = clip if clip else (0.0, y)
            uses.append(ImageUse(page, cx, cy, x, y, float(m.group(5)), name, sigs[name]))
    return uses
