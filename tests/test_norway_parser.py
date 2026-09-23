import json
from datetime import date
from pathlib import Path

import pytest

from insider_trades.models import TradeType
from insider_trades.parsers.norway import parse_announcement

FIXTURES = Path(__file__).parent / "fixtures"


def test_real_arribatec_message():
    msg = json.loads((FIXTURES / "oslo_detail_654802.json").read_text())["data"]["message"]
    p = parse_announcement(msg["title"], msg["body"], msg["issuerName"], date(2025, 9, 5))
    assert p.trade_type is TradeType.BUY
    assert p.quantity == 85226
    assert p.price == 0.64
    assert p.currency == "NOK"
    assert p.value == pytest.approx(85226 * 0.64)
    assert p.insider_name == "Ole Jakob Kjølvik"
    assert p.position == "CEO"
    assert p.close_associate is True
    assert p.transaction_date == date(2025, 9, 5)
    assert p.confidence == 1.0


def test_english_board_member_purchase():
    body = (
        "On 5 September 2025, Jostein Sørvoll, board member of Protector Forsikring ASA, "
        "purchased 1,000 shares in Protector Forsikring ASA at NOK 380.00 per share. "
        "Following the transaction, Sørvoll holds 25,000 shares in the company."
    )
    p = parse_announcement("Mandatory notification of trade", body, "Protector Forsikring ASA")
    assert p.trade_type is TradeType.BUY
    assert p.quantity == 1000
    assert p.price == 380.0
    assert p.insider_name == "Jostein Sørvoll"
    assert p.position == "Board Member"
    assert p.close_associate is False
    assert p.transaction_date == date(2025, 9, 5)


def test_norwegian_sale():
    body = (
        "Styremedlem Ola Nordmann har den 4. september 2025 solgt 5 000 aksjer i Kraft Bank ASA "
        "til kurs NOK 9,50 per aksje. Etter transaksjonen eier Nordmann 20 000 aksjer."
    )
    p = parse_announcement("Meldepliktig handel", body, "Kraft Bank ASA")
    assert p.trade_type is TradeType.SELL
    assert p.quantity == 5000
    assert p.price == 9.5
    assert p.insider_name == "Ola Nordmann"
    assert p.position == "Board Member"
    assert p.transaction_date == date(2025, 9, 4)


def test_average_price_and_total_value():
    body = (
        "Primary insider Kari Hansen, CFO, has today sold 10 000 shares at an average price of "
        "NOK 12.50 per share, for a total consideration of NOK 125 000. "
        "After the sale Hansen holds 40 000 shares."
    )
    p = parse_announcement("Mandatory notification of trade", body, "Foo ASA", date(2025, 9, 3))
    assert p.trade_type is TradeType.SELL
    assert p.quantity == 10000
    assert p.price == 12.5
    assert p.value == 125000
    assert p.insider_name == "Kari Hansen"
    assert p.position == "CFO"
    assert p.transaction_date == date(2025, 9, 3)


def test_option_exercise_then_sale_is_a_sale():
    body = (
        "John Doe, CEO of Zalaris ASA, has today exercised 50 000 share options at a strike price "
        "of NOK 30.00. He subsequently sold 25 000 shares at NOK 62.10 per share to cover tax."
    )
    p = parse_announcement("Exercise of employee share options", body, "Zalaris ASA")
    # The exercise sentence comes first and mentions no buy or sell verb; the sale is what hits the market.
    assert p.trade_type is TradeType.SELL
    assert p.quantity == 25000
    assert p.price == 62.10
    assert p.insider_name == "John Doe"
    assert p.position == "CEO"


def test_pure_option_exercise():
    body = (
        "Anne Berg, EVP Operations, has acquired 20 000 shares by exercising options at an exercise "
        "price of NOK 5.00 per share."
    )
    p = parse_announcement("Mandatory notification of trade", body, "AKVA group ASA")
    assert p.trade_type is TradeType.OPTION_EXERCISE
    assert p.quantity == 20000
    assert p.price == 5.0
    assert p.insider_name == "Anne Berg"


def test_share_saving_plan_allotment():
    body = (
        "Vår Energi ASA's share saving plan has allocated shares to employees. Primary insiders "
        "were allocated a total of 1 234 shares at a price of NOK 33.50 per share."
    )
    p = parse_announcement("Vår Energi ASA's share saving plan allocates shares", body, "Vår Energi ASA")
    assert p.trade_type is TradeType.ALLOTMENT
    assert p.price == 33.5


def test_empty_body_uses_title_and_lowers_confidence():
    p = parse_announcement("Primary insider notification - purchase of shares", "", "CodeLab Capital AS")
    assert p.trade_type is TradeType.BUY
    assert p.quantity is None
    assert p.confidence < 0.6
    assert any("title" in n for n in p.notes)


def test_close_associate_via_company():
    body = (
        "Reiten & Co AS, a company controlled by chairman Narve Reiten, has on 2 September 2025 "
        "acquired 100 000 shares in Vow ASA at NOK 1.05 per share."
    )
    p = parse_announcement("Notification of trade by close associate of primary insider", body, "Vow ASA")
    assert p.trade_type is TradeType.BUY
    assert p.close_associate is True
    assert p.insider_name == "Narve Reiten"
    assert p.position == "Chairman"
    assert p.quantity == 100000
    assert p.price == 1.05


def test_share_lending_is_other():
    body = "The shares lent under the share lending agreement have today been re-delivered to the lender."
    p = parse_announcement("Mandatory notification of trade - Share lending re-delivery", body, "Saga Pure ASA")
    assert p.trade_type is TradeType.OTHER


def test_holding_number_is_not_mistaken_for_quantity():
    body = (
        "Following the transaction, Kjølvik Invest AS holds a total of 556 342 shares. "
        "The company acquired 85 226 shares today at NOK 0.64."
    )
    p = parse_announcement("Mandatory notification of trade", body, "Arribatec Group ASA")
    assert p.quantity == 85226
