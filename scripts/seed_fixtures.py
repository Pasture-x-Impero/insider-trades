#!/usr/bin/env python3
"""Load the recorded test fixtures into a database so the UI can be tried offline.

Usage: INSIDER_DB=demo.db python scripts/seed_fixtures.py
Then:  INSIDER_SYNC_ON_STARTUP=0 INSIDER_DB=demo.db insider-trades serve
"""

import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from insider_trades.config import Settings  # noqa: E402
from insider_trades.store import Store  # noqa: E402
from insider_trades.sync import sync_all  # noqa: E402
from tests.conftest import fake_handler  # noqa: E402

settings = Settings.from_env()
store = Store(settings.db_path)
with httpx.Client(transport=httpx.MockTransport(fake_handler)) as client:
    results = sync_all(store, settings, since=date(2025, 9, 1), client=client)
for market, r in results.items():
    print(f"{market.value}: {r}")
print(f"seeded {settings.db_path}")
