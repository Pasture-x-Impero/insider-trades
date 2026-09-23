"""SQLite persistence. One table of trades, upserted by (market, source_id)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Market, StoredTrade, Trade, TradeType

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    source_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    transaction_date TEXT,
    issuer TEXT NOT NULL,
    ticker TEXT,
    isin TEXT,
    insider_name TEXT,
    position TEXT,
    close_associate INTEGER NOT NULL DEFAULT 0,
    trade_type TEXT NOT NULL,
    instrument TEXT,
    quantity REAL,
    price REAL,
    currency TEXT,
    value REAL,
    venue TEXT,
    status TEXT,
    title TEXT,
    raw_text TEXT,
    source_url TEXT,
    parse_confidence REAL NOT NULL DEFAULT 1.0,
    fetched_at TEXT NOT NULL,
    UNIQUE (market, source_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_published ON trades (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_issuer ON trades (issuer);
CREATE INDEX IF NOT EXISTS idx_trades_type ON trades (trade_type);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    fetched INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS price_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    cached_at TEXT NOT NULL
);
"""

COLUMNS = [
    "market", "source_id", "published_at", "transaction_date", "issuer", "ticker", "isin",
    "insider_name", "position", "close_associate", "trade_type", "instrument", "quantity",
    "price", "currency", "value", "venue", "status", "title", "raw_text", "source_url",
    "parse_confidence",
]


@dataclass
class TradeQuery:
    market: Market | None = None
    trade_type: TradeType | None = None
    date_from: date | None = None
    date_to: date | None = None
    text: str | None = None
    issuer: str | None = None
    min_value: float | None = None
    sort: str = "published_at"
    descending: bool = True
    limit: int = 100
    offset: int = 0


@dataclass
class SyncResult:
    market: Market
    fetched: int
    inserted: int
    updated: int


