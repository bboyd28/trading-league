from decimal import Decimal
import core.prices as prices


def test_get_or_update_price_initializes_new_stock(monkeypatch):
    calls = []

    expected_price = {
        "symbol": "AAPL",
        "price_date": "2026-11-16",
        "price": Decimal("250.00")
    }

    def mock_get_price(symbol, target_date):
        calls.append("lookup")

        if calls.count("lookup") == 1:
            raise ValueError("No price history found.")

        return expected_price

    def mock_update(symbol, period):
        calls.append(("update", symbol, period))
        return 5

    monkeypatch.setattr(
        prices,
        "get_price_on_or_before",
        mock_get_price
    )

    monkeypatch.setattr(
        prices,
        "update_stock_prices",
        mock_update
    )

    result = prices.get_or_update_price("AAPL", "2026-11-16")

    assert result == expected_price
    assert calls == [
        "lookup",
        ("update", "AAPL", "5d"),
        "lookup"
    ]


def test_get_or_update_price_uses_existing_history(monkeypatch):
    expected_price = {
        "symbol": "AAPL",
        "price_date": "2026-11-16",
        "price": Decimal("250.00")
    }

    monkeypatch.setattr(
        prices,
        "get_price_on_or_before",
        lambda symbol, target_date: expected_price
    )

    def unexpected_update(*args, **kwargs):
        raise AssertionError("Stock prices should not be downloaded.")

    monkeypatch.setattr(
        prices,
        "update_stock_prices",
        unexpected_update
    )

    result = prices.get_or_update_price("AAPL", "2026-11-16")

    assert result == expected_price

    