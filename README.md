# Autonomous Market Monitoring System

An autonomous agent that pulls live market data hourly, evaluates equities and crypto against a multi-signal strategy, manages risk, and places paper trades without human intervention. The system runs continuously during market hours and logs all decisions.

---

## What it does

Every 60 minutes while the market is open, the system pulls hourly OHLCV bars for a configurable watchlist of equities and crypto pairs from the Alpaca Markets API. It runs each symbol through a signal engine (RSI, SMA crossover, MACD), applies a risk layer, and either opens a position, holds, or exits. A Flask dashboard at `localhost:8080` shows live positions, stop levels, and recent trade history.

This is not a prototype. It runs on real Alpaca paper trading infrastructure with persistent state, a daily loss circuit breaker, and intrabar stop checks every minute during open positions.

---

## Repository structure

```
autonomous-market-monitoring/
  trading-bot/    equity and options trading agent (hourly, market hours)
  crypto-bot/     crypto trading agent (every 15 minutes, 24/7)
```

Both bots share the same general architecture and use the same Alpaca API credentials. They are independent processes with separate configuration and state files.

---

## Architecture

```
Market Data (Alpaca API)
  → Signal Engine (RSI 14, SMA 9/21 crossover, MACD 12/26/9, 50-bar trend filter)
  → Risk Layer (hard stop, trailing stop, daily circuit breaker, position limits)
  → Execution (market orders via Alpaca paper trading)
  → State Manager (persists positions and trade log across restarts)
  → Dashboard (Flask API + vanilla JS, auto-refresh 30s)
```

**Signal logic:** A buy requires confluence across at least two of: RSI dip with MACD confirmation, SMA crossover with MACD confirmation, or trend-following conditions (price above 50-bar SMA with short MA above long MA). Sells require confluence on the opposite side. No single-indicator trades.

**Risk parameters:**

| Parameter | Value | What it does |
|---|---|---|
| Hard stop-loss | 3.0% | Exits position immediately at 3% loss from entry |
| Trailing stop | 3.5% | Tracks peak price from entry; exits on 3.5% reversal |
| Daily loss limit | 5.0% | Circuit breaker; no new trades after 5% portfolio drawdown |
| Max position size | 10% | No single position exceeds 10% of available cash |
| Max open positions | 4 | Portfolio concentration cap |

**Intrabar stop checks:** Even though signals run hourly, the risk layer checks stop conditions every minute for open positions so it does not wait a full hour to respond to a sharp move.

---

## Stack

- Python 3.10+
- Alpaca Markets API (paper trading)
- pandas, pandas-ta
- Flask
- Plotly (backtest visualization)
- python-dotenv

---

## How to run

### 1. Get Alpaca paper trading credentials

Go to [alpaca.markets](https://alpaca.markets), sign up, go to Paper Trading, then API Keys, and generate a key pair.

### 2. Clone and configure

```bash
git clone https://github.com/kclark-ai/autonomous-market-monitoring.git
cd autonomous-market-monitoring/trading-bot
cp .env.example .env
```

Open `.env` and fill in `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. Leave everything else as-is to start.

### 3. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Run

```bash
python bot.py
```

The bot runs an initial scan immediately, then scans every 60 minutes. The dashboard is at `http://localhost:8080`.

To run in the background:

```bash
nohup python bot.py > logs/bot.log 2>&1 &
```

### 5. Telegram alerts (optional)

Create a bot at [t.me/BotFather](https://t.me/BotFather) to get a token, then run:

```bash
python -c "from src.notify import get_chat_id; get_chat_id()"
```

Add the token and chat ID to `.env`. The bot will send trade alerts and accept `/status`, `/positions`, `/stop`, and `/start` commands.

---

## Performance

_Section in progress. Will include realized P&L, win rate, and drawdown once paper trading has run for a full quarter._

---

## Disclaimer

This system trades paper only. It is not financial advice. Backtest results do not predict future performance. Do not use this with a live brokerage account without fully understanding the code and the risks involved.

---

kevinclark.ai/projects/autonomous-market-monitoring
