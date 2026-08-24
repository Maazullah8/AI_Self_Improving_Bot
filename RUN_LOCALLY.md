# Run It Yourself

Everything you need to run the trading bot dashboard on **your own computer**,
including how to pull real market data from **MetaTrader 5** for backtesting.

## 1. Prerequisites

| Tool | Version | How to check |
|---|---|---|
| Python | 3.10+ | `python3 --version` |
| Node.js | 18.17+ | `node --version` |
| npm | 9+ | `npm --version` |
| Git | any | `git --version` |

- **macOS**: `brew install python node git`
- **Windows**: install from python.org, nodejs.org, and git-scm.com
- **Linux (Debian/Ubuntu)**:
  ```bash
  sudo apt update
  sudo apt install -y python3 python3-venv git
  ```
  Install Node from https://nodejs.org.

## 2. Get the code

```bash
git clone <your-repo-url>
cd <repo-folder>
```

> If the repo isn't hosted anywhere, copy the project folder to your computer
> (zip it up or push it to a private GitHub repo first).

## 3. Set up the backend

```bash
# create an isolated Python environment
python3 -m venv .venv

# activate it
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate       # Windows

# install backend + API dependencies
pip install -e ".[api,dev]"

# optional: real market data via yfinance (free, cross-platform)
pip install -e ".[yfinance]"
```

## 4. Set up the dashboard

```bash
cd dashboard
npm install
cd ..
```

## 5. Start the backend

```bash
# make sure the venv is active (see step 3)
python -m trading_bot.api.run
```

The server auto-detects the data source:
- **yfinance installed** → live Yahoo data (default symbol **XAUUSD**)
- otherwise → a deterministic synthetic demo feed (UI still works)

Useful flags:
```bash
# force the demo feed
python -m trading_bot.api.run --provider synthetic

# run a backtest + AI review at startup so the dashboard isn't empty
python -m trading_bot.api.run --seed-demo

# start a PAPER live pipeline (simulated executor, never real money)
python -m trading_bot.api.run --live --symbol XAUUSD --timeframe 5m
```

You should see `Uvicorn running on http://0.0.0.0:8000`.
**Keep this terminal open.**

## 6. Seed it with real data (optional)

In a second terminal, once the backend is up:

```bash
curl -s -X POST http://localhost:8000/api/backtest -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","timeframe":"5m","start":0,"end":0,"initial_cash":10000,"strategy":"smc_crt","params":{"htf":"4h","zone_tf":"4h","ltf":"5m"},"seed":42}'

curl -s -X POST http://localhost:8000/api/review -H "Content-Type: application/json" \
  -d '{"strategy":"smc_crt","strategy_version":"v1.0"}'
```

> Windows PowerShell users: replace `curl ... -d '{...}'` with
> `Invoke-RestMethod -Uri http://localhost:8000/api/backtest -Method Post -Body '{"..."}' -ContentType "application/json"`.

## 7. Start the dashboard

```bash
cd dashboard
npm run dev
```

Open **http://localhost:3000**. The dashboard proxies `/api/*` to the backend
on `:8000` automatically.

## 8. Stop / restart

- Stop a server with **Ctrl+C** in its terminal.
- To restart, run steps 5 and 7 again.
- Run the test suite with `pytest` from the repo root.

---

## Backtesting on MetaTrader 5 data

The bot ships with an `MT5DataProvider` (read-only bars — it never places
orders) and an `MT5Executor` (order execution for demo/live). For backtesting
you only need the provider.

### Requirements

- **Windows** — the MT5 terminal only runs on Windows.
- MetaTrader 5 terminal installed and logged into an **account (demo is fine)**.
- The symbol you want (e.g. EURUSD) visible in Market Watch with history
  downloaded (right-click symbol → *Bars* / *Copy all periods*).
- The Python `MetaTrader5` package:
  ```bash
  pip install MetaTrader5
  ```

### Step-by-step

1. **Open the MT5 terminal** and log in to your (demo) account. Leave it
   running in the background.
2. **Verify the connection** from Python (venv active):
   ```bash
   python -c "from trading_bot.data.mt5_provider import MT5DataProvider; p = MT5DataProvider(); print(p.available_symbols()[:10]); p.shutdown()"
   ```
   You should see a list of symbols (e.g. `['EURUSD', 'GBPUSD', ...]`).
