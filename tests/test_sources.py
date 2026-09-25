from datetime import date

from insider_trades.models import Market, TradeType
from insider_trades.sources.finansinspektionen import (
    FinansinspektionenSource,
    decode_export,
    parse_export,
)
from insider_trades.sources.oslo_bors import OsloBorsSource


def test_oslo_fetch_uses_recorded_fixture(client):
    trades = OsloBorsSource(client).fetch(date(2025, 9, 1))
    assert len(trades) == 35
    by_id = {t.source_id: t for t in trades}
    arr = by_id["654802"]
    assert arr.market is Market.NORWAY
    assert arr.issuer == "Arribatec Group ASA"
    assert arr.ticker == "ARR"
    assert arr.trade_type is TradeType.BUY
    assert arr.quantity == 85226 and arr.price == 0.64 and arr.currency == "NOK"
    assert arr.insider_name == "Ole Jakob Kjølvik"
    assert arr.source_url == "https://newsweb.oslobors.no/message/654802"
    assert arr.published_at.isoformat().startswith("2025-09-05T12:45:11")
    assert arr.status == "current"
    # Everything else had no body in the fixture, so it is title only with reduced confidence.
    others = [t for t in trades if t.source_id != "654802"]
    assert all(t.parse_confidence < 0.7 for t in others)
    assert all(t.raw_text is None for t in others)


def test_oslo_title_only_classification(client):
    trades = {t.source_id: t for t in OsloBorsSource(client).fetch(date(2025, 9, 1))}
    titles = {t.title: t.trade_type for t in trades.values()}
    assert titles["Primary insider notification - purchase of shares"] is TradeType.BUY
    assert titles["Exercise of employee share options under share incentive program"] is TradeType.OPTION_EXERCISE
    assert titles["Vår Energi ASA's share saving plan allocates shares"] is TradeType.ALLOTMENT
    assert titles["Saga Pure ASA - Mandatory notification of trade - Share lending re-delivery"] is TradeType.OTHER


def test_oslo_respects_detail_fetch_limit(client):
    trades = OsloBorsSource(client, max_detail_fetch=0).fetch(date(2025, 9, 1))
    assert len(trades) == 35
    assert all(t.raw_text is None for t in trades)


def test_fi_decode_and_parse(client):
    src = FinansinspektionenSource(client)
    text = src.download(date(2025, 9, 1))
    assert text.startswith("Publication date;")
    rows = parse_export(text)
    assert len(rows) == 4
    assert rows[0]["issuer"] == "Volvo, AB"
    assert rows[0]["pdmr"] == "Martin Lundstedt"


def test_fi_trades(client):
    trades = FinansinspektionenSource(client).fetch(date(2025, 9, 1))
    assert len(trades) == 4
    volvo, investor, evo, sinch = trades
    assert volvo.market is Market.SWEDEN
    assert volvo.trade_type is TradeType.BUY
    assert volvo.quantity == 5000 and volvo.price == 281.5 and volvo.currency == "SEK"
    assert volvo.value == 5000 * 281.5
    assert volvo.isin == "SE0000115446"
    assert volvo.transaction_date == date(2025, 9, 4)
    assert volvo.published_at.isoformat().startswith("2025-09-05T17:32:11")
    assert volvo.close_associate is False
    assert investor.trade_type is TradeType.SELL
    assert investor.close_associate is True
    assert investor.insider_name == "Johan Forssell"
    assert evo.trade_type is TradeType.OPTION_EXERCISE
    assert sinch.trade_type is TradeType.ALLOTMENT
    assert sinch.price is None and sinch.status == "Revised"
    assert len({t.source_id for t in trades}) == 4


def test_fi_swedish_headers_and_utf8():
    text = (
        "Publiceringsdatum;Utgivare;Person i ledande ställning;Befattning;Närstående;Karaktär;"
        "Instrumentnamn;ISIN;Transaktionsdatum;Volym;Pris;Valuta;Status\n"
        "2025-09-05 10:00:00;Volvo, AB;Martin Lundstedt;VD;Nej;Förvärv;Volvo B;SE0000115446;"
        "2025-09-04;100;281,5;SEK;Aktuell\n"
    )
    rows = parse_export(decode_export(text.encode("utf-8")))
    assert rows[0]["nature"] == "Förvärv"
    from insider_trades.sources.finansinspektionen import row_to_trade
    t = row_to_trade(rows[0])
    assert t.trade_type is TradeType.BUY
    assert t.position == "VD"
    assert t.close_associate is False


