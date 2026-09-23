"""Number and date parsing helpers for Nordic announcement text."""

from __future__ import annotations

import re
from datetime import date

_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")
_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")

MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    # Norwegian and Swedish
    "januar": 1, "februar": 2, "mars": 3, "mai": 5, "juni": 6, "juli": 7, "oktober": 10,
    "desember": 12, "januari": 1, "februari": 2, "maj": 5, "augusti": 8, "december_": 12,
}


def parse_number(text: str) -> float | None:
    """Parse '85 226', '1,000', '1.000.000', '9,50', '0.64', '12.345,67' into a float."""
    s = text.replace(" ", " ").replace(" ", " ").strip()
    s = re.sub(r"\s+", "", s)
    if not s or not re.fullmatch(r"[\d.,]+", s) or not s[0].isdigit():
        return None
    if "," in s and "." in s:
        # The last separator is the decimal one.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if _THOUSANDS_COMMA.match(s) else s.replace(",", ".")
    elif "." in s:
        if _THOUSANDS_DOT.match(s):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


_DATE_PATTERNS = [
    # 2025-09-04
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    # 04.09.2025 or 4/9/2025
    re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"),
    # 5 September 2025, 5. september 2025, 5th of September 2025
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\.?\s+(?:of\s+)?([A-Za-zæøåäö]+),?\s+(\d{4})\b"),
    # September 05, 2025
    re.compile(r"\b([A-Za-zæøåäö]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"),
]


def find_date(text: str) -> date | None:
    """Return the first recognisable calendar date in the text, if any."""
    best: tuple[int, date] | None = None
    for i, pat in enumerate(_DATE_PATTERNS):
        for m in pat.finditer(text):
            try:
                if i == 0:
                    d = date(int(m[1]), int(m[2]), int(m[3]))
                elif i == 1:
                    d = date(int(m[3]), int(m[2]), int(m[1]))
                elif i == 2:
                    month = MONTHS.get(m[2].lower())
                    if not month:
                        continue
                    d = date(int(m[3]), month, int(m[1]))
                else:
                    month = MONTHS.get(m[1].lower())
                    if not month:
                        continue
                    d = date(int(m[3]), month, int(m[2]))
            except ValueError:
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), d)
            break
    return best[1] if best else None
