from datetime import date

from insider_trades.models import Market, TradeType
from insider_trades.store import TradeQuery
from insider_trades.sync import sync_all, sync_market


def test_sync_is_idempotent(store, settings, client):
    r1 = sync_market(store, Market.NORWAY, settings, client, since=date(2025, 9, 1))
    assert (r1.fetched, r1.inserted, r1.updated) == (35, 35, 0)
    r2 = sync_market(store, Market.NORWAY, settings, client, since=date(2025, 9, 1))
    assert (r2.fetched, r2.inserted, r2.updated) == (35, 0, 35)
    items, total = store.query(TradeQuery(market=Market.NORWAY, limit=500))
    assert total == 35 and len(items) == 35


def test_sync_all_both_markets(store, settings, client):
    results = sync_all(store, settings, since=date(2025, 9, 1), client=client)
    assert results[Market.NORWAY].inserted == 35
    assert results[Market.SWEDEN].inserted == 4
    assert store.latest_published(Market.SWEDEN).date() == date(2025, 9, 5)


def test_query_filters_and_sorting(store, settings, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    buys, n = store.query(TradeQuery(trade_type=TradeType.BUY))
    assert n >= 2 and all(t.trade_type is TradeType.BUY for t in buys)
    hits, n = store.query(TradeQuery(text="kjølvik"))
    assert n == 1 and hits[0].ticker == "ARR"
    by_value, _ = store.query(TradeQuery(sort="value", descending=True, limit=3))
    assert by_value[0].value >= by_value[1].value
    # Null values sort last even ascending.
    asc, _ = store.query(TradeQuery(sort="value", descending=False, limit=500))
    assert asc[0].value is not None and asc[-1].value is None
    se, n = store.query(TradeQuery(market=Market.SWEDEN, date_from=date(2025, 9, 5)))
    assert n == 2
    _, n = store.query(TradeQuery(min_value=1_000_000))
    assert n == 2  # Volvo and Investor rows


def test_summary(store, settings, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    s = store.summary(TradeQuery())
    assert s["total"] == 39
    assert s["by_type"]["buy"]["count"] >= 2
    assert s["top_sells"][0]["issuer"] == "Investor AB"
    assert set(s["last_sync"]) == {"NO", "SE"}
    assert s["last_sync"]["NO"]["error"] is None


def test_failed_sync_is_recorded(store, settings):
    import httpx

    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    import pytest

    with pytest.raises(httpx.HTTPStatusError):
        sync_market(store, Market.NORWAY, settings, bad)
    s = store.summary(TradeQuery())
    assert "503" in s["last_sync"]["NO"]["error"]