def test_fi_fetch_splits_windows_that_hit_the_cap():
    """A window returning EXPORT_CAP rows is split until every piece is under the cap."""
    import httpx

    from insider_trades.sources import finansinspektionen as fi

    header = (
        "Publication date;Issuer;Person discharging managerial responsibilities;Nature of transaction;"
        "Instrument name;ISIN;Transaction date;Volume;Price;Currency;Status\n"
    )
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        frm = request.url.params["Publiceringsdatum.From"]
        to = request.url.params["Publiceringsdatum.To"]
        calls.append((frm, to))
        days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
        # Pretend the register has 300 rows per day, so anything over 3 days hits the cap.
        n = min(fi.EXPORT_CAP, 300 * days)
        rows = "".join(
            f"{frm} 10:00:00;Issuer {i};Person {i};Acquisition;Share;SE000{i:07d};{frm};1;1;SEK;Current\n"
            for i in range(n)
        )
        return httpx.Response(200, content=(header + rows).encode("utf-8"), headers={"content-type": "text/csv"})

    src = fi.FinansinspektionenSource(httpx.Client(transport=httpx.MockTransport(handler)))
    trades = src.fetch(date(2025, 9, 1), date(2025, 9, 14))
    assert calls[0] == ("2025-09-01", "2025-09-14")
    assert len(calls) > 1
    # Every leaf window is under the cap, so all 14 days x 300 rows come back.
    assert len(trades) == 14 * 300
    assert len({t.source_id for t in trades}) == len(trades)


def test_fi_nature_mapping_covers_live_values():
    """Every nature value seen in the live export maps to a type, none fall through to other by accident."""
    from insider_trades.sources.finansinspektionen import classify

    live = {
        "Acquisition": TradeType.BUY, "Disposal": TradeType.SELL, "Subscription": TradeType.BUY,
        "Allotment": TradeType.ALLOTMENT, "Exercise decrease": TradeType.OPTION_EXERCISE,
        "Exercise increase": TradeType.OPTION_EXERCISE, "Conversion increase": TradeType.OPTION_EXERCISE,
        "Internal transaction – Acquisition": TradeType.OTHER, "Internal transaction – Disposal": TradeType.OTHER,
        "Exchange increase": TradeType.OTHER, "Exchange decrease": TradeType.OTHER,
        "Return of loan increase": TradeType.OTHER, "Return of loan decrease": TradeType.OTHER,
        "Loan granted": TradeType.OTHER, "Loan received": TradeType.OTHER,
        "Gift received": TradeType.OTHER, "Gift given": TradeType.OTHER, "Inheritance received": TradeType.OTHER,
        "Demerger increase": TradeType.OTHER, "Issue of instrument": TradeType.OTHER,
        "Dividend distributed": TradeType.OTHER, "Dividend received": TradeType.OTHER,
        "Division of joint property between spouses decrease": TradeType.OTHER, "Pledging": TradeType.OTHER,
        # Swedish site wording
        "Förvärv": TradeType.BUY, "Avyttring": TradeType.SELL, "Teckning": TradeType.BUY,
        "Tilldelning": TradeType.ALLOTMENT, "Lösen ökning": TradeType.OPTION_EXERCISE,
        "Pantsättning": TradeType.OTHER,
    }
    for nature, expected in live.items():
        assert classify(nature, "", "") is expected, nature
    assert classify("Something new", "", "") is TradeType.OTHER
    assert classify("", "", "") is TradeType.UNKNOWN


REAL_EXPORT = (
    "Publication date;Issuer;LEI-code;Notifier;Person discharging managerial responsibilities;Position;"
    "Closely associated;Amendment;Details of amendment;Initial notification;Linked to share option programme;"
    "Nature of transaction;Intrument type;Instrument name;ISIN;Transaction date;Volume;Unit;Price;Currency;"
    "Trading venue;Status;\n"
    "09/08/2026 22:05:02;Gränges AB;5493006UG44TYSIXOB13;Fredrik Spens;Fredrik Spens;Other senior executive;"
    ";;;Yes;;Disposal;Share;Gränges AB;SE0006288015;06/08/2026 00:00:00;7179.0;Quantity;187.0;SEK;"
    "NASDAQ STOCKHOLM AB;Current;\n"
    "09/08/2026 16:16:02;Swedish Orphan Biovitrum AB (publ);X;A B;A B;CEO;;;;Yes;;Disposal;Share;"
    "Swedish Orphan Biovitrum AB;SE0000872095;06/08/2026 00:00:00;97515.0;Quantity;474.256;SEK;"
    "NASDAQ STOCKHOLM AB;Current;\n"
    "09/08/2026 12:00:00;K33 AB (publ);X;C D;C D;Board member;;;;Yes;;Return of loan increase;Share;"
    "K33 AB (publ);SE0000000001;06/08/2026 00:00:00;40000000.0;Quantity;0.026;SEK;;Current;\n"
)


