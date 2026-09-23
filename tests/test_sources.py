from datetime import date

from insider_trades.models import Market, TradeType
from insider_trades.sources.finansinspektionen import (
    FinansinspektionenSource, decode_export, parse_export,
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
