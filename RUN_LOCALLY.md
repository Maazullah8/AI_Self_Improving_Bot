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
# .venv\Scripts\activate       # Windows

# install backend + API dependencies
pip install -e ".[api,dev]"
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

You should see `Uvicorn running on http://0.0.0.0:8000`.
**Keep this terminal open.**

## 6. Seed it with real data (optional)

In a second terminal, once the backend is up:

```bash
curl -s -X POST http://localhost:8000/api/backtest -H "Content-Type: application/json" \
  -d '{"symbol":"EURUSD","timeframe":"5m","start":0,"end":0,"initial_cash":10000,"strategy":"smc_crt","params":{"htf":"4h","zone_tf":"4h","ltf":"5m"},"seed":42}'

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