def test_fi_real_export_numbers_use_dot_decimals():
    """The export writes '474.256' meaning 474.256 SEK, not 474 256."""
    from insider_trades.sources.finansinspektionen import export_number, row_to_trade

    assert export_number("474.256") == 474.256
    assert export_number("0.026") == 0.026
    assert export_number("7179.0") == 7179
    assert export_number("281,50") == 281.5
    assert export_number("") is None and export_number("n/a") is None

    rows = parse_export(REAL_EXPORT)
    assert rows[0]["instrument_type"] == "Share"  # the misspelled header is mapped
    trades = [row_to_trade(r) for r in rows]
    granges, sobi, k33 = trades
    assert granges.price == 187.0 and granges.quantity == 7179 and granges.value == 7179 * 187.0
    assert granges.published_at.isoformat().startswith("2026-08-09T22:05:02")
    assert granges.transaction_date == date(2026, 8, 6)
    assert sobi.price == 474.256 and round(sobi.value) == round(97515 * 474.256)
    assert k33.price == 0.026 and k33.trade_type is TradeType.OTHER


def test_fi_swap_with_nominal_in_price_is_other_without_value():
    """Swedbank: an interest rate swap reported with the nominal amount as both volume and price."""
    from insider_trades.sources.finansinspektionen import row_to_trade

    text = REAL_EXPORT.split("\n")[0] + "\n" + (
        "12/08/2026 13:38:12;Swedbank AB (publ);M312WZV08Y7LYUC71685;Sparbanken Skåne AB (publ);Rasmus Roos;"
        "Member of the Board of Directors;Yes;;;Yes;;Subscription;Swap;Ränteswapavtal;EZD17D1P8FN0;"
        "12/08/2026 00:00:00;18000000.0;Quantity;18000000.0;SEK;SWEDBANK - SYSTEMATIC INTERNALISER;Current;\n"
        "10/08/2026 10:20:43;K-Fast Holding AB;549300VT0UXKWES37P59;Niclas Bagler;Niclas Bagler;"
        "Deputy CEO/Deputy Managing Director;;;;Yes;;Acquisition;Share;K-Fast Holding AB B;SE0016101679;"
        "10/08/2026 00:00:00;4000.0;Quantity;11.5;SEK;SWEDBANK - SYSTEMATIC INTERNALISER;Current;\n"
        "15/08/2026 20:30:08;Prostatype Genomics AB;X;Anders Lundberg;Anders Lundberg;Member of the Board;"
        ";;;Yes;;Subscription;BTU;Prostatype Genomics BTU;SE0029529825;12/08/2026 00:00:00;643750.0;Quantity;"
        "0.80;SEK;FIRST NORTH SWEDEN - SME GROWTH MARKET;Current;\n"
        "01/08/2026 10:00:00;Tele2 AB;X;Kinnevik AB;Someone;Board member;Yes;;;Yes;;Acquisition;"
        "Other derivative;Total Return Swap;SE0000000002;01/08/2026 00:00:00;426919.0;Quantity;163.4646;SEK;;Current;\n"
    )
    swap, kfast, btu, trs = [row_to_trade(r) for r in parse_export(text)]
    assert swap.trade_type is TradeType.OTHER
    assert swap.price is None and swap.value is None and swap.quantity == 18_000_000
    assert swap.close_associate is True and swap.insider_name == "Rasmus Roos"
    assert swap.instrument == "Ränteswapavtal · Swap"
    assert kfast.trade_type is TradeType.BUY and kfast.value == 46000
    assert btu.trade_type is TradeType.BUY and btu.value == round(643750 * 0.8, 2)
    assert trs.trade_type is TradeType.OTHER and trs.value is not None
