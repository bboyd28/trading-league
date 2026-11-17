from decimal import Decimal

import numpy as np
import pytest

import core.analytics as analytics
import core.database as database
import core.portfolio as portfolio

PLAYER = "101"


def add_snapshots(values, discord_id=PLAYER):
    """values: [(date, total_value_cents)]"""
    portfolio.register_user(discord_id, "Alice")

    with database.get_connection(write=True) as connection:
        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id, snapshot_date, cash_balance_cents,
                holdings_value_cents, total_value_cents
            )
            VALUES (?, ?, 5000000, ? - 5000000, ?)
        """, [(discord_id, d, v, v) for d, v in values])


def add_prices(closes, symbol="SPY", adjusted=None):
    """closes: [(date, close)]. adjusted defaults to the same numbers."""
    with database.get_connection(write=True) as connection:
        connection.executemany("""
            INSERT INTO price_history (symbol, price_date, close_price, adjusted_close, source)
            VALUES (?, ?, ?, ?, 'test')
        """, [
            (symbol, d, str(c), str(adjusted.get(d, c) if adjusted else c))
            for d, c in closes
        ])


THREE_DAYS = [
    ("2026-11-11", 10_000_000),
    ("2026-11-12", 10_200_000),
    ("2026-11-13", 10_100_000),
]
FIVE_DAYS = [
    ("2026-11-10", 10_000_000),
    ("2026-11-11", 10_100_000),
    ("2026-11-12", 9_900_000),
    ("2026-11-13", 10_200_000),
    ("2026-11-16", 10_000_000),
]
FIVE_SPY = [
    ("2026-11-10", 100), ("2026-11-11", 101), ("2026-11-12", 100),
    ("2026-11-13", 102), ("2026-11-16", 101),
]


def fractions(values):
    array = np.array([v for _, v in values], dtype=float)
    return np.diff(array) / array[:-1]


# ---- returns -------------------------------------------------------------

def test_daily_returns(setup_database):
    add_snapshots(THREE_DAYS)

    result = analytics.get_daily_returns(PLAYER)

    assert [r["date"] for r in result] == ["2026-11-12", "2026-11-13"]
    assert result[0]["daily_return"] == Decimal("2")
    assert result[1]["daily_return"] == (Decimal("-100") / Decimal("10200")) * 100


def test_daily_returns_need_two_snapshots(setup_database):
    add_snapshots(THREE_DAYS[:1])
    assert analytics.get_daily_returns(PLAYER) == []


def test_daily_returns_without_snapshots(setup_database):
    portfolio.register_user(PLAYER, "Alice")
    assert analytics.get_daily_returns(PLAYER) == []


def test_cumulative_returns(setup_database):
    add_snapshots(THREE_DAYS)

    result = analytics.get_cumulative_returns(PLAYER)

    assert result[0]["cumulative_return"] == Decimal("2")
    assert result[1]["cumulative_return"] == (Decimal("1.01") - Decimal("1")) * 100


# ---- benchmark -----------------------------------------------------------

def test_benchmark_daily_returns(setup_database):
    add_prices([("2026-11-11", 100), ("2026-11-12", 102), ("2026-11-13", 101)])

    result = analytics.get_benchmark_daily_returns("2026-11-11", "2026-11-13")

    assert result[0]["daily_return"] == Decimal("2")
    assert result[1]["daily_return"] == ((Decimal("101") - Decimal("102")) / Decimal("102")) * 100


def test_benchmark_baseline_is_last_close_on_or_before_start(setup_database):
    add_prices([("2026-11-09", 98), ("2026-11-12", 100), ("2026-11-13", 110)])

    result = analytics.get_benchmark_daily_returns("2026-11-11", "2026-11-13")

    # Baseline is the 9th, so the first return spans 98 -> 100.
    assert [r["date"] for r in result] == ["2026-11-12", "2026-11-13"]


def test_benchmark_cumulative_returns(setup_database):
    add_prices([("2026-11-11", 100), ("2026-11-12", 102), ("2026-11-13", 101)])

    result = analytics.get_benchmark_cumulative_returns("2026-11-11", "2026-11-13")

    assert result[0]["cumulative_return"] == Decimal("2")
    assert result[1]["cumulative_return"] == Decimal("1")


def test_benchmark_uses_close_not_adjusted_close(setup_database):
    """Portfolios exclude dividends, so the benchmark must too."""
    add_prices(
        [("2026-11-11", 100), ("2026-11-12", 102)],
        adjusted={"2026-11-11": 90, "2026-11-12": 99},
    )

    result = analytics.get_benchmark_daily_returns("2026-11-11", "2026-11-12")

    assert result[0]["daily_return"] == Decimal("2")


def test_benchmark_without_history(setup_database):
    with pytest.raises(ValueError, match="No price history found for SPY"):
        analytics.get_benchmark_daily_returns("2026-11-11", "2026-11-13")


def test_benchmark_rejects_backwards_dates(setup_database):
    with pytest.raises(ValueError, match="Start date cannot be after end date"):
        analytics.get_benchmark_daily_returns("2026-11-13", "2026-11-11")


def test_compare_portfolio_to_benchmark(setup_database):
    add_snapshots(THREE_DAYS)
    add_prices([("2026-11-11", 100), ("2026-11-12", 101), ("2026-11-13", 103)])

    result = analytics.compare_portfolio_to_benchmark(PLAYER)

    assert result[0]["portfolio_return"] == Decimal("2")
    assert result[0]["benchmark_return"] == Decimal("1")
    assert result[0]["excess_return"] == Decimal("1")
    assert result[1]["portfolio_return"] == Decimal("1")
    assert result[1]["benchmark_return"] == Decimal("3")
    assert result[1]["excess_return"] == Decimal("-2")


# ---- risk metrics (checked against numpy) --------------------------------

def test_volatility_matches_numpy(setup_database):
    add_snapshots(FIVE_DAYS)

    expected = np.std(fractions(FIVE_DAYS), ddof=1) * np.sqrt(252) * 100

    assert float(analytics.get_portfolio_volatility(PLAYER)) == pytest.approx(expected)


def test_sharpe_matches_numpy(setup_database):
    add_snapshots(FIVE_DAYS)
    returns = fractions(FIVE_DAYS)

    expected = returns.mean() / returns.std(ddof=1) * np.sqrt(252)

    assert float(analytics.get_sharpe_ratio(PLAYER)) == pytest.approx(expected)


def test_sharpe_subtracts_the_risk_free_rate(setup_database):
    add_snapshots(FIVE_DAYS)

    plain = analytics.get_sharpe_ratio(PLAYER)
    with_rate = analytics.get_sharpe_ratio(PLAYER, risk_free_rate=Decimal("5"))

    assert with_rate < plain


def test_sharpe_rejects_impossible_risk_free_rate(setup_database):
    with pytest.raises(ValueError, match="greater than -100"):
        analytics.get_sharpe_ratio(PLAYER, risk_free_rate=Decimal("-100"))


def test_flat_portfolio_has_no_sharpe(setup_database):
    add_snapshots([("2026-11-10", 10_000_000), ("2026-11-11", 10_000_000),
                   ("2026-11-12", 10_000_000)])

    assert analytics.get_sharpe_ratio(PLAYER) is None


def test_metrics_need_enough_data(setup_database):
    add_snapshots(THREE_DAYS[:2])   # a single return

    assert analytics.get_portfolio_volatility(PLAYER) is None
    assert analytics.get_sharpe_ratio(PLAYER) is None
    assert analytics.get_max_drawdown(PLAYER) is not None
    assert analytics.get_portfolio_beta(PLAYER) is None


def test_max_drawdown(setup_database):
    add_snapshots([
        ("2026-11-10", 10_000_000), ("2026-11-11", 10_500_000),
        ("2026-11-12", 9_500_000), ("2026-11-13", 9_000_000),
        ("2026-11-16", 10_200_000),
    ])

    assert analytics.get_max_drawdown(PLAYER) == Decimal("-14.28571428571428571428571429")


def test_beta_matches_numpy_and_uses_every_day(setup_database):
    add_snapshots(FIVE_DAYS)
    add_prices(FIVE_SPY)

    mine = fractions(FIVE_DAYS)
    market = fractions(FIVE_SPY)
    expected = np.cov(mine, market)[0, 1] / np.var(market, ddof=1)

    assert float(analytics.get_portfolio_beta(PLAYER)) == pytest.approx(expected)


def test_beta_is_none_when_the_market_is_flat(setup_database):
    add_snapshots(FIVE_DAYS)
    add_prices([(d, 100) for d, _ in FIVE_DAYS])

    assert analytics.get_portfolio_beta(PLAYER) is None


# ---- summary -------------------------------------------------------------

def test_performance_summary(setup_database):
    add_snapshots(FIVE_DAYS)
    add_prices(FIVE_SPY)

    summary = analytics.get_performance_summary(PLAYER)

    assert summary["start_date"] == "2026-11-10"
    assert summary["end_date"] == "2026-11-16"
    assert summary["observations"] == 4
    assert summary["total_return_pct"] == Decimal("0")
    assert summary["benchmark_return_pct"] == Decimal("1")
    assert summary["excess_return_pct"] == Decimal("-1")
    assert float(summary["volatility_pct"]) == pytest.approx(
        float(analytics.get_portfolio_volatility(PLAYER))
    )
    assert float(summary["beta"]) == pytest.approx(float(analytics.get_portfolio_beta(PLAYER)))


def test_summary_works_without_benchmark_data(setup_database):
    add_snapshots(FIVE_DAYS)

    summary = analytics.get_performance_summary(PLAYER)

    assert summary["volatility_pct"] is not None
    assert summary["beta"] is None
    assert summary["benchmark_return_pct"] is None


def test_summary_is_none_without_history(setup_database):
    portfolio.register_user(PLAYER, "Alice")
    assert analytics.get_performance_summary(PLAYER) is None
