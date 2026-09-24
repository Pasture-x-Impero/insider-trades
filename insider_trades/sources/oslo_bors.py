"""Oslo Børs NewsWeb: category 1102 is "mandatory notification of trade, primary insiders".

The newsreader API returns a list of announcements; each has to be fetched
separately to get the body text. Bodies are free text and go through
:mod:`insider_trades.parsers.norway`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from ..models import Market, Trade
from ..parsers.norway import parse_announcement

log = logging.getLogger(__name__)

LIST_URL = "https://api3.oslo.oslobors.no/v1/newsreader/list"
DETAIL_URL = "https://api3.oslo.oslobors.no/v1/newsreader/message"
PUBLIC_URL = "https://newsweb.oslobors.no/message/{id}"
CATEGORY_PRIMARY_INSIDERS = 1102


class OsloBorsSource:
    market = Market.NORWAY

    def __init__(self, client: httpx.Client, max_detail_fetch: int = 200):
        self.client = client
        self.max_detail_fetch = max_detail_fetch

    def list_messages(self, since: date) -> list[dict]:
        r = self.client.post(
            LIST_URL,
            params={"category": CATEGORY_PRIMARY_INSIDERS, "fromDate": since.isoformat()},
            headers={"accept": "*/*", "content-type": "application/json"},
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("messages", []) or []

    def get_message(self, message_id: int) -> dict:
        r = self.client.post(
            DETAIL_URL,
            params={"messageId": message_id},
            headers={"accept": "*/*", "content-type": "application/json"},
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("message", {}) or {}

    def fetch(self, since: date) -> list[Trade]:
        messages = [m for m in self.list_messages(since) if not m.get("test")]
        log.info("oslo børs: %d announcements since %s", len(messages), since)
        if len(messages) > self.max_detail_fetch:
            log.warning(
                "oslo børs: only the first %d of %d announcements get their body text; "
                "raise INSIDER_MAX_DETAIL_FETCH to parse the rest",
                self.max_detail_fetch, len(messages),
            )
        trades: list[Trade] = []
        for i, msg in enumerate(messages):
            detail: dict = {}
            if i < self.max_detail_fetch:
                try:
                    detail = self.get_message(int(msg["messageId"]))
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    log.warning("oslo børs: detail fetch failed for %s: %s", msg.get("messageId"), exc)
            trades.append(self.to_trade({**msg, **detail}))
        return trades

    @staticmethod
    def to_trade(msg: dict) -> Trade:
        published = datetime.fromisoformat(msg["publishedTime"].replace("Z", "+00:00"))
        title = msg.get("title", "") or ""
        body = msg.get("body", "") or ""
        issuer = msg.get("issuerName", "") or ""
        parsed = parse_announcement(title, body, issuer, published.date())
        attachments = msg.get("attachments") or []
        if not body and (attachments or msg.get("numbAttachments")):
            parsed.notes.append("details are in an attachment; see the source link")
        status = "superseded" if msg.get("correctedByMessageId") else "current"
        if msg.get("correctionForMessageId"):
            status = "correction"
        return Trade(
            market=Market.NORWAY,
            source_id=str(msg["messageId"]),
            published_at=published,
            transaction_date=parsed.transaction_date,
            issuer=issuer,
            ticker=(msg.get("issuerSign") or None),
            insider_name=parsed.insider_name,
            position=parsed.position,
            close_associate=parsed.close_associate,
            trade_type=parsed.trade_type,
            instrument=parsed.instrument,
            quantity=parsed.quantity,
            price=parsed.price,
            currency=parsed.currency or ("NOK" if parsed.price is not None else None),
            value=parsed.value,
            venue=", ".join(msg.get("markets") or []) or None,
            status=status,
            title=title,
            raw_text=body or None,
            source_url=PUBLIC_URL.format(id=msg["messageId"]),
            parse_confidence=parsed.confidence,
        )
