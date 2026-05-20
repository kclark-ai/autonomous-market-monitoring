"""
Compares fixed-percentage stops vs ATR-based dynamic stops across the full watchlist.
Runs 365 days of hourly data per symbol and prints a side-by-side results table.
"""
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from src.config import (
    STOP_LOSS_PCT, TRAILING_STOP_PCT, MIN_HOLD_BARS, COOLDOWN_BARS,
    POSITION_SIZE_PCT, WATCHLIST, ATR_HARD_MULT, ATR_TRAIL_MULT,
)
from src.strategy import compute_indicators, get_signal

DAYS = 365
STARTING_CASH = 10_000


def fetch_data(symbol: str) -> pd.DataFrame:
    end = datetime.today()
    start = end - timedelta(days=DAYS + 90)
    df = yf.download(symbol, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                     interval="1h", auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    cutoff = end - timedelta(days=DAYS)
    return df[df.index >= pd.Timestamp(cutoff, tz=df.index.tz)]


def run_backtest(df: pd.DataFrame, use_atr: bool) -> dict:
    df = compute_indicators(df.copy())
    cash = STARTING_CASH
    shares = 0
    entry_price = 0.0
    entry_atr = 0.0
    peak_price = 0.0
    bars_held = 0
    bars_since_exit = 999
    last_exit_stoploss = False
    trades = []
    equity_curve = []

    for i in range(2, len(df)):
        window = df.iloc[:i + 1]
        row = df.iloc[i]
        price = float(row["close"])
        atr = float(row["atr"]) if not pd.isna(row["atr"]) else price * 0.01
        in_position = shares > 0
        portfolio_value = cash + shares * price
        equity_curve.append(portfolio_value)

        if in_position:
            bars_held += 1
            if price > peak_price:
                peak_price = price

            if use_atr:
                hard_stop = entry_price - ATR_HARD_MULT * entry_atr
                trail_stop = peak_price - ATR_TRAIL_MULT * entry_atr
            else:
                hard_stop = entry_price * (1 - STOP_LOSS_PCT)
                trail_stop = peak_price * (1 - TRAILING_STOP_PCT)

            if price <= hard_stop:
                pnl = (price - entry_price) * shares
                cash += shares * price
                trades.append({"pnl": pnl, "reason": "HardStop",
                                "hold_bars": bars_held, "entry": entry_price, "exit": price})
                shares = 0; bars_held = 0; bars_since_exit = 0
                last_exit_stoploss = True; peak_price = 0.0
                continue

            if bars_held >= MIN_HOLD_BARS and price <= trail_stop:
                pnl = (price - entry_price) * shares
                cash += shares * price
                trades.append({"pnl": pnl, "reason": "Trail+" if pnl >= 0 else "Trail-",
                                "hold_bars": bars_held, "entry": entry_price, "exit": price})
                shares = 0; bars_held = 0; bars_since_exit = 0
                last_exit_stoploss = False; peak_price = 0.0
                continue

            if not (price > entry_price * 1.005):
                cooldown = bars_since_exit if last_exit_stoploss else 999
                sig = get_signal(window, bars_held=bars_held, bars_since_exit=cooldown, in_position=True)
                if sig == "sell":
                    pnl = (price - entry_price) * shares
                    cash += shares * price
                    trades.append({"pnl": pnl, "reason": "Signal",
                                   "hold_bars": bars_held, "entry": entry_price, "exit": price})
                    shares = 0; bars_held = 0; bars_since_exit = 0
                    last_exit_stoploss = False; peak_price = 0.0
        else:
            bars_since_exit += 1
            cooldown = bars_since_exit if last_exit_stoploss else 999
            sig = get_signal(window, bars_since_exit=cooldown, in_position=False)
            if sig == "buy" and cash > 0:
                qty = int((cash * POSITION_SIZE_PCT) / price)
                if qty > 0:
                    shares = qty
                    entry_price = price
                    entry_atr = atr
                    peak_price = price
                    cash -= shares * price
                    bars_held = 0

    if shares > 0:
        price = float(df.iloc[-1]["close"])
        pnl = (price - entry_price) * shares
        cash += shares * price
        trades.append({"pnl": pnl, "reason": "End",
                       "hold_bars": bars_held, "entry": entry_price, "exit": price})

    return {"trades": trades, "equity_curve": equity_curve, "final_cash": cash}


def compute_stats(result: dict) -> dict:
    trades = result["trades"]
    eq = result["equity_curve"]
    if not trades or not eq:
        return {"trades": 0, "win_rate": 0, "ret": 0, "max_dd": 0,
                "avg_win": 0, "avg_loss": 0, "profit_factor": 0}
    winners = [t for t in trades if t["pnl"] > 0]
    losers  = [t for t in trades if t["pnl"] <= 0]
    gross_win  = sum(t["pnl"] for t in winners) if winners else 0
    gross_loss = abs(sum(t["pnl"] for t in losers)) if losers else 0
    peak = eq[0]
    max_dd = 0.0
    for e in eq:
        if e > peak: peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd: max_dd = dd
    ret = (eq[-1] - STARTING_CASH) / STARTING_CASH * 100
    return {
        "trades": len(trades),
        "win_rate": len(winners) / len(trades) * 100,
        "ret": ret,
        "max_dd": max_dd * 100,
        "avg_win": gross_win / len(winners) if winners else 0,
        "avg_loss": -gross_loss / len(losers) if losers else 0,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else 0,
    }


def main():
    print(f"\n{'='*74}")
    print(f"  ATR vs Fixed Stop Comparison  |  {DAYS}d hourly  |  ${STARTING_CASH:,} per symbol")
    print(f"  Fixed:  hard={STOP_LOSS_PCT*100:.1f}%  trail={TRAILING_STOP_PCT*100:.1f}%")
    print(f"  ATR:    hard={ATR_HARD_MULT}x ATR  trail={ATR_TRAIL_MULT}x ATR")
    print(f"{'='*74}\n")

    header = f"{'Symbol':<6}  {'Fix Ret':>8}  {'ATR Ret':>8}  {'Fix WR':>7}  {'ATR WR':>7}  {'Fix DD':>7}  {'ATR DD':>7}  {'Fix PF':>7}  {'ATR PF':>7}  {'Winner':>7}"
    print(header)
    print("-" * len(header))

    agg_fixed = {"ret": 0, "wins": 0, "dd": 0, "pf": 0, "count": 0}
    agg_atr   = {"ret": 0, "wins": 0, "dd": 0, "pf": 0, "count": 0}
    atr_wins = 0

    for sym in WATCHLIST:
        print(f"  Fetching {sym}...", end="", flush=True)
        df = fetch_data(sym)
        if df.empty or len(df) < 60:
            print(f" skipped (no data)")
            continue

        r_fixed = run_backtest(df, use_atr=False)
        r_atr   = run_backtest(df, use_atr=True)
        s_fixed = compute_stats(r_fixed)
        s_atr   = compute_stats(r_atr)

        winner = "ATR" if s_atr["ret"] > s_fixed["ret"] else "Fixed"
        if winner == "ATR":
            atr_wins += 1

        for k, v in [("ret", s_fixed["ret"]), ("wins", s_fixed["win_rate"]),
                     ("dd", s_fixed["max_dd"]), ("pf", s_fixed["profit_factor"])]:
            agg_fixed[k] += v
        for k, v in [("ret", s_atr["ret"]), ("wins", s_atr["win_rate"]),
                     ("dd", s_atr["max_dd"]), ("pf", s_atr["profit_factor"])]:
            agg_atr[k] += v
        agg_fixed["count"] += 1
        agg_atr["count"] += 1

        print(f"\r{sym:<6}  {s_fixed['ret']:>+7.1f}%  {s_atr['ret']:>+7.1f}%  "
              f"{s_fixed['win_rate']:>6.0f}%  {s_atr['win_rate']:>6.0f}%  "
              f"{s_fixed['max_dd']:>6.1f}%  {s_atr['max_dd']:>6.1f}%  "
              f"{s_fixed['profit_factor']:>7.2f}  {s_atr['profit_factor']:>7.2f}  "
              f"{'>>> ' + winner:<7}")

    n = agg_fixed["count"]
    if n > 0:
        print("-" * len(header))
        print(f"{'AVG':<6}  {agg_fixed['ret']/n:>+7.1f}%  {agg_atr['ret']/n:>+7.1f}%  "
              f"{agg_fixed['wins']/n:>6.0f}%  {agg_atr['wins']/n:>6.0f}%  "
              f"{agg_fixed['dd']/n:>6.1f}%  {agg_atr['dd']/n:>6.1f}%  "
              f"{agg_fixed['pf']/n:>7.2f}  {agg_atr['pf']/n:>7.2f}  "
              f"ATR {atr_wins}/{n}")
        print(f"\n  ATR wins on return: {atr_wins}/{n} symbols")
        verdict = "IMPLEMENT ATR STOPS" if atr_wins > n / 2 else "KEEP FIXED STOPS"
        print(f"  Verdict: {verdict}\n")


if __name__ == "__main__":
    main()
