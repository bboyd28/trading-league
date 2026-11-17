# trading-league

A paper-trading league for a Discord server. Everyone starts with $100,000 of
fake money and trades real stocks at real closing prices. The bot ranks the
league and reports each player's risk and return against SPY.

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Put your bot token in `.env`, then start the bot from the project root:

```
python -m bot.main
```

The database is created on first start at `data/league.db`. Older databases are
upgraded automatically.

## Commands

| Command | What it does |
| --- | --- |
| `/register` | Join the league |
| `/portfolio` | Cash, positions, and total value |
| `/buy`, `/buy-amount` | Buy by shares or by dollars |
| `/sell`, `/sell-amount` | Sell by shares (or `all`) or by dollars |
| `/leaderboard` | Standings: all time, past week, or past month |
| `/stats` | Return, volatility, Sharpe, drawdown, and beta vs SPY |
| `/trades` | Your 10 most recent trades |
| `/admin-update` | Admin only. Run the daily price and snapshot job now |
| `/admin-check` | Admin only. Check that cash matches the trade ledger |

## Trading rules

- Orders fill at the last official close, with a 0.10% fee on each trade.
- Trading is closed from 9:30 am to 4:15 pm ET on trading days. That way
  nobody can trade at yesterday's close after reading today's news.
  To turn this off while testing, run
  `UPDATE league_settings SET execution_model = 'any_time'`.
- Minimum purchase is $1.00. No shorting. Shares can be fractional.
- Holidays come from a built-in NYSE calendar. Early-close days are treated as
  normal days.

## How it works

```
bot/        Discord layer: commands, embeds, scheduled jobs
core/
  execution.py       the one place orders are placed (rules + price)
  portfolio.py       accounts, trades, valuation (the trade ledger)
  prices.py          Yahoo download and stored prices
  market_calendar.py NYSE days and Eastern time
  market_updates.py  daily job: prices, then snapshots
  analytics.py       returns, volatility, Sharpe, drawdown, beta
  leaderboard.py     standings from snapshots
  database.py        SQLite setup and migrations
tests/
```

- Money is stored as integer cents. Trades are never edited, so a portfolio can
  always be rebuilt from the `trades` table.
- At 4:30 pm ET on trading days the bot downloads prices and saves a snapshot
  for each player. If the bot was offline, it fills in missed days on startup.
- Snapshots also save per-position rows (`position_snapshots`) for later
  attribution and risk work.

## Tests

```
python -m pytest
```

## Known gaps

- Stock splits and dividends are not handled. A split will show as a false
  loss. The SPY benchmark uses plain closes so the comparison stays fair.
- Yahoo Finance is unofficial and can rate limit. All downloading goes through
  `fetch_daily_prices` in `core/prices.py`, so it can be swapped out.
- Share quantities are stored as text, so holdings are summed in Python.
  Fine for a friend group. Switch to integer units if the trade table grows large.