3. **Run the MT5 backtest script** (a ready-made CLI is included):
   ```bash
   python -m examples.backtest_mt5 --symbol EURUSD --timeframe H1 \
       --start 2023-01-01 --end 2023-12-31 --initial-cash 10000
   ```
   Output includes bars analyzed, trades, win rate, profit factor, net profit,
   max drawdown, and Sharpe. `--timeframe` accepts `1m, 3m, 5m, 15m, 30m,
   1h, 4h, 1d, 1w, 1mo`.

### Use MT5 data in the dashboard API (optional)

The API server picks its data source in `src/trading_bot/api/run.py`
(`build_provider()`). To backtest through the dashboard on real MT5 data,
swap the synthetic provider for the MT5 one:

```python
from trading_bot.data.mt5_provider import MT5DataProvider

def build_provider():
    return MT5DataProvider()
```

Then `POST /api/backtest` from the dashboard's **Backtesting** page will run on
real bars. The provider is fail-closed: if MT5 isn't running, the endpoint
returns an error instead of fabricating data.

### Going further (execution)

To execute signals on a MT5 demo account you'd wire `MT5Executor(login=...,
password=..., server=...)` into the live pipeline instead of the simulated
executor. **Never use a real-money account without fully reviewing the
validation gates** — see the strategy promotion workflow in `README.md`.

---

## Backtesting on free Yahoo Finance data (yfinance)

No Windows, no MT5 terminal — works on macOS, Windows and Linux. Pulls OHLCV
bars straight from Yahoo Finance.

```bash
pip install -e ".[yfinance]"
```

### Run a backtest on XAUUSD (gold)

```bash
python -m examples.backtest_yahoo --symbol XAUUSD --timeframe 1h \
    --start 2024-01-01 --end 2024-06-30 --initial-cash 10000
```

Output includes bars analyzed, trades, win rate, profit factor, net profit,
max drawdown and Sharpe. `--timeframe` accepts `1m, 3m, 5m, 15m, 30m, 1h,
4h, 1d, 1w, 1mo`. Supported symbols: `XAUUSD` (gold), `XAGUSD` (silver),
`SPX`, `NAS100`, `BTCUSD`, `ETHUSD`, plus any Yahoo ticker passed through
(e.g. `EURUSD=X`).

> **Equity curve & Monte Carlo in the dashboard**: after you click **Run
> backtest** on the *Backtesting* page, the result shows the **equity curve**
> chart and a **Monte Carlo** panel (2,000 bootstrap resamples of your actual
> trade sequence): median / P5 / P95 final equity, worst drawdown and losing
> streak at the 95th percentile, and the risk of ruin. The promotion gates in
> `src/trading_bot/validation/pipeline.py` require MC ruin < 5% and MC
> drawdown < 40% before a strategy can be promoted.

> **About XAUUSD on Yahoo**: Yahoo has no spot-gold ticker, so the provider
> maps `XAUUSD → GC=F` (front-month COMEX gold futures) — the closest
> freely-available series. See the docstring in
> `src/trading_bot/data/yahoo_provider.py`.

---

## Live (paper) trading with XAUUSD

The live pipeline is **fail-closed and paper-only by default**: it reads live
bars, runs the strategy, and executes through a `SimulatedExecutor` that never
touches a real account.

```bash
python -m trading_bot.api.run --live --symbol XAUUSD --timeframe 5m --poll-seconds 30
```

- Open the dashboard's **Live Trades** page — it auto-refreshes every 10s and
  shows pipeline status, balance/equity, realized P&L and open positions.
- Positions are managed bar-by-bar: **SL / TP are checked on every new bar**
  (conservative SL-first on same-bar double breach) and closed trades are
  journaled, so they flow into Analytics, Trade History and AI Review.
- `/api/live` exposes the full snapshot for the dashboard.

### MT5 demo trading (real orders, demo account)

MetaTrader 5 lets the bot place **real orders on a demo account** — the exact
same strategy, risk and journaling code as paper trading. This is how you
validate execution against a real broker feed before ever considering live
money.

**1. Install & log in to MT5**
- Install the MetaTrader 5 desktop terminal (**Windows only**).
- Open it and log in to a **demo account** (in the terminal: *File → Open an
  Account → Open a demo account*). Leave the terminal **running** in the
  background.
- Make sure the symbol you'll trade (e.g. `XAUUSD`) is visible in *Market
  Watch* with history downloaded.
- Install the Python package:
  ```bash
  pip install MetaTrader5
  ```

**2. Start the bot against your demo account**

```bash
python -m trading_bot.api.run --live --symbol XAUUSD --timeframe 5m \
    --executor mt5 --mt5-login 12345678 --mt5-password yourpass \
    --mt5-server "ICMarkets-Demo" --poll-seconds 30
