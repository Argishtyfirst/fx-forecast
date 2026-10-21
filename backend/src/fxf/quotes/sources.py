"""Where to convert: retail rates from Armenian banks and money transfer services.

Sources, all public and read without a login (checked 21 Oct 2026):

- rate.am: one page carries the board rates of 17 Armenian banks. The numbers sit in the
  page's Next.js server-component payload, which the header `RSC: 1` returns on its own.
  CLEARING is the non-cash rate (money on an account), CASH the branch rate, CARD a sparse
  card rate. "buy" is what the bank pays you for a euro or dollar.
- Inecobank's own rates feed adds its online (app) rate, which beats its board rate and
  which rate.am does not show.
- Wise: the documented, token-free quote endpoint (POST /v3/quotes, "for illustrative
  purposes") gives the exact AMD a recipient in Armenia gets for an amount. Wise converts at
  the mid-market rate and charges a fee that depends on the amount, so a few amounts are
  quoted and the fee curve is stored.

- Paysend: the public corridor pages (Germany to Armenia for euros, the US to Armenia for
  dollars) embed the calculator state: the standard rate, better rates for larger amounts,
  the fixed fee, and a promo rate for small first transfers (kept in meta, not used). An
  unknown page silently shows another corridor, so the currencies are checked every time.

Revolut publishes no EUR/AMD rate that a script may read (its pages sit behind a bot check,
its quote API is disallowed by robots.txt), so it is listed as unavailable, never scraped.

Every value is checked against the CBA rate: a quote more than MAX_GAP away from it is a
data error (rate.am shows the odd 87.12 for a 401 rate) and is dropped.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import BaseModel

from fxf import http

RATEAM_URL: Final = "https://www.rate.am/en/armenian-dram-exchange-rates/banks"
INECO_URL: Final = "https://www.inecobank.am/api/rates/"
WISE_URL: Final = "https://api.wise.com/v3/quotes"
WISE_AMOUNTS: Final = (250, 1000, 5000)
PAYSEND_PAGES: Final = {
    # currency sent: (public corridor page, the country it is sent from)
    "EUR": ("https://paysend.com/en-de/send-money/from-germany-to-armenia", "a European"),
    "USD": (
        "https://paysend.com/en-us/send-money/from-the-united-states-of-america-to-armenia",
        "a US",
    ),
}
MAX_GAP: Final = 0.05
CURRENCIES: Final = {"EUR": "EURAMD", "USD": "USDAMD"}
RATEAM_CHANNELS: Final = {"CLEARING": "non_cash", "CASH": "cash", "CARD": "card"}


@dataclass
class Quote:
    provider: str
    name: str
    kind: str  # bank | app | transfer
    pair: str
    channel: str  # cash | non_cash | card | online | transfer
    buy: float | None
    source: str
    sell: float | None = None
    fee_fixed: float | None = None
    fee_pct: float | None = None
    quoted_at: dt.datetime | None = None
    url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def plausible(rate: float | None, reference: float | None) -> bool:
    if rate is None:
        return False
    return reference is None or abs(rate / reference - 1) <= MAX_GAP


# --- rate.am ------------------------------------------------------------------------------


def _flight_rows(body: str) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for line in body.split("\n"):
        m = re.match(r"^([0-9a-f]+):(.*)$", line)
        if m and m.group(2)[:1] in "{[":
            try:
                rows[m.group(1)] = json.loads(m.group(2))
            except ValueError:
                continue
    return rows


def _resolve(rows: dict[str, Any], v: Any, depth: int = 0) -> Any:
    """Replace "$<id>" references with the rows they point to (the ids change per response)."""
    if depth > 25:
        return v
    if isinstance(v, str) and v.startswith("$") and v[1:] in rows:
        return _resolve(rows, rows[v[1:]], depth + 1)
    if isinstance(v, dict):
        return {k: _resolve(rows, x, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve(rows, x, depth + 1) for x in v]
    return v


def _find_props(node: Any, depth: int = 0) -> dict[str, Any] | None:
    if depth > 40:
        return None
    if isinstance(node, dict):
        if "organizationRates" in node and "organizations" in node:
            return node
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = _find_props(child, depth + 1)
        if found is not None:
            return found
    return None


def parse_rateam(body: str, reference: dict[str, float]) -> list[Quote]:
    rows = _flight_rows(body)
    props = None
    for row in rows.values():
        props = _find_props(row)
        if props is not None:
            break
    if props is None:
        raise http.SchemaError("rate.am: no organizationRates in the page payload")
    rates = _resolve(rows, props["organizationRates"])
    orgs = _resolve(rows, props["organizations"])
    if not isinstance(rates, dict) or not isinstance(orgs, dict):
        raise http.SchemaError("rate.am: unexpected organizationRates shape")
    out: list[Quote] = []
    for code, entry in rates.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("rates"), dict):
            continue
        org = orgs.get(code) if isinstance(orgs.get(code), dict) else {}
        name = " ".join(str(org.get("name") or code).split())
        # rate.am keys banks by an internal code ("inekobank"); the slug ("inecobank") is the
        # bank's usual name and matches the ids of the bank's own sources.
        provider = str(org.get("slug") or code)
        updated = entry.get("lastUpdated")
        quoted_at = (
            dt.datetime.fromtimestamp(updated / 1000, dt.UTC)
            if isinstance(updated, int | float)
            else None
        )
        for ccy, pair in CURRENCIES.items():
            by_type = entry["rates"].get(ccy)
            if not isinstance(by_type, dict):
                continue
            for raw_channel, channel in RATEAM_CHANNELS.items():
                q = by_type.get(raw_channel)
                if not isinstance(q, dict):
                    continue
                buy, sell = _num(q.get("buy")), _num(q.get("sell"))
                if not plausible(buy, reference.get(pair)):
                    continue
                out.append(
                    Quote(
                        provider=provider,
                        name=name,
                        kind="bank",
                        pair=pair,
                        channel=channel,
                        buy=buy,
                        sell=sell if plausible(sell, reference.get(pair)) else None,
                        quoted_at=quoted_at,
                        source="rate.am",
                        url=org.get("website") or None,
                    )
                )
    if not out:
        raise http.SchemaError("rate.am: no usable bank rates")
    return out


def fetch_rateam(reference: dict[str, float]) -> list[Quote]:
    body = http.fetch_text("rateam", RATEAM_URL, headers={"RSC": "1"}, ext="txt")
    return parse_rateam(body, reference)


# --- Inecobank online rate ----------------------------------------------------------------


class _InecoSide(BaseModel):
    buy: float | None = None
    sell: float | None = None


class _InecoItem(BaseModel):
    code: str
    online: _InecoSide | None = None


class _InecoResponse(BaseModel):
    success: bool
    items: list[_InecoItem]


def fetch_inecobank(reference: dict[str, float]) -> list[Quote]:
    data: _InecoResponse = http.fetch_json(
        "inecobank", INECO_URL, _InecoResponse, headers={"Accept": "application/json"}
    )
    out = []
    for item in data.items:
        pair = CURRENCIES.get(item.code)
        if (
            pair is None
            or item.online is None
            or not plausible(item.online.buy, reference.get(pair))
        ):
            continue
        out.append(
            Quote(
                provider="inecobank",
                name="Inecobank",
                kind="bank",
                pair=pair,
                channel="online",
                buy=item.online.buy,
                sell=item.online.sell,
                source="inecobank",
                url="https://www.inecobank.am/en/Individual/exchange-rates",
                meta={"note": "Rate in InecoOnline and the Inecobank app"},
            )
        )
    return out


# --- Wise ---------------------------------------------------------------------------------


class _WiseFee(BaseModel):
    total: float


class _WiseOption(BaseModel):
    payIn: str
    payOut: str | None = None
    disabled: bool = False
    fee: _WiseFee
    sourceAmount: float | None = None
    targetAmount: float | None = None
    estimatedDelivery: str | None = None


class _WiseQuote(BaseModel):
    rate: float
    paymentOptions: list[_WiseOption]


def fetch_wise(reference: dict[str, float]) -> list[Quote]:
    """Quote a few amounts per currency (a bank transfer in, the cheapest pay-in) and store
    the fee at each amount; fxf.quotes.service interpolates the fee for the user's amount."""
    out: list[Quote] = []
    errors: list[str] = []
    for ccy, pair in CURRENCIES.items():
        points: list[list[float]] = []
        mid = None
        delivery = payout = None
        for amount in WISE_AMOUNTS:
            try:
                q: _WiseQuote = http.post_json(
                    "wise",
                    WISE_URL,
                    {"sourceCurrency": ccy, "targetCurrency": "AMD", "sourceAmount": amount},
                    _WiseQuote,
                    retries=1,
                )
            except http.SourceError as exc:
                errors.append(f"{ccy} {amount}: {exc}")
                continue
            opt = next(
                (o for o in q.paymentOptions if o.payIn == "BANK_TRANSFER" and not o.disabled),
                None,
            )
            if opt is None or not opt.targetAmount:
                continue
            mid = q.rate
            points.append([float(amount), round(opt.fee.total, 2), round(opt.targetAmount, 2)])
            delivery, payout = opt.estimatedDelivery, opt.payOut
        if not points or not plausible(mid, reference.get(pair)):
            continue
        out.append(
            Quote(
                provider="wise",
                name="Wise",
                kind="transfer",
                pair=pair,
                channel="transfer",
                buy=mid,
                source="wise",
                url="https://wise.com/",
                meta={
                    "fee_curve": points,  # [amount, fee in the base currency, AMD received]
                    "payout": payout,
                    "estimated_delivery": delivery,
                    "note": "Bank transfer from a European account to an Armenian bank account"
                    + (" by SWIFT" if payout == "SWIFT" else ""),
                },
            )
        )
    if errors and not out:
        raise http.SourceError("; ".join(errors))
    return out


