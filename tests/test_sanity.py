from insider_trades.sanity import check_all, check_trade


def trade(**kw):
    base = {"market": "NO", "issuer": "X", "source_id": "1", "published_at": "2026-09-01T00:00:00",
            "trade_type": "buy", "currency": "NOK", "quantity": 1000.0, "price": 10.0, "value": 10000.0,
            "parse_confidence": 1.0, "symbol": "X.OL"}
    base.update(kw)
    return base


QUOTE = {"price": 10.0, "currency": "NOK", "market_cap": 1_000_000_000}


def test_plausible_trade_is_kept():
    t = trade()
    assert check_trade(t, QUOTE) is None
    assert t["price"] == 10.0 and t["value"] == 10000.0 and "suspect" not in t


def test_total_in_price_field_is_rejected():
    # Schouw: 25 000 shares at "19 500 000" per share.
    t = trade(quantity=25000.0, price=19_500_000.0, value=487_500_000_000.0, currency="DKK", symbol=None)
    reason = check_trade(t, None)
    assert "above any Nordic share price" in reason  # caught by the per unit cap first
    assert t["price"] is None and t["value"] is None and t["parse_confidence"] <= 0.3


def test_price_far_above_quote_is_rejected():
    t = trade(price=500.0, value=500_000.0)
    assert "x the current share price" in check_trade(t, QUOTE)
    assert t["value"] is None


def test_price_far_below_quote_only_matters_for_shares():
    buy = trade(price=0.1, value=100.0)
    assert check_trade(buy, QUOTE) is not None
    warrant = trade(trade_type="allotment", price=0.1, value=100.0)
    assert check_trade(warrant, QUOTE) is None


def test_value_above_market_cap_is_rejected():
    t = trade(quantity=200_000_000.0, price=10.0, value=2_000_000_000.0)
    assert "market cap" in check_trade(t, QUOTE)


def test_currency_mismatch_uses_rough_fx():
    # 2020 Bulkers: 299 USD against a quote of about 130 NOK is 24x after conversion.
    t = trade(currency="USD", price=299.0, value=299_000.0)
    assert "x the current share price" in check_trade(t, {**QUOTE, "price": 130.0})
    ok = trade(currency="USD", price=12.5, value=12_500.0)
    assert check_trade(ok, {**QUOTE, "price": 130.0}) is None


def test_absurd_price_per_share_without_quote():
    # Schouw: 678 shares at 498 791 DKK each, and no quote to compare with.
    t = trade(currency="DKK", quantity=678.0, price=498_791.04, value=338_180_325.0, symbol=None)
    assert "above any Nordic share price" in check_trade(t, None)
    assert t["value"] is None


def test_check_all_returns_flagged():
    trades = [trade(), trade(source_id="2", price=1_000.0, value=1_000_000.0)]
    flagged = check_all(trades, {"X.OL": QUOTE})
    assert [t["source_id"] for t, _ in flagged] == ["2"]


def test_london_quotes_in_pence():
    # AstraZeneca: 121.02 GBP per share against a quote of 12552 GBp (125.52 GBP) is fine.
    azn = trade(currency="GBP", price=121.02, value=121_020.0)
    assert check_trade(azn, {"price": 12552.0, "currency": "GBp", "market_cap": None}) is None
    # AJ Bell: 161 SEK against 567 GBp (5.67 GBP, about 77 NOK) is about 2x, fine.
    ajb = trade(currency="SEK", price=161.0, value=161_000.0)
    assert check_trade(ajb, {"price": 567.0, "currency": "GBp", "market_cap": None}) is None
    # A real outlier in pounds is still caught.
    bad = trade(currency="GBP", price=5000.0, value=5_000_000.0)
    assert check_trade(bad, {"price": 12552.0, "currency": "GBp", "market_cap": None}) is not None
