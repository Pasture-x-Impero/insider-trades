import json
import re
from datetime import date

from insider_trades.cli import main
from insider_trades.prices import PriceService
from insider_trades.render import render_html
from insider_trades.store import TradeQuery
from insider_trades.sync import sync_all


def extract_data(html: str) -> dict:
    m = re.search(r'<script id="insider-data" type="application/json">(.*?)</script>', html, re.S)
    assert m, "embedded data block missing"
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_render_embeds_data_and_assets(store, settings, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    html = render_html(store, TradeQuery(limit=500), PriceService(client, store))
    assert "<style>" in html and 'href="/static/styles.css"' not in html
    assert 'src="/static/app.js"' not in html and "const api = dataEl" in html
    data = extract_data(html)
    assert len(data["trades"]) == 39
    assert data["total_in_store"] == 39
    arr = next(t for t in data["trades"] if t["ticker"] == "ARR")
    assert arr["symbol"] == "ARR.OL"
    assert arr["insider_name"] == "Ole Jakob Kjølvik"
    assert "ARR.OL" in data["prices"] and len(data["prices"]["ARR.OL"]["points"]) == 4
    volvo = next(t for t in data["trades"] if t["issuer"].startswith("Volvo"))
    assert volvo["symbol"] == "VOLV-B.ST"
    assert set(data["last_sync"]) == {"NO", "SE"}


def test_render_without_prices_and_filters(store, settings, client):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    from insider_trades.models import Market

    html = render_html(store, TradeQuery(market=Market.SWEDEN, limit=500))
    data = extract_data(html)
    assert len(data["trades"]) == 4 and data["prices"] == {}
    assert all(t["symbol"] is None for t in data["trades"])


def test_render_escapes_closing_script_tags(store, settings, client):
    from datetime import datetime, timezone

    from insider_trades.models import Market, Trade

    store.upsert([Trade(market=Market.NORWAY, source_id="x", published_at=datetime.now(timezone.utc),
                        issuer="Evil ASA", raw_text="</script><script>alert(1)</script>")])
    html = render_html(store, TradeQuery())
    body = html.split('id="insider-data"', 1)[1]
    assert "</script><script>alert" not in body
    assert extract_data(html)["trades"][0]["raw_text"].startswith("</script>")


def test_cli_render_no_sync(store, settings, client, tmp_path, monkeypatch):
    sync_all(store, settings, since=date(2025, 9, 1), client=client)
    monkeypatch.setenv("INSIDER_DB", str(settings.db_path))
    out = tmp_path / "out.html"
    assert main(["render", "--out", str(out), "--no-sync", "--no-prices", "--days", "3650"]) == 0
    assert out.exists() and len(extract_data(out.read_text())["trades"]) == 39
