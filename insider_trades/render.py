"""Render the tracker as one self contained HTML file.

The page carries its data in a JSON block and the same frontend the server uses,
with the stylesheet and script inlined, so it works from disk, from GitHub Pages,
or attached to an email. No server and no network needed to read it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from .models import Market
from .prices import PriceService
from .store import Store, TradeQuery

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"


def collect_prices(store: Store, trades: list[dict], prices: PriceService) -> dict[str, dict]:
    """Fetch one daily close series per symbol covering every trade for that symbol."""
    by_symbol: dict[str, date] = {}
    for t in trades:
        symbol = prices.resolve_symbol(Market(t["market"]), t.get("ticker"), t.get("isin"), t.get("issuer"))
        t["symbol"] = symbol
        if not symbol:
            continue
        anchor = date.fromisoformat(t.get("transaction_date") or t["published_at"][:10])
        start = anchor - timedelta(days=30)
        by_symbol[symbol] = min(by_symbol.get(symbol, start), start)
    series: dict[str, dict] = {}
    for symbol, start in by_symbol.items():
        try:
            series[symbol] = prices.history(symbol, start)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("prices: skipping %s: %s", symbol, exc)
    return series


def render_html(store: Store, query: TradeQuery, prices: PriceService | None = None,
                title: str = "Insider Trades") -> str:
    items, total = store.query(query)
    trades = [t.model_dump(mode="json") for t in items]
    for t in trades:
        t["symbol"] = None
    price_series = collect_prices(store, trades, prices) if prices else {}
    summary = store.summary(TradeQuery())
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_in_store": total,
        "last_sync": summary["last_sync"],
        "trades": trades,
        "prices": price_series,
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    html = html.replace("<title>Insider Trades</title>", f"<title>{title}</title>")
    html = html.replace('<link rel="stylesheet" href="/static/styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace(
        '<script src="/static/app.js"></script>',
        f'<script id="insider-data" type="application/json">{data_json}</script>\n<script>\n{js}\n</script>',
    )
    return html


def render_to_file(store: Store, out: Path, query: TradeQuery, prices: PriceService | None = None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(store, query, prices), encoding="utf-8")
    return out