```

| Flag | Meaning |
|---|---|
| `--executor mt5` | route orders through the MT5 terminal (fail-closed if it can't) |
| `--mt5-login` | your demo account login (number) |
| `--mt5-password` | demo account password |
| `--mt5-server` | broker server name, exactly as it appears in MT5 login |
| `--mt5-path` | full path to `terminal64.exe` if it isn't auto-detected |
| `--timeframe` | bar timeframe; keep `--poll-seconds` ≈ 2–6× the bar length |

The server **refuses to start** if MT5 isn't ready (no terminal, wrong
credentials, symbol missing) — it never guesses.

**3. Watch it**

- The dashboard's **Live Trades** page shows positions, balance and P&L in
  near real time.
- Trades also appear in your MT5 terminal under *Trade*, with SL/TP attached
  to each order.
- Closed trades are journaled and show up in Analytics, Trade History and AI
  Review — exactly like backtests.

**4. Safety rules (don't skip)**

- Use a **demo account** until the strategy passes the promotion gates
  (Monte Carlo ruin < 5%, drawdown tail < 40%, see `README.md`).
- The pipeline is fail-closed: stale data, strategy errors, or an unhealthy
  broker mean **no trade**. That's a safety net, not a substitute for
  validation — review AI feedback before real money.
- `--seed-demo` only populates historical data; it never affects live orders.

---

## Where to change the trading symbol (XAUUSD → something else)

1. **Backend / live data** — `src/trading_bot/api/run.py`:
   - default `--symbol` is `XAUUSD`; pass `--symbol EURUSD` (or `XAGUSD`,
     `BTCUSD`, …) to the `python -m trading_bot.api.run` command.
2. **Dashboard backtest** — `dashboard/app/backtesting/page.js` line ~47:
   `symbol: "XAUUSD"` (the body of the `POST /api/backtest` request).
3. **Backtest API default** — `src/trading_bot/api/app.py`:
   `BacktestRequest.symbol = "XAUUSD"`.
4. **CLI backtests** — `examples/backtest_yahoo.py` / `examples/backtest_mt5.py`:
   the `--symbol` flag.
5. **MT5-only symbols** — `MT5DataProvider` uses the symbol as-is, so a custom
   broker symbol (e.g. `XAUUSD.m`) must match what appears in your MT5
   Market Watch.

## Backtesting data sources (data folder / Supabase / Yahoo)

The Backtesting page shows exactly **where each backtest's candles come from**
in the "Data Source" card (active provider, file path or table URL, bar count
and date coverage).

Priority when started with the default `--provider auto`:

1. **Local data folder** - any `*.jsonl` candle file in `src/trading_bot/data/`
   (e.g. `XAU_5m_data.jsonl`). This is the default and works fully offline.
2. **Supabase** - used automatically when credentials are present (see below).
3. **Yahoo Finance** - fallback when yfinance is installed.
4. **Synthetic** - deterministic demo feed, last resort.

Force a specific source with:

```bash
PYTHONPATH=src python -m trading_bot.api.run --provider jsonl      # data folder only
PYTHONPATH=src python -m trading_bot.api.run --provider supabase   # Supabase only
```

### Connect your Supabase database

1. Copy `.env.example` to `.env` in the repository root.
2. Fill in your values from Supabase Dashboard -> Project Settings -> API:

   ```
   SUPABASE_URL=https://YOUR-PROJECT-ref.supabase.co
   SUPABASE_KEY=your-anon-or-service-key
   SUPABASE_TABLE=candles
   ```

3. Create the candles table once (Supabase SQL editor):

   ```sql
   create table if not exists candles (
       symbol    text        not null,
       timeframe text        not null,
       time      bigint      not null,
       open      double precision not null,
       high      double precision not null,
       low       double precision not null,
       close     double precision not null,
       volume    double precision default 0,
       spread    double precision default 0,
       primary key (symbol, timeframe, time)
   );
   ```

4. Restart the API server. The Data Source card will show
   "Supabase (https://your-project...)" with a green dot when connected.
