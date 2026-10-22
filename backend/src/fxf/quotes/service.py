"""GET /api/quotes/{pair}: what each provider would give for an amount, best first."""

from __future__ import annotations

import datetime as dt
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.api.schemas import ProviderQuoteOut, QuoteReference, QuotesResponse, UnavailableProvider
from fxf.models import ProviderQuote, Rate

LOOKBACK: Final = dt.timedelta(days=4)
STALE_AFTER: Final = dt.timedelta(hours=26)
QUOTE_PAIRS: Final = ("EURAMD", "USDAMD", "GBPAMD", "RUBAMD")
DISCLAIMER: Final = (
    "Indicative rates collected from public pages, not offers. Banks may give a better rate "
    "for large amounts, and transfer services change fees often. Check with the provider "
    "before you convert."
)
UNAVAILABLE: Final = (
    UnavailableProvider(
        provider="revolut",
        name="Revolut",
        reason=(
            "Revolut does not publish its dram rate for automated reading. Check the app: you "
            "cannot hold dram there, so a transfer to Armenia converts when you send, and "
            "weekend exchanges cost 1% more."
        ),
        url="https://www.revolut.com/",
    ),
)


def fee_for(q: ProviderQuote, amount: float) -> float:
    """Fee in the base currency. Wise: interpolate the stored quotes (linear between them,
    the end slopes beyond); others: fee_fixed + fee_pct, or none."""
    curve = sorted((float(a), float(f)) for a, f, *_ in (q.meta or {}).get("fee_curve") or [])
    if len(curve) == 1:
        a0, f0 = curve[0]
        return f0 * amount / a0
    if len(curve) >= 2:
        seg = next(
            ((curve[i], curve[i + 1]) for i in range(len(curve) - 1) if amount <= curve[i + 1][0]),
            (curve[-2], curve[-1]),
        )
        (a0, f0), (a1, f1) = seg
        return max(f0 + (f1 - f0) * (amount - a0) / (a1 - a0), 0.0)
    fixed = float(q.fee_fixed) if q.fee_fixed is not None else 0.0
    pct = q.fee_pct or 0.0
    return fixed + amount * pct / 100.0


def rate_for(q: ProviderQuote, amount: float) -> float:
    """The provider's rate for this amount: the tier with the highest floor at or below the
    amount, when the amount is inside it. Tier ceilings are given to the cent (886.00 to
    1331.99, then 1332.00), so the gap between two tiers belongs to the lower one."""
    tiers = sorted(
        (float(lo), float(hi), float(r)) for lo, hi, r in (q.meta or {}).get("tiers") or []
    )
    tier = next((t for t in reversed(tiers) if t[0] <= amount), None)
    if tier is not None and amount < tier[1] + 0.01:
        return tier[2]
    return float(q.buy)


def build_quotes(session: Session, pair: str, amount: float, now: dt.datetime) -> QuotesResponse:
    ref = session.execute(
        select(Rate.rate, Rate.date, Rate.source)
        .where(Rate.pair == pair)
        .order_by(Rate.date.desc())
        .limit(1)
    ).first()
    reference = float(ref.rate) if ref else None
    rows = session.scalars(
        select(ProviderQuote)
        .where(ProviderQuote.pair == pair, ProviderQuote.fetched_at >= now - LOOKBACK)
        .order_by(ProviderQuote.provider, ProviderQuote.channel, ProviderQuote.fetched_at.desc())
        .distinct(ProviderQuote.provider, ProviderQuote.channel)
    ).all()
    quotes = []
    for q in rows:
        if q.buy is None:
            continue
        rate = rate_for(q, amount)
        fee_base = fee_for(q, amount)
        if fee_base >= amount:
            continue  # the fee eats the whole amount: not an option for it
        net = (amount - fee_base) * rate
        quotes.append(
            ProviderQuoteOut(
                provider=q.provider,
                name=q.name,
                kind=q.kind,
                channel=q.channel,
                rate=rate,
                fee=round(fee_base * rate, 2),
                net=round(net, 2),
                vs_reference_pct=round((net / (amount * reference) - 1) * 100, 3)
                if reference
                else None,
                fetched_at=q.fetched_at,
                quoted_at=q.quoted_at,
                stale=now - q.fetched_at > STALE_AFTER,
                url=q.url,
                note=(q.meta or {}).get("note"),
                delivery=(q.meta or {}).get("estimated_delivery"),
            )
        )
    quotes.sort(key=lambda x: (x.stale, -x.net))
    return QuotesResponse(
        pair=pair,
        amount=amount,
        reference=QuoteReference(source="CBA", rate=reference, date=ref.date) if ref else None,
        as_of=max((q.fetched_at for q in quotes), default=None),
        quotes=quotes,
        unavailable=list(UNAVAILABLE),
        indicative=True,
        disclaimer=DISCLAIMER,
    )
