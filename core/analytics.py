"""Performance metrics built from daily portfolio snapshots.

Snapshots are saved on trading days only, so annualizing with 252 days
is fair. The benchmark uses plain closes (no dividends), the same way
portfolios are valued here.
"""
import statistics
from decimal import Decimal

from core.database import get_connection
from core.prices import normalize_symbol

TRADING_DAYS = 252


# ---- loading -------------------------------------------------------------

def _load_snapshots(discord_id):
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT snapshot_date, total_value_cents
            FROM portfolio_snapshots
            WHERE discord_id = ?
            ORDER BY snapshot_date
        """, (discord_id,)).fetchall()

    return [(row["snapshot_date"], Decimal(row["total_value_cents"])) for row in rows]


def _load_benchmark(start_date, end_date, symbol):
    """Closes from the last trading day on or before start_date through end_date."""
    symbol = normalize_symbol(symbol)

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    with get_connection() as connection:
        baseline = connection.execute("""
            SELECT MAX(price_date) AS price_date FROM price_history
            WHERE symbol = ? AND price_date <= ?
        """, (symbol, start_date)).fetchone()["price_date"]

        if baseline is None:
            raise ValueError(
                f"No price history found for {symbol} on or before {start_date}."
            )

        rows = connection.execute("""
            SELECT price_date, close_price FROM price_history
            WHERE symbol = ? AND price_date >= ? AND price_date <= ?
            ORDER BY price_date
        """, (symbol, baseline, end_date)).fetchall()

    return [(row["price_date"], Decimal(row["close_price"])) for row in rows]


# ---- pure math (no database) ---------------------------------------------

def _pct_changes(series):
    """Percent change between consecutive (date, value) pairs."""
    return [
        {"date": date, "daily_return": ((value - previous) / previous) * 100}
        for (_, previous), (date, value) in zip(series, series[1:])
    ]


def _compound(daily):
    growth = Decimal("1")
    cumulative = []

    for observation in daily:
        growth *= Decimal("1") + observation["daily_return"] / Decimal("100")
        cumulative.append({
            "date": observation["date"],
            "cumulative_return": (growth - Decimal("1")) * Decimal("100"),
        })

    return cumulative


def _fractions(daily):
    return [float(o["daily_return"]) / 100 for o in daily]


def _volatility(returns):
    if len(returns) < 2:
        return None

    annual = statistics.stdev(returns) * (TRADING_DAYS ** 0.5)
    return Decimal(str(annual)) * 100


def _sharpe(returns, risk_free_rate):
    if len(returns) < 2:
        return None

    daily_risk_free = (1 + float(risk_free_rate) / 100) ** (1 / TRADING_DAYS) - 1
    excess = [r - daily_risk_free for r in returns]
    spread = statistics.stdev(excess)

    if spread == 0:
        return None

    return Decimal(str(statistics.mean(excess) / spread * (TRADING_DAYS ** 0.5)))


def _max_drawdown(series):
    if len(series) < 2:
        return None

    peak = series[0][1]
    worst = Decimal("0")

    for _, value in series[1:]:
        peak = max(peak, value)
        worst = min(worst, ((value - peak) / peak) * 100)

    return worst


def _beta(portfolio_daily, benchmark_daily):
    mine = {o["date"]: float(o["daily_return"]) / 100 for o in portfolio_daily}
    market = {o["date"]: float(o["daily_return"]) / 100 for o in benchmark_daily}
    shared = sorted(set(mine) & set(market))

    if len(shared) < 2:
        return None

    market_returns = [market[d] for d in shared]
    variance = statistics.variance(market_returns)

    if variance == 0:
        return None

    covariance = statistics.covariance([mine[d] for d in shared], market_returns)
    return Decimal(str(covariance / variance))


def _check_risk_free(risk_free_rate):
    if risk_free_rate <= Decimal("-100"):
        raise ValueError("Risk-free rate must be greater than -100%.")


# ---- public functions ----------------------------------------------------

def get_daily_returns(discord_id):
    return _pct_changes(_load_snapshots(discord_id))


def get_cumulative_returns(discord_id):
    return _compound(get_daily_returns(discord_id))


def get_benchmark_daily_returns(start_date, end_date, symbol="SPY"):
    return _pct_changes(_load_benchmark(start_date, end_date, symbol))


def get_benchmark_cumulative_returns(start_date, end_date, symbol="SPY"):
    return _compound(get_benchmark_daily_returns(start_date, end_date, symbol))


def compare_portfolio_to_benchmark(discord_id, symbol="SPY"):
    """Cumulative portfolio vs benchmark return on the dates both have."""
    snapshots = _load_snapshots(discord_id)
    portfolio = _compound(_pct_changes(snapshots))

    if not portfolio:
        return []

    benchmark = {
        o["date"]: o["cumulative_return"]
        for o in get_benchmark_cumulative_returns(
            snapshots[0][0], snapshots[-1][0], symbol
        )
    }

    return [
        {
            "date": o["date"],
            "portfolio_return": o["cumulative_return"],
            "benchmark_return": benchmark[o["date"]],
            "excess_return": o["cumulative_return"] - benchmark[o["date"]],
        }
        for o in portfolio
        if o["date"] in benchmark
    ]


def get_portfolio_volatility(discord_id):
    """Annualized volatility, in percent."""
    return _volatility(_fractions(get_daily_returns(discord_id)))


def get_sharpe_ratio(discord_id, risk_free_rate=Decimal("0")):
    """Annualized Sharpe ratio. risk_free_rate is an annual percent."""
    _check_risk_free(risk_free_rate)
    return _sharpe(_fractions(get_daily_returns(discord_id)), risk_free_rate)


def get_max_drawdown(discord_id):
    """Largest peak-to-trough drop, in percent (a negative number)."""
    return _max_drawdown(_load_snapshots(discord_id))


def get_portfolio_beta(discord_id, symbol="SPY"):
    snapshots = _load_snapshots(discord_id)
    daily = _pct_changes(snapshots)

    if len(daily) < 2:
        return None

    benchmark = _pct_changes(_load_benchmark(snapshots[0][0], snapshots[-1][0], symbol))
    return _beta(daily, benchmark)


def get_performance_summary(discord_id, symbol="SPY", risk_free_rate=Decimal("0")):
    """Every headline metric from a single database read. None if too little data."""
    _check_risk_free(risk_free_rate)
    snapshots = _load_snapshots(discord_id)
    daily = _pct_changes(snapshots)

    if not daily:
        return None

    returns = _fractions(daily)
    first, last = snapshots[0], snapshots[-1]
    total_return = ((last[1] - first[1]) / first[1]) * 100

    summary = {
        "start_date": first[0],
        "end_date": last[0],
        "observations": len(daily),
        "total_return_pct": total_return,
        "volatility_pct": _volatility(returns),
        "sharpe": _sharpe(returns, risk_free_rate),
        "max_drawdown_pct": _max_drawdown(snapshots),
        "beta": None,
        "benchmark_return_pct": None,
        "excess_return_pct": None,
    }

    try:
        closes = _load_benchmark(first[0], last[0], symbol)
    except ValueError:
        return summary

    if len(closes) >= 2:
        benchmark_total = ((closes[-1][1] - closes[0][1]) / closes[0][1]) * 100
        summary["beta"] = _beta(daily, _pct_changes(closes))
        summary["benchmark_return_pct"] = benchmark_total
        summary["excess_return_pct"] = total_return - benchmark_total

    return summary
