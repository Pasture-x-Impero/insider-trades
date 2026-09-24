"""Finansinspektionen's insider register (insynsregistret) for Nasdaq Stockholm.

The search page offers a CSV export. The export is structured, so no text parsing
is needed. The site has no public API contract: the column names below cover
both the Swedish and English versions of the site and are matched loosely.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote_plus

import httpx

from ..models import Market, Trade, TradeType
from ..parsers.numbers import parse_number

log = logging.getLogger(__name__)

EXPORT_URL = "https://marknadssok.fi.se/publiceringsklient/en-GB/Search/Search"
EXPORT_CAP = 1000  # the export returns at most this many rows; larger windows are split
WINDOW_DAYS = 14
PUBLIC_URL = "https://marknadssok.fi.se/publiceringsklient/en-GB/Search/Search?SearchFunctionType=Insyn&Utgivare={issuer}"

# Normalised header -> field. Normalisation strips accents, case and punctuation.
HEADERS = {
    "publication date": "published", "publiceringsdatum": "published",
    "issuer": "issuer", "utgivare": "issuer",
    "lei code": "lei", "lei kod": "lei",
    "notifier": "notifier", "anmalningsskyldig": "notifier",
    "person discharging managerial responsibilities": "pdmr",
    "person i ledande stallning": "pdmr",
    "position": "position", "befattning": "position",
    "closely associated": "close", "narstaende": "close",
    "nature of transaction": "nature", "karaktar": "nature",
    "instrument type": "instrument_type", "instrumenttyp": "instrument_type",
    "instrument name": "instrument", "instrumentnamn": "instrument",
    "isin": "isin",
    "transaction date": "transaction_date", "transaktionsdatum": "transaction_date",
    "volume": "volume", "volym": "volume",
    "unit": "unit", "volymsenhet": "unit",
    "price": "price", "pris": "price",
    "currency": "currency", "valuta": "currency",
    "trading venue": "venue", "handelsplats": "venue",
    "status": "status",
    "details": "details", "detaljer": "details",
}

NATURE = {
    "acquisition": TradeType.BUY, "forvarv": TradeType.BUY,
    "disposal": TradeType.SELL, "avyttring": TradeType.SELL,
}
EXERCISE_WORDS = re.compile(r"exercise|utnyttjande|losen|inlosen", re.I)
ALLOTMENT_WORDS = re.compile(r"allot|tilldeln|share saving|aktiesparprogram|incentive|incitament|vesting|gift|gava", re.I)
YES_WORDS = {"yes", "ja", "true", "1"}


def normalise(header: str) -> str:
    s = unicodedata.normalize("NFKD", header)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


def decode_export(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    # Heuristic: UTF-16LE without BOM has NULs on every second byte.
    if len(raw) > 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode("utf-16-le")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def parse_export(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    first_line = text.split("\n", 1)[0]
    delimiter = max(";\t,", key=first_line.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return []
    fields = [HEADERS.get(normalise(h), normalise(h)) for h in rows[0]]
    out = []
    for r in rows[1:]:
        out.append({fields[i]: (r[i].strip() if i < len(r) else "") for i in range(len(fields))})
    return out


def _date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:19] if "%H" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _datetime(s: str) -> datetime | None:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    d = _date(s)
    return datetime(d.year, d.month, d.day, tzinfo=UTC) if d else None


def classify(nature: str, details: str, instrument_type: str) -> TradeType:
    base = NATURE.get(normalise(nature))
    blob = f"{details} {instrument_type}"
    if base is TradeType.BUY and EXERCISE_WORDS.search(blob):
        return TradeType.OPTION_EXERCISE
    if base is TradeType.BUY and ALLOTMENT_WORDS.search(blob):
        return TradeType.ALLOTMENT
    if base is None:
        return TradeType.OTHER if nature.strip() else TradeType.UNKNOWN
    return base


def row_to_trade(row: dict) -> Trade | None:
    published = _datetime(row.get("published", ""))
    issuer = row.get("issuer", "").strip()
    if not published or not issuer:
        return None
    quantity = parse_number(row.get("volume", ""))
    price = parse_number(row.get("price", ""))
    close = normalise(row.get("close", "")) in YES_WORDS
    key = "|".join(
        row.get(k, "") for k in (
            "published", "issuer", "lei", "pdmr", "notifier", "position", "close",
            "transaction_date", "instrument", "instrument_type", "isin", "nature",
            "volume", "unit", "price", "currency", "venue", "status", "details",
        )
    )
    source_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    pdmr = row.get("pdmr", "").strip() or None
    notifier = row.get("notifier", "").strip() or None
    return Trade(
        market=Market.SWEDEN,
        source_id=source_id,
        published_at=published,
        transaction_date=_date(row.get("transaction_date", "")),
        issuer=issuer,
        isin=row.get("isin", "").strip() or None,
        insider_name=pdmr or notifier,
        position=row.get("position", "").strip() or None,
        close_associate=close or (bool(notifier) and bool(pdmr) and notifier != pdmr),
        trade_type=classify(row.get("nature", ""), row.get("details", ""), row.get("instrument_type", "")),
        instrument=row.get("instrument", "").strip() or row.get("instrument_type", "").strip() or None,
        quantity=quantity,
        price=price,
        currency=row.get("currency", "").strip().upper() or ("SEK" if price is not None else None),
        venue=row.get("venue", "").strip() or None,
        status=row.get("status", "").strip() or None,
        title=f"{row.get('nature', '').strip()} {row.get('instrument', '').strip()}".strip() or None,
        raw_text=row.get("details", "").strip() or None,
        source_url=PUBLIC_URL.format(issuer=quote_plus(issuer)),
        parse_confidence=1.0,
    )


class FinansinspektionenSource:
    market = Market.SWEDEN

    def __init__(self, client: httpx.Client):
        self.client = client

    def download(self, since: date, until: date | None = None) -> str:
        params = {
            "SearchFunctionType": "Insyn",
            "Utgivare": "",
            "PersonILedandeStällningNamn": "",
            "Transaktionsdatum.From": "",
            "Transaktionsdatum.To": "",
            "Publiceringsdatum.From": since.strftime("%Y-%m-%d"),
            "Publiceringsdatum.To": until.strftime("%Y-%m-%d") if until else "",
            "button": "export",
            "Page": "1",
        }
        r = self.client.get(EXPORT_URL, params=params, headers={"accept": "text/csv,*/*"})
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "html" in ctype and b"<html" in r.content[:500].lower():
            raise RuntimeError(
                "Finansinspektionen returned an HTML page instead of the CSV export; "
                "the site may be rate limiting or the export URL has changed"
            )
        return decode_export(r.content)

    def fetch_rows(self, since: date, until: date) -> list[dict]:
        """Rows published in [since, until]. Windows that hit the export cap are split."""
        rows = parse_export(self.download(since, until))
        if len(rows) < EXPORT_CAP or since == until:
            if len(rows) >= EXPORT_CAP:
                log.warning("finansinspektionen: %s alone hits the export cap; some rows may be missing", since)
            return rows
        mid = since + (until - since) / 2
        log.info("finansinspektionen: %s..%s hit the export cap, splitting", since, until)
        return self.fetch_rows(since, mid) + self.fetch_rows(mid + timedelta(days=1), until)

    def fetch(self, since: date, until: date | None = None) -> list[Trade]:
        until = until or datetime.now(UTC).date()
        rows: list[dict] = []
        start = since
        while start <= until:
            end = min(start + timedelta(days=WINDOW_DAYS - 1), until)
            rows.extend(self.fetch_rows(start, end))
            start = end + timedelta(days=1)
        log.info("finansinspektionen: %d rows since %s", len(rows), since)
        natures = Counter(r.get("nature", "") for r in rows)
        unmapped = {k: v for k, v in natures.items() if normalise(k) not in NATURE}
        log.info("finansinspektionen: nature values %s", dict(natures.most_common(12)))
        if unmapped:
            log.warning("finansinspektionen: unmapped nature values (classified as other): %s", unmapped)
        seen: set[str] = set()
        trades: list[Trade] = []
        for t in (row_to_trade(r) for r in rows):
            if t and t.source_id not in seen:
                seen.add(t.source_id)
                trades.append(t)
        return trades
