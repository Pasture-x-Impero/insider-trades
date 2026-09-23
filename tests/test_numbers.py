from datetime import date

from insider_trades.parsers.numbers import find_date, parse_number


def test_parse_number_variants():
    assert parse_number("85 226") == 85226
    assert parse_number("1,000") == 1000
    assert parse_number("1.000.000") == 1_000_000
    assert parse_number("9,50") == 9.5
    assert parse_number("0.64") == 0.64
    assert parse_number("12.345,67") == 12345.67
    assert parse_number("12,345.67") == 12345.67
    assert parse_number("1 234 567") == 1234567
    assert parse_number("380.00") == 380.0
    assert parse_number("abc") is None


def test_find_date_variants():
    assert find_date("has today (September 05, 2025) acquired") == date(2025, 9, 5)
    assert find_date("On 5 September 2025, X purchased") == date(2025, 9, 5)
    assert find_date("har den 4. september 2025 kjøpt") == date(2025, 9, 4)
    assert find_date("Trade date: 04.09.2025") == date(2025, 9, 4)
    assert find_date("Trade date: 2025-09-04") == date(2025, 9, 4)
    assert find_date("on 1st of September 2025") == date(2025, 9, 1)
    assert find_date("no date here") is None
