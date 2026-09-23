"""Daily close prices from Yahoo Finance, used to show how a stock moved after a trade."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from .models import Market
from .store import Store

log = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
EXCHANGE_SUFFIX = {Market.NORWAY: ".OL", Market.SWEDEN: ".ST"}
PREFERRED_EXCHANGE = {Market.NORWAY: "OSL", Market.SWEDEN: "STO"}
CACHE_SECONDS = 6 * 3600
SYMBOL_CACHE_SECONDS = 30 * 24 * 3600


class PriceService:
    def __init__(self, client: httpx.Client, store: Store):
        self.client = client
        self.store = store

    def resolve_symbol(self, market: Market, ticker: str | None, isin: str | None,
                       issuer: str | None = None) -> str | None:
        if ticker:
            return f"{ticker}{EXCHANGE_SUFFIX[market]}"
        query = isin or issuer
        if not query:
            return None
        key = f"symbol:{market}:{query}"
        cached = self.store.cache_get(key, SYMBOL_CACHE_SECONDS)
        if cached is not None:
            return cached or None
        symbol = ""
        try:
            r = self.client.get(SEARCH_URL, params={"q": query, "quotesCount": 10, "newsCount": 0})
            r.raise_for_status()
            quotes = r.json().get("quotes", [])
            equities = [q for q in quotes if q.get("quoteType") == "EQUITY" and q.get("symbol")]
            preferred = [q for q in equities if q.get("exchange") == PREFERRED_EXCHANGE[market]]
            chosen = (preferred or equities or [None])[0]
            symbol = chosen["symbol"] if chosen else ""
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("symbol lookup failed for %s: %s", query, exc)
            return None
        self.store.cache_put(key, symbol)
        return symbol or None

    def history(self, symbol: str, start: date, end: date | None = None) -> dict:
        end = end or date.today()
        key = f"chart:{symbol}:{start}:{end}"
        cached = self.store.cache_get(key, CACHE_SECONDS)
        if cached:
            return json.loads(cached)
        period1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
        period2 = int((datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)).timestamp())
        r = self.client.get(
            CHART_URL.format(symbol=symbol),
            params={"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"},
        )
        r.raise_for_status()
        payload = self.parse_chart(symbol, r.json())
        self.store.cache_put(key, json.dumps(payload))
        return payload

    @staticmethod
    def parse_chart(symbol: str, data: dict) -> dict:
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            err = (data.get("chart") or {}).get("error") or {}
            raise ValueError(err.get("description") or f"no chart data for {symbol}")
        res = result[0]
        stamps = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        points = [
            {"date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(), "close": round(c, 4)}
            for ts, c in zip(stamps, closes)
            if c is not None
        ]
        meta = res.get("meta") or {}
        return {
            "symbol": symbol,
            "currency": meta.get("currency"),
            "name": meta.get("shortName") or meta.get("longName"),
            "last": meta.get("regularMarketPrice"),
            "points": points,
        }
