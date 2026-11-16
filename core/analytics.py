from decimal import Decimal
from core.database import get_connection

import statistics

def get_daily_returns(discord_id: str):
    """
    Calculate daily portfolio returns using historical snapshots.

    Returns the percentage change in portfolio value
    between consecutive snapshots.
    """

    with get_connection() as connection:

        snapshots = connection.execute("""
            SELECT snapshot_date, total_value_cents
            FROM portfolio_snapshots
            WHERE discord_id = ?
            ORDER BY snapshot_date ASC
        """, (discord_id,)).fetchall()

    if len(snapshots) < 2:
        return []

    daily_returns = []

    for previous, current in zip(snapshots, snapshots[1:]):

        previous_value = Decimal(
            previous["total_value_cents"]
        )

        current_value = Decimal(
            current["total_value_cents"]
        )

        daily_return = (
            (current_value - previous_value)
            / previous_value
        ) * 100

        daily_returns.append({
            "date": current["snapshot_date"],
            "daily_return": daily_return
        })

    return daily_returns

def get_cumulative_returns(discord_id: str):
    """
    Calculate cumulative portfolio returns over time.

    Measures total performance relative to the
    participant's original starting balance.
    """

    daily_returns = get_daily_returns(discord_id)

    if not daily_returns:
        return []

    cumulative_returns = []

    cumulative_growth = Decimal("1")

    for observation in daily_returns:

        daily_return = observation["daily_return"]

        cumulative_growth *= (
            Decimal("1") + daily_return / Decimal("100")
        )

        cumulative_return = (
            cumulative_growth - Decimal("1")
        ) * Decimal("100")

        cumulative_returns.append({
            "date": observation["date"],
            "cumulative_return": cumulative_return
        })

    return cumulative_returns


