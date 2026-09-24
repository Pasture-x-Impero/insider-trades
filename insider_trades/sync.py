"""Pull new announcements from each source into the store."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import httpx

from .config import Settings
from .models import Market
from .sources import FinansinspektionenSource, OsloBorsSource
from .store import Store, SyncResult

log = logging.getLogger(__name__)

OVERLAP_DAYS = 3  # re-fetch a few days so corrections and late detail fetches are picked up


def make_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout,
        headers={"user-agent": settings.user_agent, "accept-language": "en,nb,sv"},
        follow_redirects=True,
    )


def build_source(market: Market, client: httpx.Client, settings: Settings):
    if market is Market.NORWAY:
        return OsloBorsSource(client, max_detail_fetch=settings.max_detail_fetch)
    return FinansinspektionenSource(client)


def since_for(store: Store, market: Market, settings: Settings, override: date | None) -> date:
    if override:
        return override
    latest = store.latest_published(market)
    if latest:
        return (latest - timedelta(days=OVERLAP_DAYS)).date()
    return date.today() - timedelta(days=settings.initial_lookback_days)


def sync_market(store: Store, market: Market, settings: Settings,
                client: httpx.Client | None = None, since: date | None = None) -> SyncResult:
    started = datetime.now(UTC)
    own_client = client is None
    client = client or make_client(settings)
    try:
        source = build_source(market, client, settings)
        start = since_for(store, market, settings, since)
        trades = source.fetch(start)
        inserted, updated = store.upsert(trades)
        result = SyncResult(market=market, fetched=len(trades), inserted=inserted, updated=updated)
        store.record_sync(market, result, None, started)
        log.info("%s: fetched=%d inserted=%d updated=%d", market.value, len(trades), inserted, updated)
        return result
    except Exception as exc:  # noqa: BLE001 - we record and re-raise every failure
        store.record_sync(market, None, f"{type(exc).__name__}: {exc}", started)
        raise
    finally:
        if own_client:
            client.close()


def sync_all(store: Store, settings: Settings, markets: list[Market] | None = None,
             since: date | None = None, client: httpx.Client | None = None,
             ) -> dict[Market, SyncResult | Exception]:
    results: dict[Market, SyncResult | Exception] = {}
    own_client = client is None
    client = client or make_client(settings)
    try:
        for market in markets or list(Market):
            try:
                results[market] = sync_market(store, market, settings, client, since)
            except Exception as exc:  # noqa: BLE001
                log.error("%s sync failed: %s", market.value, exc)
                results[market] = exc
    finally:
        if own_client:
            client.close()
    return results
