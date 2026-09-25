#!/usr/bin/env python3
"""Print raw Finansinspektionen export rows to diagnose parsing. Used from CI only."""

import csv
import io
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from insider_trades.parsers.numbers import parse_number  # noqa: E402
from insider_trades.sources.finansinspektionen import (  # noqa: E402
    FinansinspektionenSource,
    parse_export,
)

since = date(2026, 8, 10)
with httpx.Client(timeout=60, follow_redirects=True, headers={"user-agent": "insider-trades-debug"}) as c:
    text = FinansinspektionenSource(c).download(since, date(2026, 8, 16))
for line in text.splitlines():
    if "swedbank" in line.lower():
        print("RAW SWED:", line)

lines = text.splitlines()
print("RAW HEADER:", lines[0])
for line in lines[1:4]:
    print("RAW ROW:", line)
reader = csv.reader(io.StringIO(text), delimiter=";")
header = next(reader)
print("HEADER COUNT", len(header))
lens = Counter(len(r) for r in reader)
print("ROW FIELD COUNTS", dict(lens))

rows = parse_export(text)
print("PARSED KEYS", list(rows[0].keys()))
print("UNIT", Counter(r.get("unit", "") for r in rows).most_common(10))
print("INSTRUMENT TYPE", Counter(r.get("instrument_type", "") for r in rows).most_common(15))
same = [r for r in rows if r.get("price") and r.get("price") == r.get("volume")]
print("PRICE == VOLUME", len(same), "of", len(rows))
for r in same[:15]:
    print("  SAME", {k: r.get(k) for k in ("issuer", "instrument_type", "instrument", "volume", "unit", "price", "currency", "nature")})
big = sorted(rows, key=lambda r: -((parse_number(r.get("volume", "")) or 0) * (parse_number(r.get("price", "")) or 0)))
for r in big[:25]:
    print("  BIG", {k: r.get(k) for k in ("issuer", "instrument_type", "instrument", "volume", "unit", "price", "currency", "nature")})
for r in rows:
    if "swedbank" in r.get("issuer", "").lower():
        print("  SWED", r)