SORTABLE = {"published_at", "transaction_date", "issuer", "value", "quantity", "price"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, detect_types=0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ----- writes -------------------------------------------------------

    def upsert(self, trades: list[Trade]) -> tuple[int, int]:
        """Insert or update trades. Returns (inserted, updated)."""
        inserted = updated = 0
        now = _now()
        with self._conn() as c:
            for t in trades:
                row = self._row(t)
                existing = c.execute(
                    "SELECT id FROM trades WHERE market=? AND source_id=?",
                    (row["market"], row["source_id"]),
                ).fetchone()
                if existing:
                    sets = ", ".join(f"{k}=:{k}" for k in COLUMNS if k not in ("market", "source_id"))
                    c.execute(
                        f"UPDATE trades SET {sets}, fetched_at=:fetched_at "
                        "WHERE market=:market AND source_id=:source_id",
                        {**row, "fetched_at": now},
                    )
                    updated += 1
                else:
                    cols = ", ".join(COLUMNS + ["fetched_at"])
                    vals = ", ".join(f":{k}" for k in COLUMNS + ["fetched_at"])
                    c.execute(f"INSERT INTO trades ({cols}) VALUES ({vals})", {**row, "fetched_at": now})
                    inserted += 1
        return inserted, updated

    @staticmethod
    def _row(t: Trade) -> dict:
        d = t.model_dump(mode="json")
        d["close_associate"] = 1 if t.close_associate else 0
        return {k: d.get(k) for k in COLUMNS}

    def record_sync(self, market: Market, result: SyncResult | None, error: str | None,
                    started_at: datetime) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO sync_runs (market, started_at, finished_at, fetched, inserted, updated, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    market.value, started_at.isoformat(), _now(),
                    result.fetched if result else 0,
                    result.inserted if result else 0,
                    result.updated if result else 0,
                    error,
                ),
            )

    # ----- reads --------------------------------------------------------

    def get(self, trade_id: int) -> StoredTrade | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return self._to_model(row) if row else None

    def latest_published(self, market: Market) -> datetime | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(published_at) AS m FROM trades WHERE market=?", (market.value,)
            ).fetchone()
        return datetime.fromisoformat(row["m"]) if row and row["m"] else None

    def query(self, q: TradeQuery) -> tuple[list[StoredTrade], int]:
        where, params = self._where(q)
        sort = q.sort if q.sort in SORTABLE else "published_at"
        direction = "DESC" if q.descending else "ASC"
        # NULLs last regardless of direction, so unparsed values do not float to the top.
        order = f"({sort} IS NULL), {sort} {direction}, published_at DESC"
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM trades {where}", params).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM trades {where} ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, q.limit, q.offset),
            ).fetchall()
        return [self._to_model(r) for r in rows], total

    def summary(self, q: TradeQuery) -> dict:
        where, params = self._where(q)
        with self._conn() as c:
            by_type = {
                r["trade_type"]: {"count": r["n"], "value": r["v"] or 0.0}
                for r in c.execute(
                    f"SELECT trade_type, COUNT(*) n, SUM(value) v FROM trades {where} GROUP BY trade_type",
                    params,
                )
            }
            top_buys = [
                dict(r)
                for r in c.execute(
                    f"SELECT issuer, ticker, market, COUNT(*) n, SUM(value) v FROM trades {where}"
                    f" {'AND' if where else 'WHERE'} trade_type='buy' AND value IS NOT NULL"
                    " GROUP BY market, issuer ORDER BY v DESC LIMIT 10",
                    params,
                )
            ]
            top_sells = [
                dict(r)
                for r in c.execute(
                    f"SELECT issuer, ticker, market, COUNT(*) n, SUM(value) v FROM trades {where}"
                    f" {'AND' if where else 'WHERE'} trade_type='sell' AND value IS NOT NULL"
                    " GROUP BY market, issuer ORDER BY v DESC LIMIT 10",
                    params,
                )
            ]
            last_sync = {
                r["market"]: dict(r)
                for r in c.execute(
                    "SELECT market, MAX(finished_at) finished_at, fetched, inserted, updated, error"
                    " FROM sync_runs GROUP BY market"
                )
            }
            total = c.execute(f"SELECT COUNT(*) FROM trades {where}", params).fetchone()[0]
        return {
            "total": total,
            "by_type": by_type,
            "top_buys": top_buys,
            "top_sells": top_sells,
            "last_sync": last_sync,
        }

    def issuers(self, prefix: str, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT issuer, ticker, market, COUNT(*) n FROM trades"
                " WHERE issuer LIKE ? OR ticker LIKE ? GROUP BY market, issuer"
                " ORDER BY (issuer LIKE ? OR ticker LIKE ?) DESC, n DESC, issuer LIMIT ?",
                (f"%{prefix}%", f"{prefix}%", f"{prefix}%", f"{prefix}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _where(q: TradeQuery) -> tuple[str, list]:
        clauses, params = [], []
        if q.market:
            clauses.append("market=?")
            params.append(q.market.value)
        if q.trade_type:
            clauses.append("trade_type=?")
            params.append(q.trade_type.value)
        if q.date_from:
            clauses.append("published_at >= ?")
            params.append(q.date_from.isoformat())
        if q.date_to:
            clauses.append("published_at < ?")
            params.append(f"{q.date_to.isoformat()}T23:59:59.999999")
        if q.issuer:
            clauses.append("issuer = ?")
            params.append(q.issuer)
        if q.min_value is not None:
            clauses.append("value >= ?")
            params.append(q.min_value)
        if q.text:
            like = f"%{q.text}%"
            clauses.append("(issuer LIKE ? OR ticker LIKE ? OR insider_name LIKE ? OR title LIKE ?)")
            params.extend([like, like, like, like])
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    @staticmethod
    def _to_model(row: sqlite3.Row) -> StoredTrade:
        d = dict(row)
        d["close_associate"] = bool(d["close_associate"])
        return StoredTrade(**d)

    # ----- price cache --------------------------------------------------

    def cache_get(self, key: str, max_age_seconds: int) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT payload, cached_at FROM price_cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["cached_at"])
        return row["payload"] if age.total_seconds() < max_age_seconds else None

    def cache_put(self, key: str, payload: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO price_cache (key, payload, cached_at) VALUES (?,?,?)",
                (key, payload, _now()),
            )
