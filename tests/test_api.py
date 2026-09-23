from datetime import date

from fastapi.testclient import TestClient

from insider_trades.api import create_app
from insider_trades.sync import sync_all


def make(settings, store, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    # Swap in the fake transport for the app's own client too.
    app = create_app(settings, store, client)
    return TestClient(app)


def test_index_and_static(settings, store, client):
    with make(settings, store, client) as c:
        assert "<title>Insider Trades</title>" in c.get("/").text
        assert c.get("/static/app.js").status_code == 200
        assert c.get("/api/health").json()["status"] == "ok"


def test_list_and_filter(settings, store, client):
    with make(settings, store, client) as c:
        r = c.get("/api/trades", params={"market": "NO", "limit": 10}).json()
        assert r["total"] == 35 and len(r["items"]) == 10
        r = c.get("/api/trades", params={"q": "Volvo"}).json()
        assert r["total"] == 1 and r["items"][0]["market"] == "SE"
        r = c.get("/api/trades", params={"type": "sell", "from": "2025-09-01", "to": "2025-09-30"}).json()
        assert all(i["trade_type"] == "sell" for i in r["items"])
        assert c.get("/api/trades", params={"market": "XX"}).status_code == 422


def test_detail_prices_and_summary(settings, store, client):
    with make(settings, store, client) as c:
        arr = c.get("/api/trades", params={"q": "ARR"}).json()["items"][0]
        d = c.get(f"/api/trades/{arr['id']}").json()
        assert d["insider_name"] == "Ole Jakob Kjølvik"
        p = c.get(f"/api/prices/{arr['id']}").json()
        assert p["symbol"] == "ARR.OL"
        assert len(p["points"]) == 4  # the None close is dropped
        assert p["trade_date"] == "2025-09-05"
        assert p["anchor_close"] == 0.64  # first close on or after the trade date
        s = c.get("/api/summary").json()
        assert s["total"] == 39
        assert c.get("/api/summary", params={"days": 1}).json()["total"] == 0
        assert c.get("/api/summary", params={"market": "SE", "type": "sell"}).json()["total"] == 1
        assert c.get("/api/trades/999999").status_code == 404
        # Swedish issuer resolves via ISIN search
        volvo = c.get("/api/trades", params={"q": "Volvo"}).json()["items"][0]
        assert c.get(f"/api/prices/{volvo['id']}").json()["symbol"] == "VOLV-B.ST"


def test_sync_endpoint(settings, store, client):
    app = create_app(settings, store, client)
    with TestClient(app) as c:
        r = c.post("/api/sync", params={"market": "SE", "since": "2025-09-01"}).json()
        assert r == {"SE": {"market": "SE", "fetched": 4, "inserted": 4, "updated": 0}}
        assert c.get("/api/issuers", params={"q": "vol"}).json()[0]["issuer"] == "Volvo, AB"
