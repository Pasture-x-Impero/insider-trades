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


def _reject(trade: dict, reason: str) -> None:
    trade["suspect"] = reason
    trade["price"] = None
    trade["value"] = None
    trade["parse_confidence"] = min(trade.get("parse_confidence") or 1.0, 0.3)


def check_trade(trade: dict, quote: dict | None) -> str | None:
    """Blank price and value on the trade dict if they are implausible. Returns the reason."""
    price, value = trade.get("price"), trade.get("value")
    currency = (trade.get("currency") or "").upper()
    if price is None and value is None:
        return None
    same_currency = bool(quote and quote.get("currency") and quote["currency"].upper() == currency)
    if same_currency and price and quote.get("price"):
        ratio = price / quote["price"]
        too_low = trade.get("trade_type") in SHARE_TYPES and ratio < 1 / PRICE_RATIO_LIMIT
        if ratio > PRICE_RATIO_LIMIT or too_low:
            reason = f"price {price:g} is {ratio:.3g}x the current share price {quote['price']:g}"
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
