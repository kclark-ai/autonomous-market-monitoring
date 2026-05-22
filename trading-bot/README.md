# Autonomous Market Monitoring System

A production AI agent that observes market conditions, evaluates signals, manages risk, and executes paper trades without human intervention — every hour the market is open.

**Status:** Live  
**Equities watched:** 10  
**Tick frequency:** 1 hour  
**Backtest return:** +7.4% over 365 days  

---

## What this is

Most portfolio projects are prototypes — things that worked once, in a controlled environment, on a good day. This is not that.

This system runs on the Alpaca Markets paper trading API, pulls live market data every hour, evaluates 10 equities against a multi-signal strategy, and places real simulated orders. The dashboard updates in real time. The risk manager enforces hard limits. The trade log persists across sessions.

It was built, debugged, backtested, and parameter-tuned in a single session. The parameters running live today were selected after a sweep across 4 configurations and 365 days of hourly data across 4 symbols.

---

## Architecture

Market Data (Alpaca API) → Signal Engine (RSI, SMA, MACD) → Risk Layer (stop-loss, circuit breaker, position limits) → Execution (market orders via Alpaca paper trading) → Dashboard (Flask API + vanilla JS, auto-refresh 30s)

**Data ingestion:** Alpaca Markets API pulls hourly OHLCV bars for all 10 symbols. 60-bar rolling window. IEX feed.

**Signal engine:** RSI(14), SMA crossover (9/21), 50-bar trend filter, MACD histogram. Requires confluence — no single-indicator trades.

**Risk layer:** Hard stop-loss at 3%. Trailing stop at 3.5%. Daily loss circuit breaker at 5% of portfolio. Position size capped at 10% per trade.

**Execution:** Market orders via Alpaca. Paper trading mode. Configurable for live with a single environment variable change.

**Dashboard:** Flask API + vanilla JS frontend. Auto-refreshes every 30 seconds. Start/stop controls. Accessible on local network.

---

## Risk parameters

| Parameter | Value | Logic |
|---|---|---|
| Hard stop-loss | 3.0% | Maximum loss per position. No exceptions. |
| Trailing stop | 3.5% | Tracks peak price from entry. Exits on reversal. |
| Daily loss limit | 5.0% | Circuit breaker. No new trades after 5% portfolio loss. |
| Max position size | 10% | No single position exceeds 10% of available cash. |

---

## Stack

- Python
- Alpaca Markets API (paper trading)
- pandas
- Flask
- Vanilla JS

Built entirely in Claude Code.

---

## Setup

**Requirements:** Python 3.10+, Mac or Linux (Windows works with minor adjustments)

### 1. Get a free Alpaca paper trading account
Go to [alpaca.markets](https://alpaca.markets) → sign up → go to **Paper Trading** → **API Keys** → generate a key pair. Keep both values handy.

### 2. Clone the repo
```bash
git clone <repo-url>
cd trading-bot
```

### 3. Create your environment file
```bash
cp .env.example .env
```
Open `.env` and fill in your `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. Leave everything else as-is to start.

### 4. Create a virtual environment and install dependencies
```bash
python3 -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 5. Run the bot
```bash
python bot.py
```

The bot starts immediately, runs an initial scan, then scans every 60 minutes. The dashboard is available at `http://localhost:8080` (also accessible from other devices on your local network at `http://<your-ip>:8080`).

### 6. (Optional) Run in the background
```bash
nohup python bot.py > logs/bot.log 2>&1 &
```
Logs go to `logs/bot.log`. Check status with `tail -f logs/bot.log`.

### 7. (Optional) Telegram alerts
Set up a Telegram bot at [t.me/BotFather](https://t.me/BotFather) to get a token, then run:
```bash
python -c "from src.notify import get_chat_id; get_chat_id()"
```
Add the token and chat ID to your `.env`. The bot will send trade alerts and accept commands like `/status`, `/positions`, `/stop`, `/start`.

---

## Why this matters beyond trading

This isn't a finance project. It's a demonstration of a production autonomous agent with a data pipeline, signal engine, risk layer, state manager, API integration, and monitoring interface. That stack is structurally identical to any enterprise AI agent: ingest data, evaluate against defined rules, manage state, execute actions, observe outputs, enforce guardrails. The domain is financial markets. The pattern is universal.

---

## Disclaimer

Paper trading only. Not financial advice. Past backtest performance does not predict future results.

---

→ kevinclark.ai/projects/autonomous-market-monitoring  
→ kevinclark.ai
