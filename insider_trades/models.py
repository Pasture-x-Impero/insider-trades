"""Shared data model. Every source normalises into a :class:`Trade`."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Market(StrEnum):
    NORWAY = "NO"
    SWEDEN = "SE"


class TradeType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    OPTION_EXERCISE = "option_exercise"
    ALLOTMENT = "allotment"  # share programmes, vesting, grants
    OTHER = "other"
    UNKNOWN = "unknown"


class Trade(BaseModel):
    """One insider transaction, or one announcement when the source is free text."""

    market: Market
    source_id: str = Field(description="Stable id within the source, used for upserts")
    published_at: datetime
    transaction_date: date | None = None
    issuer: str
    ticker: str | None = None
    isin: str | None = None
    insider_name: str | None = None
    position: str | None = None
    close_associate: bool = False
    trade_type: TradeType = TradeType.UNKNOWN
    instrument: str | None = None
    quantity: float | None = None
    price: float | None = None
    currency: str | None = None
    value: float | None = None
    venue: str | None = None
    status: str | None = None
    title: str | None = None
    raw_text: str | None = None
    source_url: str | None = None
    parse_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _derive_value(self) -> "Trade":
        if self.value is None and self.quantity is not None and self.price is not None:
            self.value = round(self.quantity * self.price, 2)
        return self


class StoredTrade(Trade):
    id: int
    fetched_at: datetime
