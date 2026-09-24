"""Extract structured trade data from Oslo Børs insider announcements.

Announcements are free text in English or Norwegian, so this is heuristic. Every
result carries a confidence score and the caller keeps the original text so a
reader can always check the parse against the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..models import TradeType
from .numbers import find_date, parse_number

# --- vocabulary --------------------------------------------------------------

BUY_VERBS = re.compile(
    r"\b(acquired|acquires|acquisition of|purchased|purchases|purchase of|bought|buys|"
    r"subscribed for|subscription of|kjøpt|kjøper|kjøp av|ervervet|erverv av|tegnet)\b",
    re.I,
)
SELL_VERBS = re.compile(
    r"\b(sold|sells|sale of|disposed of|disposal of|divested|solgt|selger|salg av|avhendet)\b",
    re.I,
)
EXERCISE = re.compile(r"\b(exercis\w*|utøv\w*|innløs\w*)\b", re.I)
ALLOTMENT = re.compile(
    r"\b(allocat\w*|allott\w*|allotment|vest\w*|granted|grant of|tildel\w*|share saving|"
    r"aksjespare\w*|incentive|bonus shares|matching shares)\b",
    re.I,
)
OTHER = re.compile(
    r"\b(share lending|share loan|lend\w*|re-?deliver\w*|transferr?\w*|gift|overf\w*|utlån|"
    r"pledge\w*|pantsett\w*)\b",
    re.I,
)
CLOSE_ASSOCIATE = re.compile(
    r"close(?:ly)? associat\w*|nærstående|wholly[- ]owned|controlled by|owned by|"
    r"a company (?:owned|controlled)",
    re.I,
)

POSITIONS: list[tuple[str, str]] = [
    (r"chief executive officer|\bceo\b|administrerende direktør|adm\.? ?dir\.?|daglig leder|konsernsjef", "CEO"),
    (r"chief financial officer|\bcfo\b|finansdirektør|økonomidirektør", "CFO"),
    (r"chief operating officer|\bcoo\b|driftsdirektør", "COO"),
    (r"chief technology officer|\bcto\b|teknologidirektør", "CTO"),
    (r"deputy chair(?:man|person|woman)?|nestleder", "Deputy Chairman"),
    (r"chair(?:man|person|woman)? of the board|chair(?:man|person|woman)?\b|styreleder|styrets leder", "Chairman"),
    (r"(?:member|director) of the board|board member|non-executive director|styremedlem|"
     r"varamedlem|deputy board member", "Board Member"),
    (r"executive vice president|\bevp\b|senior vice president|\bsvp\b|vice president|\bvp\b|"
     r"konserndirektør|direktør", "Executive"),
    (r"primary insider|primærinnsider", "Primary Insider"),
]
POSITION_ALTERNATION = "|".join(p for p, _ in POSITIONS)

NAME = (
    r"(?P<name>[A-ZÆØÅÄÖÉ][\w'’\-æøåäöé]+"
    r"(?:\s+(?:van|von|de|der|den|af|av|le|du)\s+|\s+)"
    r"(?:[A-ZÆØÅÄÖÉ][\w'’\-æøåäöé]+(?:\s+|$)){0,2}[A-ZÆØÅÄÖÉ][\w'’\-æøåäöé]+)"
)
COMPANY_SUFFIX = re.compile(
    r"\b(AS|ASA|AB|A/S|Ltd|LLC|Inc|Holding|Holdings|Invest|Capital|Group|Partners|"
    r"Sparebank|Bank|Fund|Eiendom|Kapital)\b",
    re.I,
)
NAME_STOPWORDS = re.compile(
    r"^(Following|After|Etter|Please|This|The|Board|Primary|Close|Mandatory|Notification|"
    r"For|Oslo|Nasdaq|Euronext|Chairman|Member|Total|Share|Shares|Options|Reference|"
    r"Notice|Disclosure|Section|Subject)\b",
)

POS = f"(?i:{POSITION_ALTERNATION})"
NAME_PATTERNS = [
    # "..., a company wholly owned by the CEO, Ole Jakob Kjølvik, has ..."
    re.compile(rf"(?i:(?:owned|controlled) by (?:the )?){POS},?\s+{NAME}"),
    # "Jostein Sørvoll, board member, purchased ..."
    re.compile(rf"{NAME},\s+(?i:(?:the\s+|a\s+)?){POS}\b"),
    # "CEO of Foo ASA, John Doe, has ..."
    re.compile(rf"{POS}\s+(?i:of|in|i)\s+[^,.\n]{{2,60}},\s+{NAME}"),
    # "Styremedlem Ola Nordmann har ..." / "board member John Doe has ..."
    re.compile(rf"{POS}\s+{NAME},?\s+(?i:has|have|har|purchased|acquired|sold|kjøpte|solgte)"),
    # "primary insider John Doe" / "close associate Jane Roe"
    re.compile(rf"(?i:primary insider|primærinnsider|close associate|nærstående)\s+(?i:of\s+)?{NAME}"),
    # "John Doe, primary insider" / "John Doe (primary insider)"
    re.compile(rf"{NAME},?\s+\(?(?i:(?:a\s+)?(?:primary insider|primærinnsider))"),
    # "... owned by John Doe" / "controlled by John Doe"
    re.compile(rf"(?i:owned|controlled)\s+(?i:by)\s+{NAME}"),
    # "John Doe has today ..." / "John Doe har i dag ..."
    re.compile(rf"{NAME}\s+(?i:has|have)\s+(?i:today|on\b)"),
    re.compile(rf"{NAME}\s+har\s+(?i:i dag|den\b)"),
]

CURRENCY = r"(?P<cur>NOK|SEK|DKK|EUR|USD|GBP|CHF|kroner|kr)"
NUM = r"(?P<num>\d(?:[\d\s .,]*\d)?)"
MONEY_PATTERNS = [
    re.compile(rf"\b{CURRENCY}\.?\s*{NUM}", re.I),
    re.compile(rf"\b{NUM}\s*{CURRENCY}\b", re.I),
]
PRICE_CONTEXT_BEFORE = re.compile(
    r"(price|pris|kurs|\bat\b|\btil\b|\bà\b|per share|per aksje|strike)\W*$", re.I
)
PRICE_CONTEXT_AFTER = re.compile(r"^\W*(per share|per aksje|pr\.? aksje|each|per unit|per option)", re.I)
VALUE_CONTEXT = re.compile(
    r"(total|totalt|value|verdi|consideration|vederlag|amount|beløp|proceeds|sum)\W*$", re.I
)
QUANTITY = re.compile(
    r"(?P<num>\d(?:[\d\s .,]*\d)?)\s*(?:ordinary\s+|common\s+|new\s+|treasury\s+|egne\s+)?"
    r"(?P<unit>shares?|aksjer|aksje|units?|andeler|options?|opsjoner|warrants?|rights?|tegningsretter)\b",
    re.I,
)
HOLDING_CONTEXT = re.compile(
    r"(holds?|owns?|eier|innehar|total holding|holding of|beholdning|now holds|following)\W*"
    r"(?:a total of\s+|totalt\s+)?$",
    re.I,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÆØÅ(])|\n{2,}")
TODAY = re.compile(r"\b(today|i dag|idag)\b", re.I)


@dataclass
class ParsedTrade:
    trade_type: TradeType = TradeType.UNKNOWN
    quantity: float | None = None
    price: float | None = None
    currency: str | None = None
    value: float | None = None
    insider_name: str | None = None
    position: str | None = None
    close_associate: bool = False
    transaction_date: date | None = None
    instrument: str | None = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


# --- helpers -----------------------------------------------------------------


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]


def _clean(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t ]+", " ", text)
    return text.strip()


def _first_match_pos(pattern: re.Pattern, text: str) -> int | None:
    m = pattern.search(text)
    return m.start() if m else None


def _valid_name(name: str, issuer: str) -> bool:
    if COMPANY_SUFFIX.search(name) or NAME_STOPWORDS.search(name):
        return False
    if len(name.split()) < 2 or len(name) > 60:
        return False
    return not (issuer and name.lower() in issuer.lower())


def _position(text: str) -> str | None:
    best: tuple[int, str] | None = None
    generic: str | None = None
    for pattern, label in POSITIONS:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        if label == "Primary Insider":
            generic = label
        elif best is None or m.start() < best[0]:
            best = (m.start(), label)
    return best[1] if best else generic


def _find_name(text: str, issuer: str) -> str | None:
    for pat in NAME_PATTERNS:
        for m in pat.finditer(text):
            name = re.sub(r"\s+", " ", m.group("name")).strip(" ,")
            if _valid_name(name, issuer):
                return name
    return None


def _classify(title: str, body: str) -> tuple[TradeType, str | None]:
    """Return (trade type, the sentence the decision was based on)."""
    text = body or title
    buy_pos = _first_match_pos(BUY_VERBS, text)
    sell_pos = _first_match_pos(SELL_VERBS, text)
    if buy_pos is not None or sell_pos is not None:
        pos = min(p for p in (buy_pos, sell_pos) if p is not None)
        kind = TradeType.BUY if pos == buy_pos else TradeType.SELL
        sentence = next((s for s in _sentences(text) if text.find(s) <= pos < text.find(s) + len(s)), text)
        if kind is TradeType.BUY and EXERCISE.search(sentence):
            return TradeType.OPTION_EXERCISE, sentence
        if kind is TradeType.BUY and ALLOTMENT.search(sentence) and not re.search(
            r"purchase|bought|kjøp", sentence, re.I
        ):
            return TradeType.ALLOTMENT, sentence
        return kind, sentence
    if EXERCISE.search(text):
        return TradeType.OPTION_EXERCISE, None
    if ALLOTMENT.search(text):
        return TradeType.ALLOTMENT, None
    if OTHER.search(text):
        return TradeType.OTHER, None
    # Fall back to the title when the body did not help.
    if body and text is body:
        return _classify(title, "")
    return TradeType.UNKNOWN, None


def _quantity(scope: str, fallback: str) -> tuple[float | None, str | None]:
    for text in (scope, fallback):
        for m in QUANTITY.finditer(text):
            before = text[max(0, m.start() - 40):m.start()]
            if HOLDING_CONTEXT.search(before):
                continue
            n = parse_number(m.group("num"))
            if n is not None and n >= 1:
                unit = m.group("unit").lower()
                instrument = "options" if unit.startswith("op") else (
                    "warrants" if unit.startswith("warr") else "shares"
                )
                return n, instrument
    return None, None


def _money(text: str) -> tuple[float | None, str | None, float | None]:
    """Return (price, currency, total value) by scoring every currency amount in the text."""
    candidates: list[tuple[int, int, float, str]] = []
    for pat in MONEY_PATTERNS:
        for m in pat.finditer(text):
            n = parse_number(m.group("num"))
            if n is None:
                continue
            cur = m.group("cur").upper()
            cur = "NOK" if cur in ("KR", "KRONER") else cur
            before = text[max(0, m.start() - 30):m.start()]
            after = text[m.end():m.end() + 25]
            score = 0
            if PRICE_CONTEXT_BEFORE.search(before):
                score += 2
            if PRICE_CONTEXT_AFTER.search(after):
                score += 3
            if VALUE_CONTEXT.search(before):
                score -= 4
            candidates.append((score, m.start(), n, cur))
    if not candidates:
        return None, None, None
    candidates.sort(key=lambda c: (-c[0], c[1]))
    price = currency = value = None
    best = candidates[0]
    if best[0] > 0:
        price, currency = best[2], best[3]
    values = [c for c in candidates if c[0] < 0]
    if values:
        value = values[0][2]
        currency = currency or values[0][3]
    if price is None and len(candidates) == 1 and best[2] < 100_000:
        # A single bare amount is far more likely a price than a total.
        price, currency = best[2], best[3]
    return price, currency, value


# --- entry point -------------------------------------------------------------


def parse_announcement(title: str, body: str, issuer: str = "", published: date | None = None) -> ParsedTrade:
    title = _clean(title or "")
    body = _clean(body or "")
    result = ParsedTrade()

    result.trade_type, sentence = _classify(title, body)
    text = body or title
    scope = sentence or text

    result.quantity, result.instrument = _quantity(scope, text)
    result.price, result.currency, result.value = _money(scope)
    if result.price is None and scope is not text:
        p, c, v = _money(text)
        result.price, result.currency = p, c or result.currency
        result.value = result.value if result.value is not None else v

    result.close_associate = bool(CLOSE_ASSOCIATE.search(text)) or bool(
        re.search(r"close associate|nærstående", title, re.I)
    )
    result.insider_name = _find_name(text, issuer)
    result.position = _position(text) or _position(title)
    if result.position == "Primary Insider" and result.close_associate:
        result.position = None  # the close associate flag already says it

    result.transaction_date = find_date(scope) or find_date(text)
    if result.transaction_date is None and published and TODAY.search(scope):
        result.transaction_date = published
    if result.transaction_date is None and published:
        result.transaction_date = published
        result.notes.append("transaction date assumed equal to publication date")

    if result.value is None and result.quantity and result.price:
        result.value = round(result.quantity * result.price, 2)

    confidence = 1.0
    if not body:
        confidence -= 0.4
        result.notes.append("no body text; parsed from title only")
    if result.trade_type is TradeType.UNKNOWN:
        confidence -= 0.3
    if result.quantity is None:
        confidence -= 0.15
    if result.price is None:
        confidence -= 0.15
    if result.insider_name is None:
        confidence -= 0.1
    result.confidence = round(max(0.0, confidence), 2)
    return result