def get_benchmark_daily_returns(
    start_date: str,
    end_date: str,
    symbol: str = "SPY"
):
    """
    Calculate daily benchmark returns using adjusted closing prices.

    Includes the last available trading price on or before
    start_date as the baseline for calculating returns.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Benchmark symbol is required.")

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    with get_connection() as connection:

        prices = connection.execute("""
            SELECT price_date, adjusted_close
            FROM price_history
            WHERE symbol = ?
            AND price_date <= ?
            AND price_date >= (
                SELECT MAX(price_date)
                FROM price_history
                WHERE symbol = ?
                AND price_date <= ?
                AND adjusted_close IS NOT NULL
            )
            AND adjusted_close IS NOT NULL
            ORDER BY price_date ASC
        """, (
            symbol,
            end_date,
            symbol,
            start_date
        )).fetchall()

    if not prices:
        raise ValueError(
            f"No adjusted price history found for {symbol} "
            f"on or before {start_date}."
        )

    if len(prices) < 2:
        return []

    benchmark_returns = []

    for previous, current in zip(prices, prices[1:]):

        previous_price = Decimal(previous["adjusted_close"])
        current_price = Decimal(current["adjusted_close"])

        daily_return = (
            (current_price - previous_price)
            / previous_price
        ) * 100

        benchmark_returns.append({
            "date": current["price_date"],
            "daily_return": daily_return
        })

    return benchmark_returns

def get_benchmark_cumulative_returns(
    start_date: str,
    end_date: str,
    symbol: str = "SPY"
):
    """
    Calculate cumulative benchmark returns over time.
    """

    daily_returns = get_benchmark_daily_returns(
        start_date,
        end_date,
        symbol
    )

    if not daily_returns:
        return []

    cumulative_returns = []
    cumulative_growth = Decimal("1")

    for observation in daily_returns:

        daily_return = observation["daily_return"]

        cumulative_growth *= (
            Decimal("1") + daily_return / Decimal("100")
        )

        cumulative_return = (
            cumulative_growth - Decimal("1")
        ) * Decimal("100")

        cumulative_returns.append({
            "date": observation["date"],
            "cumulative_return": cumulative_return
        })

    return cumulative_returns


def compare_portfolio_to_benchmark(
    discord_id: str,
    symbol: str = "SPY"
):
    """
    Compare a participant's cumulative returns
    against a market benchmark.

    Returns results for dates shared by both datasets.
    """

    portfolio_returns = get_cumulative_returns(discord_id)

    if not portfolio_returns:
        return []

    # Find the participant's first recorded snapshot.
    with get_connection() as connection:

        first_snapshot = connection.execute("""
            SELECT MIN(snapshot_date) AS first_date
            FROM portfolio_snapshots
            WHERE discord_id = ?
        """, (discord_id,)).fetchone()

    start_date = first_snapshot["first_date"]
    end_date = portfolio_returns[-1]["date"]

    # Calculate benchmark performance over the same period.
    benchmark_returns = get_benchmark_cumulative_returns(
        start_date,
        end_date,
        symbol
    )

    # Organize benchmark results by date.
    benchmark_by_date = {
        observation["date"]: observation["cumulative_return"]
        for observation in benchmark_returns
    }

    comparisons = []

    for observation in portfolio_returns:

        date = observation["date"]

        if date not in benchmark_by_date:
            continue

        portfolio_return = observation["cumulative_return"]
        benchmark_return = benchmark_by_date[date]

        comparisons.append({
            "date": date,
            "portfolio_return": portfolio_return,
            "benchmark_return": benchmark_return,
            "excess_return": portfolio_return - benchmark_return
        })

    return comparisons


def get_portfolio_volatility(discord_id: str):
    """
    Calculate annualized historical portfolio volatility.

    Uses the sample standard deviation of daily returns.
    """

    daily_returns = get_daily_returns(discord_id)

    if len(daily_returns) < 2:
        return None

    returns = [
        float(observation["daily_return"]) / 100
        for observation in daily_returns
    ]

    daily_volatility = statistics.stdev(returns)

    annualized_volatility = daily_volatility * (252 ** 0.5)

    return Decimal(str(annualized_volatility)) * 100


def get_sharpe_ratio(
    discord_id: str,
    risk_free_rate: Decimal = Decimal("0")
):
    """
    Calculate the annualized Sharpe ratio of a portfolio.

    Risk-free rate is expressed as an annual percentage.
    """

    if risk_free_rate <= Decimal("-100"):
        raise ValueError("Risk-free rate must be greater than -100%.")

    daily_returns = get_daily_returns(discord_id)

    if len(daily_returns) < 2:
        return None

    returns = [
        float(observation["daily_return"]) / 100
        for observation in daily_returns
    ]

    annual_risk_free_rate = float(risk_free_rate) / 100

    daily_risk_free_rate = (
        (1 + annual_risk_free_rate) ** (1 / 252)
    ) - 1

    excess_returns = [
        daily_return - daily_risk_free_rate
        for daily_return in returns
    ]

    average_excess_return = statistics.mean(excess_returns)
    daily_volatility = statistics.stdev(returns)

    if daily_volatility == 0:
        return None

    sharpe_ratio = (
        average_excess_return / daily_volatility
    ) * (252 ** 0.5)

    return Decimal(str(sharpe_ratio))


def get_max_drawdown(discord_id: str):
    """
    Calculate the maximum drawdown of a portfolio.

    Returns the largest percentage decline from a previous
    portfolio peak to a subsequent trough.
    """

    with get_connection() as connection:
        snapshots = connection.execute("""
            SELECT snapshot_date, total_value_cents
            FROM portfolio_snapshots
            WHERE discord_id = ?
            ORDER BY snapshot_date ASC
        """, (discord_id,)).fetchall()

    if len(snapshots) < 2:
        return None

    peak_value = Decimal(snapshots[0]["total_value_cents"])
    max_drawdown = Decimal("0")

    for snapshot in snapshots[1:]:
        current_value = Decimal(snapshot["total_value_cents"])

        if current_value > peak_value:
            peak_value = current_value

        drawdown = (
            (current_value - peak_value) / peak_value
        ) * 100

        if drawdown < max_drawdown:
            max_drawdown = drawdown

    return max_drawdown


def get_portfolio_beta(discord_id: str, symbol: str = "SPY"):
    """
    Calculate portfolio beta relative to a market benchmark.

    Beta measures how sensitive portfolio returns are to
    movements in the benchmark.
    """

    portfolio_returns = get_daily_returns(discord_id)

    if len(portfolio_returns) < 2:
        return None

    first_date = portfolio_returns[0]["date"]
    last_date = portfolio_returns[-1]["date"]

    benchmark_returns = get_benchmark_daily_returns(
        first_date,
        last_date,
        symbol
    )

    portfolio_by_date = {
        observation["date"]: float(observation["daily_return"]) / 100
        for observation in portfolio_returns
    }

    benchmark_by_date = {
        observation["date"]: float(observation["daily_return"]) / 100
        for observation in benchmark_returns
    }

    common_dates = sorted(
        set(portfolio_by_date) & set(benchmark_by_date)
    )

    if len(common_dates) < 2:
        return None

    aligned_portfolio = [
        portfolio_by_date[date] for date in common_dates
    ]

    aligned_benchmark = [
        benchmark_by_date[date] for date in common_dates
    ]

    benchmark_variance = statistics.variance(aligned_benchmark)

    if benchmark_variance == 0:
        return None

    covariance = statistics.covariance(
        aligned_portfolio,
        aligned_benchmark
    )

    beta = covariance / benchmark_variance

    return Decimal(str(beta))