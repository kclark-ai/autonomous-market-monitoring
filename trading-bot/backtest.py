import argparse
import sys
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT, SMA_SHORT, SMA_LONG, TREND_SMA,
    STOP_LOSS_PCT, TRAILING_STOP_PCT, MIN_HOLD_BARS, COOLDOWN_BARS, POSITION_SIZE_PCT,
)
from src.strategy import compute_indicators, get_signal


def fetch_data(symbol: str, days: int) -> pd.DataFrame:
    end = datetime.today()
    start = end - timedelta(days=days + 60)
    df = yf.download(symbol, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                     interval="1h", auto_adjust=True, progress=False)
    if df.empty:
        print(f"No data returned for {symbol}.")
        sys.exit(1)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    cutoff = end - timedelta(days=days)
    return df[df.index >= pd.Timestamp(cutoff, tz=df.index.tz)]


def run_backtest(df: pd.DataFrame, starting_cash: float) -> dict:
    df = compute_indicators(df)
    cash = starting_cash
    shares = 0
    entry_price = 0.0
    entry_time = None
    peak_price = 0.0
    bars_held = 0
    bars_since_exit = 999
    last_exit_stoploss = False
    trades = []
    equity_curve = []
    buy_markers = []
    sell_markers = []
    trail_stops = []

    for i in range(2, len(df)):
        window = df.iloc[:i + 1]
        row = df.iloc[i]
        price = float(row["close"])
        ts = row.name
        in_position = shares > 0
        portfolio_value = cash + shares * price
        equity_curve.append({"time": ts, "equity": portfolio_value})
        trail_stops.append({"time": ts, "trail": peak_price * (1 - TRAILING_STOP_PCT) if in_position else None})

        if in_position:
            bars_held += 1
            if price > peak_price:
                peak_price = price
            hard_stop = entry_price * (1 - STOP_LOSS_PCT)
            trail_stop = peak_price * (1 - TRAILING_STOP_PCT)
            in_profit = price > entry_price * 1.005

            if price <= hard_stop:
                pnl = (price - entry_price) * shares
                cash += shares * price
                trades.append({"entry_time": entry_time, "exit_time": ts, "entry_price": entry_price,
                                "exit_price": price, "shares": shares, "pnl": pnl, "reason": "Stop Loss"})
                sell_markers.append({"time": ts, "price": price, "reason": "SL"})
                shares = 0; bars_held = 0; bars_since_exit = 0; last_exit_stoploss = True; peak_price = 0.0
                continue

            if bars_held >= MIN_HOLD_BARS and price <= trail_stop:
                pnl = (price - entry_price) * shares
                cash += shares * price
                label = "Trail+" if pnl >= 0 else "Trail-"
                trades.append({"entry_time": entry_time, "exit_time": ts, "entry_price": entry_price,
                                "exit_price": price, "shares": shares, "pnl": pnl, "reason": label})
                sell_markers.append({"time": ts, "price": price, "reason": label})
                shares = 0; bars_held = 0; bars_since_exit = 0; last_exit_stoploss = False; peak_price = 0.0
                continue

            if not in_profit:
                cooldown = bars_since_exit if last_exit_stoploss else 999
                sig = get_signal(window, bars_held=bars_held, bars_since_exit=cooldown, in_position=True)
                if sig == "sell":
                    pnl = (price - entry_price) * shares
                    cash += shares * price
                    trades.append({"entry_time": entry_time, "exit_time": ts, "entry_price": entry_price,
                                   "exit_price": price, "shares": shares, "pnl": pnl, "reason": "Signal"})
                    sell_markers.append({"time": ts, "price": price, "reason": "SIG"})
                    shares = 0; bars_held = 0; bars_since_exit = 0; last_exit_stoploss = False; peak_price = 0.0
        else:
            bars_since_exit += 1
            cooldown = bars_since_exit if last_exit_stoploss else 999
            sig = get_signal(window, bars_since_exit=cooldown, in_position=False)
            if sig == "buy" and cash > 0:
                shares_to_buy = int((cash * POSITION_SIZE_PCT) / price)
                if shares_to_buy > 0:
                    shares = shares_to_buy
                    entry_price = price
                    peak_price = price
                    entry_time = ts
                    cash -= shares * price
                    bars_held = 0
                    buy_markers.append({"time": ts, "price": price})

    if shares > 0:
        price = float(df.iloc[-1]["close"])
        pnl = (price - entry_price) * shares
        cash += shares * price
        trades.append({"entry_time": entry_time, "exit_time": df.iloc[-1].name,
                        "entry_price": entry_price, "exit_price": price,
                        "shares": shares, "pnl": pnl, "reason": "End"})

    return {"df": df, "trades": trades, "equity_curve": equity_curve,
            "buy_markers": buy_markers, "sell_markers": sell_markers,
            "trail_stops": trail_stops, "final_cash": cash, "starting_cash": starting_cash}


