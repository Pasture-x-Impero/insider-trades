"""HTTP API and static frontend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .models import Market, TradeType
from .prices import MARKET_CURRENCY, PriceService, QuoteService
from .store import Store, TradeQuery
from .sync import make_client, sync_all

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"


def create_app(settings: Settings | None = None, store: Store | None = None,
               client: httpx.Client | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or Store(settings.db_path)
    client = client or make_client(settings)
    prices = PriceService(client, store)
    quotes = QuoteService(client, store)
    sync_lock = asyncio.Lock()

    async def run_sync(markets: list[Market] | None = None, since: date | None = None) -> dict:
        async with sync_lock:
            results = await asyncio.to_thread(sync_all, store, settings, markets, since, client)
        return {
            m.value: ({"error": str(r)} if isinstance(r, Exception) else r.__dict__ | {"market": m.value})
            for m, r in results.items()
        }

    async def scheduler() -> None:
        if settings.sync_on_startup:
            try:
                await run_sync()
            except Exception as exc:  # noqa: BLE001
                log.error("startup sync failed: %s", exc)
        while settings.sync_interval_minutes > 0:
            await asyncio.sleep(settings.sync_interval_minutes * 60)
            try:
                await run_sync()
            except Exception as exc:  # noqa: BLE001
                log.error("scheduled sync failed: %s", exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(scheduler()) if settings.sync_interval_minutes >= 0 else None
        try:
            yield
        finally:
            if task:
                task.cancel()
            client.close()

    app = FastAPI(title="Insider Trades", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings

    @app.get("/api/trades")
    def list_trades(
        market: Market | None = None,
        type: TradeType | None = None,
        q: str | None = Query(default=None, max_length=100),
        issuer: str | None = None,
        date_from: date | None = Query(default=None, alias="from"),
        date_to: date | None = Query(default=None, alias="to"),
        min_value: float | None = None,
        sort: str = "published_at",
        order: str = "desc",
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        query = TradeQuery(
            market=market, trade_type=type, text=q, issuer=issuer, date_from=date_from,
            date_to=date_to, min_value=min_value, sort=sort, descending=order != "asc",
            limit=limit, offset=offset,
        )
        items, total = store.query(query)
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    @app.get("/api/trades/{trade_id}")
    def get_trade(trade_id: int):
        trade = store.get(trade_id)
        if not trade:
            raise HTTPException(404, "trade not found")
        return trade

    @app.get("/api/summary")
    def summary(
        market: Market | None = None,
        type: TradeType | None = None,
        q: str | None = Query(default=None, max_length=100),
        issuer: str | None = None,
        date_from: date | None = Query(default=None, alias="from"),
        date_to: date | None = Query(default=None, alias="to"),
        min_value: float | None = None,
        days: int | None = Query(default=None, ge=1, le=3650, description="shortcut for from=today-days"),
    ):
        if days and not date_from:
            date_from = date.today() - timedelta(days=days)
        query = TradeQuery(market=market, trade_type=type, text=q, issuer=issuer,
                           date_from=date_from, date_to=date_to, min_value=min_value)
        return store.summary(query)

    @app.get("/api/companies")
    def companies(
        market: Market | None = None,
        q: str | None = Query(default=None, max_length=100),
        date_from: date | None = Query(default=None, alias="from"),
        date_to: date | None = Query(default=None, alias="to"),
        min_value: float | None = None,
        with_caps: bool = True,
    ):
        query = TradeQuery(market=market, text=q, date_from=date_from, date_to=date_to, min_value=min_value)
        rows = store.companies(query)
        for r in rows:
            r["symbol"] = prices.resolve_symbol(Market(r["market"]), r["ticker"], r["isin"], r["issuer"]) \
                if with_caps else None
        info = quotes.quotes([r["symbol"] for r in rows if r["symbol"]]) if with_caps else {}
        for r in rows:
            qi = info.get(r["symbol"] or "")
            # Only a market cap in the trade currency gives a meaningful share.
            usable = bool(qi and qi.get("market_cap") and qi.get("currency") == MARKET_CURRENCY[Market(r["market"])])
            r["market_cap"] = qi["market_cap"] if usable else None
            r["market_cap_currency"] = qi.get("currency") if qi else None
            r["net_pct_of_cap"] = (r["net_value"] / r["market_cap"]) if usable else None
        rows.sort(key=lambda r: (r["net_pct_of_cap"] is None, -(r["net_pct_of_cap"] or 0), -r["net_value"]))
        return rows

    @app.get("/api/issuers")
    def issuers(q: str = Query(default="", max_length=100), limit: int = Query(default=20, le=100)):
        return store.issuers(q, limit)

    @app.get("/api/prices/{trade_id}")
    def prices_for_trade(trade_id: int, days_before: int = Query(default=30, ge=0, le=365)):
        trade = store.get(trade_id)
        if not trade:
            raise HTTPException(404, "trade not found")
        symbol = prices.resolve_symbol(trade.market, trade.ticker, trade.isin, trade.issuer)
        if not symbol:
            raise HTTPException(404, "could not resolve a price symbol for this issuer")
        anchor = trade.transaction_date or trade.published_at.date()
        try:
            data = prices.history(symbol, anchor - timedelta(days=days_before))
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"price lookup failed: {exc}") from exc
        anchor_close = next((p["close"] for p in data["points"] if p["date"] >= anchor.isoformat()), None)
        last = data["points"][-1]["close"] if data["points"] else None
        change = (last / anchor_close - 1) if anchor_close and last else None
        return {**data, "trade_date": anchor.isoformat(), "anchor_close": anchor_close,
                "change_since_trade": change}

    @app.post("/api/sync")
    async def trigger_sync(market: Market | None = None, since: date | None = None):
        return await run_sync([market] if market else None, since)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def app() -> FastAPI:
    """Factory for ``uvicorn insider_trades.api:app --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
