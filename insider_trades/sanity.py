"""Plausibility checks for trade prices and values.

Filings contain mistakes (a total written in the price field, a count in the
price field) and free text parsing can pick the wrong amount. A single bad row
can dominate every sum on the page, so implausible prices and values are
blanked before publishing and the reason is recorded on the trade.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# A trade price more than this many times the current share price (or less than
# the inverse for shares) is treated as wrong. Share prices do move, but not by
# a factor of 20 within the 90 day window the page covers.
PRICE_RATIO_LIMIT = 20.0
# Without a quote, values above these amounts in the trade currency are rejected.
ABSOLUTE_LIMIT = {"SEK": 100e9, "NOK": 100e9, "DKK": 100e9}
DEFAULT_ABSOLUTE_LIMIT = 10e9
SHARE_TYPES = {"buy", "sell"}
# Rough NOK value of one unit, only for order-of-magnitude comparisons across
# currencies. A factor of 20 threshold makes exact rates irrelevant.
ROUGH_NOK = {"NOK": 1.0, "SEK": 1.0, "DKK": 1.55, "EUR": 11.5, "USD": 10.5, "GBP": 13.5,
             "CHF": 12.0, "CAD": 7.7}
# No Nordic share trades above this price in NOK equivalent.
MAX_SHARE_PRICE_NOK = 100_000.0


def to_nok(amount: float, currency: str) -> float | None:
    rate = ROUGH_NOK.get((currency or "").upper())
    return amount * rate if rate else None


def _reject(trade: dict, reason: str) -> None:
    trade["suspect"] = reason
    trade["price"] = None
    trade["value"] = None
    trade["parse_confidence"] = min(trade.get("parse_confidence") or 1.0, 0.3)


def normalise_quote(quote: dict | None) -> dict | None:
    """London quotes are in pence ('GBp' or 'GBX'); convert them to pounds.

    This must happen before any upper-casing, since 'GBp'.upper() is 'GBP'.
    """
    if not quote or quote.get("currency") not in ("GBp", "GBX", "GBx"):
        return quote
    q = dict(quote)
    q["currency"] = "GBP"
    if q.get("price") is not None:
        q["price"] = q["price"] / 100
    return q


def check_trade(trade: dict, quote: dict | None) -> str | None:
    """Blank price and value on the trade dict if they are implausible. Returns the reason."""
    quote = normalise_quote(quote)
    price, value = trade.get("price"), trade.get("value")
    currency = (trade.get("currency") or "").upper()
    if price is None and value is None:
        return None
    same_currency = bool(quote and quote.get("currency") and quote["currency"].upper() == currency)
    if price:
        price_nok = to_nok(price, currency)
        if price_nok and price_nok > MAX_SHARE_PRICE_NOK:
            reason = f"price {price:g} {currency} per unit is above any Nordic share price"
            _reject(trade, reason)
            return reason
    ratio = None
    if same_currency and price and quote.get("price"):
        ratio = price / quote["price"]
    elif price and quote and quote.get("price") and quote.get("currency"):
        a, b = to_nok(price, currency), to_nok(quote["price"], quote["currency"])
        if a and b:
            ratio = a / b
    if ratio is not None:
        too_low = trade.get("trade_type") in SHARE_TYPES and ratio < 1 / PRICE_RATIO_LIMIT
        if ratio > PRICE_RATIO_LIMIT or too_low:
            reason = (f"price {price:g} {currency} is {ratio:.3g}x the current share price "
                      f"{quote['price']:g} {quote.get('currency') or ''}")
            _reject(trade, reason)
            return reason
    if same_currency and value and quote.get("market_cap") and value > quote["market_cap"]:
        reason = f"value {value:,.0f} exceeds the market cap {quote['market_cap']:,.0f}"
        _reject(trade, reason)
        return reason
    limit = ABSOLUTE_LIMIT.get(currency, DEFAULT_ABSOLUTE_LIMIT)
    if value and value > limit:
        reason = f"value {value:,.0f} {currency} is above the plausibility limit"
        _reject(trade, reason)
        return reason
    return None


def check_all(trades: list[dict], quotes: dict[str, dict]) -> list[tuple[dict, str]]:
    flagged = []
    for t in trades:
        reason = check_trade(t, quotes.get(t.get("symbol") or ""))
        if reason:
            flagged.append((t, reason))
    for t, reason in flagged:
        log.warning("sanity: blanked %s %s %s (%s): %s", t.get("market"), t.get("issuer"),
                    t.get("published_at", "")[:10], t.get("source_id"), reason)
    return flagged