def compute_stats(result: dict) -> dict:
    trades = result["trades"]
    eq = result["equity_curve"]
    start = result["starting_cash"]
    end_val = eq[-1]["equity"] if eq else start
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "total_return_pct": 0, "total_pnl": 0,
                "max_drawdown_pct": 0, "avg_win": 0, "avg_loss": 0, "best_trade": 0, "worst_trade": 0}
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]
    pnls = [t["pnl"] for t in trades]
    equities = [e["equity"] for e in eq]
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        if e > peak: peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd: max_dd = dd
    return {
        "total_trades": len(trades),
        "win_rate": len(winners) / len(trades) * 100,
        "total_return_pct": (end_val - start) / start * 100,
        "total_pnl": sum(pnls),
        "max_drawdown_pct": max_dd * 100,
        "avg_win": sum(t["pnl"] for t in winners) / len(winners) if winners else 0,
        "avg_loss": sum(t["pnl"] for t in losers) / len(losers) if losers else 0,
        "best_trade": max(pnls),
        "worst_trade": min(pnls),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NVDA")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--cash", type=float, default=100_000)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    print(f"\n  Backtesting {symbol} | {args.days} days | ${args.cash:,.0f} starting cash")
    df = fetch_data(symbol, args.days)
    print(f"  {len(df)} hourly bars")
    result = run_backtest(df, args.cash)
    stats = compute_stats(result)
    print(f"\n  Trades:       {stats['total_trades']}")
    print(f"  Win rate:     {stats['win_rate']:.1f}%")
    print(f"  Return:       {stats['total_return_pct']:+.2f}%  (${stats['total_pnl']:+,.2f})")
    print(f"  Max drawdown: -{stats['max_drawdown_pct']:.1f}%")
    print(f"  Avg win:      ${stats['avg_win']:+,.2f}")
    print(f"  Avg loss:     ${stats['avg_loss']:+,.2f}")

    fig = go.Figure()
    df_ind = result["df"]
    fig.add_trace(go.Candlestick(x=df_ind.index, open=df_ind["open"], high=df_ind["high"],
                                  low=df_ind["low"], close=df_ind["close"], name="Price"))
    if result["buy_markers"]:
        fig.add_trace(go.Scatter(x=[m["time"] for m in result["buy_markers"]],
                                  y=[m["price"]*0.992 for m in result["buy_markers"]],
                                  mode="markers", marker=dict(symbol="triangle-up", size=13, color="#00E676"), name="Buy"))
    if result["sell_markers"]:
        fig.add_trace(go.Scatter(x=[m["time"] for m in result["sell_markers"]],
                                  y=[m["price"]*1.008 for m in result["sell_markers"]],
                                  mode="markers", marker=dict(symbol="triangle-down", size=13, color="#FF5252"), name="Sell"))
    fig.update_layout(template="plotly_dark", title=f"{symbol} Backtest - {stats['total_trades']} trades, {stats['win_rate']:.0f}% win rate, {stats['total_return_pct']:+.1f}% return")
    out_dir = Path(__file__).parent / "backtest_results"
    out_dir.mkdir(exist_ok=True)
    chart_path = out_dir / f"{symbol}_{args.days}d_chart.html"
    fig.write_html(str(chart_path))
    webbrowser.open(f"file://{chart_path.resolve()}")
    print(f"\n  Chart opened: {chart_path}")


if __name__ == "__main__":
    main()
