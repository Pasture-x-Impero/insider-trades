"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    sync_on_startup: bool
    sync_interval_minutes: int
    initial_lookback_days: int
    http_timeout: float
    max_detail_fetch: int
    user_agent: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(os.environ.get("INSIDER_DB", "insider_trades.db")),
            sync_on_startup=os.environ.get("INSIDER_SYNC_ON_STARTUP", "1") not in ("0", "false"),
            sync_interval_minutes=int(os.environ.get("INSIDER_SYNC_INTERVAL_MINUTES", "30")),
            initial_lookback_days=int(os.environ.get("INSIDER_LOOKBACK_DAYS", "60")),
            http_timeout=float(os.environ.get("INSIDER_HTTP_TIMEOUT", "20")),
            max_detail_fetch=int(os.environ.get("INSIDER_MAX_DETAIL_FETCH", "1000")),
            user_agent=os.environ.get(
                "INSIDER_USER_AGENT",
                "insider-trades/0.1 (+https://github.com/pasture-x-impero/insider-trades)",
            ),
        )