# --- Paysend ------------------------------------------------------------------------------


def parse_paysend(html: str, reference: dict[str, float], ccy: str = "EUR") -> list[Quote]:
    pair = CURRENCIES[ccy]
    url, origin = PAYSEND_PAGES[ccy]
    at = html.find('"calculator":{"sourceCountry"')
    tx_at = html.find('"transaction":{', at) if at >= 0 else -1
    if tx_at < 0:
        raise http.SchemaError("paysend: no calculator state in the page")
    try:
        # Decode the transaction object alone: the rest of the state holds page copy whose
        # escapes are not always valid JSON.
        tx, _ = json.JSONDecoder().raw_decode(html, tx_at + len('"transaction":'))
        special = (tx.get("conversionRateSpecial") or [{}])[0]
        standard = _num((special.get("$") or {}).get("rate_orig")) or _num(tx["conversionRate"])
        tiers = [
            [float(o["$"]["range_low"]), float(o["$"]["range_high"]), float(o["$"]["rate"])]
            for o in special.get("offer") or []
        ]
        fee = float(tx.get("commissionAmount") or 0.0)
        fee_ccy = tx.get("commissionCurrency") or ccy
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise http.SchemaError(f"paysend: unexpected calculator shape ({exc})") from exc
    if tx.get("currencyToBeDebited") != ccy or tx.get("currencyToBeCredited") != "AMD":
        raise http.SchemaError(f"paysend: the page is not a {ccy} to AMD quote")
    if fee_ccy != ccy or not plausible(standard, reference.get(pair)):
        return []
    return [
        Quote(
            provider="paysend",
            name="Paysend",
            kind="transfer",
            pair=pair,
            channel="transfer",
            buy=standard,
            fee_fixed=fee,
            source="paysend",
            url=url,
            meta={
                "tiers": [t for t in tiers if plausible(t[2], reference.get(pair))],
                "promo_rate": _num(tx.get("conversionRate")),
                "estimated_delivery": (tx.get("captions") or {}).get("processingTime"),
                "note": f"Card transfer from {origin} account to an Armenian card, "
                "for a returning customer",
            },
        )
    ]


def fetch_paysend(reference: dict[str, float]) -> list[Quote]:
    out: list[Quote] = []
    errors = []
    for ccy, (url, _) in PAYSEND_PAGES.items():
        try:
            out.extend(parse_paysend(http.fetch_text("paysend", url), reference, ccy))
        except http.SourceError as exc:
            errors.append(str(exc))
    if errors and not out:
        raise http.SourceError("; ".join(errors))
    return out
