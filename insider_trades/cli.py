"""Command line entry point: ``insider-trades render|sync|serve|export``."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date

from .config import Settings
from .models import Market, TradeType
from .store import COLUMNS, Store, TradeQuery
from .sync import sync_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insider-trades", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="fetch new announcements into the database")
    p_sync.add_argument("--market", choices=[m.value for m in Market], action="append")
    p_sync.add_argument("--since", type=date.fromisoformat, help="YYYY-MM-DD, overrides the incremental start")

    p_serve = sub.add_parser("serve", help="run the web app")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")

    p_render = sub.add_parser("render", help="write a self contained HTML file with the trades")
    p_render.add_argument("--out", default="insider-trades.html", help="output path (default insider-trades.html)")
    p_render.add_argument("--days", type=int, default=90, help="include trades published in the last N days")
    p_render.add_argument("--market", choices=[m.value for m in Market])
    p_render.add_argument("--limit", type=int, default=5000)
    p_render.add_argument("--no-sync", action="store_true", help="render from the database without fetching first")
    p_render.add_argument("--no-prices", action="store_true", help="skip fetching share prices for the charts")

    p_export = sub.add_parser("export", help="write stored trades as CSV to stdout")
    p_export.add_argument("--market", choices=[m.value for m in Market])
    p_export.add_argument("--type", choices=[t.value for t in TradeType])
    p_export.add_argument("--since", type=date.fromisoformat)
    p_export.add_argument("--limit", type=int, default=10000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()

    if args.command == "sync":
        store = Store(settings.db_path)
        markets = [Market(m) for m in args.market] if args.market else None
        results = sync_all(store, settings, markets, args.since)
        failed = False
        for market, result in results.items():
            if isinstance(result, Exception):
                failed = True
                print(f"{market.value}: FAILED {result}", file=sys.stderr)
            else:
                print(f"{market.value}: fetched={result.fetched} inserted={result.inserted} updated={result.updated}")
        return 1 if failed else 0

    if args.command == "render":
        from datetime import timedelta
        from pathlib import Path

        from .prices import PriceService
        from .render import render_to_file
        from .sync import make_client

        store = Store(settings.db_path)
        markets = [Market(args.market)] if args.market else None
        with make_client(settings) as client:
            if not args.no_sync:
                for market, result in sync_all(store, settings, markets, client=client).items():
                    if isinstance(result, Exception):
                        print(f"{market.value}: sync FAILED, rendering stored data ({result})", file=sys.stderr)
                    else:
                        print(f"{market.value}: fetched={result.fetched} inserted={result.inserted} updated={result.updated}")
            query = TradeQuery(market=markets[0] if markets else None,
                               date_from=date.today() - timedelta(days=args.days), limit=args.limit)
            prices = None if args.no_prices else PriceService(client, store)
            out = render_to_file(store, Path(args.out), query, prices)
        items, _ = store.query(query)
        print(f"wrote {out} with {len(items)} trades")
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run("insider_trades.api:app", factory=True, host=args.host, port=args.port,
                    reload=args.reload)
        return 0

    if args.command == "export":
        store = Store(settings.db_path)
        query = TradeQuery(
            market=Market(args.market) if args.market else None,
            trade_type=TradeType(args.type) if args.type else None,
            date_from=args.since, limit=args.limit,
        )
        items, _ = store.query(query)
        fields = ["id", *[c for c in COLUMNS if c != "raw_text"]]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in items:
            writer.writerow(t.model_dump(mode="json"))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
