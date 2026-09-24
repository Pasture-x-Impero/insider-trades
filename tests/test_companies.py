from datetime import date

from fastapi.testclient import TestClient

from insider_trades.api import create_app
from insider_trades.models import Market
from insider_trades.prices import PriceService, QuoteService
from insider_trades.render import render_html
from insider_trades.store import TradeQuery
from insider_trades.sync import sync_all
from tests.test_render import extract_data


def test_store_companies_aggregates_buys_and_sells(store, settings, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    rows = {(r["market"], r["issuer"]): r for r in store.companies(TradeQuery())}
    volvo = rows[("SE", "Volvo, AB")]
    assert volvo["buy_count"] == 1 and volvo["buy_value"] == 5000 * 281.5
    assert volvo["sell_count"] == 0 and volvo["net_value"] == 5000 * 281.5
    investor = rows[("SE", "Investor AB")]
    assert investor["sell_count"] == 1 and investor["net_value"] == -(12000 * 312)
    arr = rows[("NO", "Arribatec Group ASA")]
    assert arr["trade_count"] == 3 and arr["buy_count"] == 1 and arr["ticker"] == "ARR"
    only_se = store.companies(TradeQuery(market=Market.SWEDEN))
    assert all(r["market"] == "SE" for r in only_se) and len(only_se) == 4


def test_quote_service_uses_crumb_and_cache(store, client):
    qs = QuoteService(client, store)
    info = qs.quotes(["ARR.OL", "VOLV-B.ST", "UNKNOWN.OL"])
    assert info["ARR.OL"]["market_cap"] == 5_000_000
    assert info["VOLV-B.ST"]["currency"] == "SEK"
    assert "UNKNOWN.OL" not in info
    # Second call is served from cache, including the negative result.
    assert store.cache_get("quote:UNKNOWN.OL", 3600) == ""
    assert qs.quotes(["ARR.OL"])["ARR.OL"]["name"] == "Arribatec"


def test_api_companies_with_market_cap(settings, store, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    with TestClient(create_app(settings, store, client)) as c:
        rows = c.get("/api/companies").json()
        by = {r["issuer"]: r for r in rows}
        arr = by["Arribatec Group ASA"]
        assert arr["symbol"] == "ARR.OL" and arr["market_cap"] == 5_000_000
        assert abs(arr["net_pct_of_cap"] - 54544.64 / 5_000_000) < 1e-9
        assert rows[0]["issuer"] == "Arribatec Group ASA"  # highest net share of market cap first
        # The mocked symbol search answers VOLV-B.ST for most ISINs, so Investor gets a cap too.
        assert by["Investor AB"]["net_pct_of_cap"] < 0
        # Sinch only resolves to a Toronto listing priced in CAD: the cap must not be used.
        sinch = by["Sinch AB"]
        assert sinch["symbol"] == "LUG.TO" and sinch["market_cap"] is None
        assert sinch["market_cap_currency"] == "CAD" and sinch["net_pct_of_cap"] is None
        assert c.get("/api/companies", params={"market": "NO"}).json()[0]["market"] == "NO"


def test_render_embeds_quotes(store, settings, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    html = render_html(store, TradeQuery(limit=500), PriceService(client, store))
    data = extract_data(html)
    assert data["quotes"]["ARR.OL"]["market_cap"] == 5_000_000
    assert data["quotes"]["VOLV-B.ST"]["market_cap"] == 560_000_000_000


def test_resolve_symbol_prefers_home_exchange(store, client):
    ps = PriceService(client, store)
    # Search returns a Toronto listing first and a Stockholm one second; Stockholm wins for Sweden.
    assert ps.resolve_symbol(Market.SWEDEN, None, "SE0000115446") == "VOLV-B.ST"
    # For Norway neither is OSL or .OL, so the first equity is the fallback.
    assert ps.resolve_symbol(Market.NORWAY, None, "NO0000000000") == "LUG.TO"
