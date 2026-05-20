import json
import os
import time
import socket
import schedule
import pandas as pd
from datetime import datetime, timezone

import src.logger as logger
logger.setup()

from src.config import (
    WATCHLIST, RSI_OVERSOLD, MIN_HOLD_BARS, MAX_HOLD_BARS, TRAILING_STOP_PCT,
    OPTIONS_ENABLED, MAX_POSITIONS, ATR_HARD_MULT, ATR_TRAIL_MULT, ATR_TP_MULT,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, STOP_INTERVAL_MINUTES,
)
from src.broker import (
    get_clock, get_account, get_bars, get_current_price, get_position,
    place_buy, place_sell,
)
from src.strategy import compute_indicators, get_signal
from src.risk import (
    daily_loss_exceeded, total_daily_loss_exceeded, maybe_reset_daily_loss,
    record_loss, should_alert_circuit_breaker, mark_circuit_breaker_alerted,
    get_daily_start_value,
)
from src.options import buy_call, check_options_positions, get_open_option_symbols
from src.news import get_news_signal, check_spacex_ipo
from src.market_filters import run_all_filters
import src.state as state
import src.notify as notify
from src.dashboard import start_dashboard

log = logger.get(__name__)

_sym_state: dict[str, dict] = {}
_SYM_STATE_FILE = os.path.join(os.path.dirname(__file__), "sym_state.json")


def get_sym_state(symbol: str) -> dict:
    if symbol not in _sym_state:
        _sym_state[symbol] = {
            "peak_price": 0.0,
            "bars_held": 0,
            "bars_since_exit": 999,
            "last_exit_was_stoploss": False,
            "entry_atr": 0.0,
        }
    return _sym_state[symbol]


def _save_sym_state():
    try:
        with open(_SYM_STATE_FILE, "w") as f:
            json.dump(_sym_state, f)
    except Exception as e:
        log.error(f"Failed to save sym_state: {e}")


def _load_sym_state():
    global _sym_state
    try:
        with open(_SYM_STATE_FILE) as f:
            _sym_state = json.load(f)
        log.info(f"Loaded sym_state for: {', '.join(_sym_state.keys())}")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def _reconcile_positions():
    """On startup, seed sym_state from any positions already open on Alpaca."""
    try:
        from src.broker import get_all_positions
        positions = get_all_positions()
        for pos in positions:
            symbol = pos.symbol
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price) if pos.current_price else entry_price
            sym = get_sym_state(symbol)
            if sym["peak_price"] == 0.0:
                sym["peak_price"] = max(entry_price, current_price)
                sym["bars_held"] = 999
                log.info(f"Reconciled open position: {symbol} peak=${sym['peak_price']:.2f}")
        if positions:
            _save_sym_state()
    except Exception as e:
        log.error(f"Position reconciliation error: {e}")


def market_is_open() -> bool:
    return get_clock().is_open


def _circuit_breaker_active(portfolio_value: float) -> bool:
    if daily_loss_exceeded() or total_daily_loss_exceeded(portfolio_value):
        if should_alert_circuit_breaker():
            msg = (
                f"Circuit breaker fired. Daily loss limit reached. "
                f"Bot paused for today. Portfolio: ${portfolio_value:,.2f}"
            )
            notify.send_alert(msg)
            mark_circuit_breaker_alerted()
        log.warning("Circuit breaker active. No new trades today.")
        return True
    return False


def _get_stop_prices(sym: dict, entry_price: float) -> tuple[float, float, float]:
    entry_atr = sym.get("entry_atr") or 0.0
    if entry_atr > 0:
        hard_stop = entry_price - ATR_HARD_MULT * entry_atr
        trail_stop = sym["peak_price"] - ATR_TRAIL_MULT * entry_atr
        take_profit = entry_price + ATR_TP_MULT * entry_atr
    else:
        hard_stop = entry_price * (1 - STOP_LOSS_PCT)
        trail_stop = sym["peak_price"] * (1 - TRAILING_STOP_PCT)
        take_profit = entry_price * (1 + TAKE_PROFIT_PCT)
    return hard_stop, trail_stop, take_profit


def _exit_position(symbol: str, qty: int, current_price: float, unrealized_pnl: float,
                   action: str, is_stoploss: bool, use_market: bool = False) -> bool:
    if place_sell(symbol, qty, current_price, use_market=use_market):
        notify.send_trade(action, symbol, qty, current_price, unrealized_pnl)
        state.add_trade(symbol, action, current_price, qty, unrealized_pnl)
        state.clear_position(symbol)
        _sym_state[symbol] = {
            "peak_price": 0.0,
            "bars_held": 0,
            "bars_since_exit": 0,
            "last_exit_was_stoploss": is_stoploss,
            "entry_atr": 0.0,
        }
        _save_sym_state()
        return True
    return False


def check_stops():
    """
    Fast stop-check loop — runs every STOP_INTERVAL_MINUTES using real-time prices.
    Handles hard stops, trailing stops, and take-profit only. No signal scanning.
    """
    if not state.is_running():
        return
    if not market_is_open():
        return

    account = get_account()
    portfolio_value = float(account.portfolio_value)

    if _circuit_breaker_active(portfolio_value):
        return

    for symbol in list(WATCHLIST):
        position = get_position(symbol)
        if position is None:
            continue
        sym = get_sym_state(symbol)
        current_price = get_current_price(symbol)
        if current_price is None:
            continue

        entry_price = float(position.avg_entry_price)
        qty = int(position.qty)
        unrealized_pnl = (current_price - entry_price) * qty

        if current_price > sym["peak_price"]:
            sym["peak_price"] = current_price

        hard_stop, trail_stop, take_profit = _get_stop_prices(sym, entry_price)
        stop_type = "ATR" if sym.get("entry_atr") else "Fixed"

        if current_price >= take_profit:
            log.info(f"[{symbol}] TAKE PROFIT ${current_price:.2f} >= ${take_profit:.2f}")
            _exit_position(symbol, qty, current_price, unrealized_pnl, "SELL (Take Profit)", False)
            continue

        if current_price <= hard_stop:
            log.warning(f"[{symbol}] HARD STOP ${current_price:.2f} <= ${hard_stop:.2f} ({stop_type})")
            if _exit_position(symbol, qty, current_price, unrealized_pnl, "SELL (Stop Loss)", True, use_market=True):
                record_loss(abs(unrealized_pnl) if unrealized_pnl < 0 else 0)
            continue

        if sym["bars_held"] >= MIN_HOLD_BARS and current_price <= trail_stop:
            log.warning(f"[{symbol}] TRAILING STOP ${current_price:.2f} <= ${trail_stop:.2f} ({stop_type})")
            action = "SELL (Trail+)" if unrealized_pnl >= 0 else "SELL (Trail-)"
            _exit_position(symbol, qty, current_price, unrealized_pnl, action, False, use_market=True)
            continue


def _handle_ipo_approvals():
    ipo_ticker = check_spacex_ipo()
    if ipo_ticker:
        if ipo_ticker not in WATCHLIST and ipo_ticker not in state.get_pending_symbols():
            state.add_pending_symbol(ipo_ticker)
            notify.send_alert(
                f"IPO detected: {ipo_ticker} is now tradable.\n"
                f"Reply /approve {ipo_ticker} to add to watchlist."
            )
            log.info(f"IPO ticker {ipo_ticker} pending approval")

    for sym in list(state.get_approved_symbols()):
        if sym not in WATCHLIST:
            WATCHLIST.append(sym)
            notify.send_alert(f"{sym} added to watchlist after manual approval.")
            log.info(f"Approved symbol {sym} added to watchlist")


def run_bot():
    """
    Full hourly scan: new buy signals, signal-based sells, max-hold exits, options.
    Hard/trailing stops are handled by check_stops() running every minute.
    """
    if not state.is_running():
        log.info("Bot paused — skipping tick")
        return

    log.info(f"{'='*50}")
    log.info(f"Bot tick: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    if not market_is_open():
        log.info("Market is closed — skipping")
        return

    account = get_account()
    portfolio_value = float(account.portfolio_value)
    cash = float(account.cash)

    maybe_reset_daily_loss(portfolio_value)

    if _circuit_breaker_active(portfolio_value):
        return

    start_val = get_daily_start_value()
    daily_pnl = portfolio_value - start_val if start_val > 0 else 0.0
    state.update_portfolio(portfolio_value=portfolio_value, cash=cash, daily_pnl=daily_pnl)
    log.info(f"Portfolio: ${portfolio_value:,.2f} | Cash: ${cash:,.2f} | Day P&L: ${daily_pnl:+,.2f}")

    _handle_ipo_approvals()

    sell_signals: set[str] = set()
    _df_cache: dict[str, pd.DataFrame] = {}

    for symbol in list(WATCHLIST):
        try:
            bars = get_bars(symbol)
            df = compute_indicators(bars)
            _df_cache[symbol] = df
            sym = get_sym_state(symbol)
            position = get_position(symbol)
            if position is not None:
                cooldown = sym["bars_since_exit"] if sym["last_exit_was_stoploss"] else 999
                sig = get_signal(df, bars_held=sym["bars_held"], bars_since_exit=cooldown, in_position=True)
                if sig == "sell":
                    sell_signals.add(symbol)
        except Exception as e:
            log.error(f"[PRE-SCAN ERROR] {symbol}: {e}")
            state.add_error(f"{symbol}: {e}")

    closed_options = check_options_positions(sell_signals)
    for opt in closed_options:
        notify.send_trade(f"CLOSE CALL {opt['symbol']}", opt["underlying"], 1, 0.0, opt["pnl"])
        state.add_trade(opt["underlying"], "OPT EXIT", 0.0, 1, opt["pnl"])

    options_held = get_open_option_symbols()

    for symbol in list(WATCHLIST):
        log.info(f"--- [{symbol}] ---")
        sym = get_sym_state(symbol)
        try:
            df = _df_cache.get(symbol) or compute_indicators(get_bars(symbol))
            current_price = float(df.iloc[-1]["close"])
            rsi = float(df.iloc[-1]["rsi"])
            trend_ok = current_price > float(df.iloc[-1]["trend_sma"])
            news_score, news_text = get_news_signal(symbol)
            news_label = (
                f" | +{news_score} BULLISH" if news_score > 0 else
                f" | {news_score} BEARISH" if news_score < 0 else ""
            )
            if news_text:
                log.info(f"News: {news_text[:80]}")
            log.info(f"Price: ${current_price:.2f} | RSI: {rsi:.1f} | Uptrend: {trend_ok}{news_label}")

            position = get_position(symbol)

            if position is not None:
                entry_price = float(position.avg_entry_price)
                qty = int(position.qty)
                unrealized_pnl = float(position.unrealized_pl)
                sym["bars_held"] += 1

                if current_price > sym["peak_price"]:
                    sym["peak_price"] = current_price
                state.update_position(symbol, qty, entry_price, sym["peak_price"], current_price)

                hard_stop, trail_stop, take_profit = _get_stop_prices(sym, entry_price)
                stop_label = f"ATR×{ATR_HARD_MULT}" if sym.get("entry_atr") else "Fixed"
                log.info(
                    f"Entry: ${entry_price:.2f} | TP: ${take_profit:.2f} | "
                    f"HardStop: ${hard_stop:.2f} | Trail: ${trail_stop:.2f} "
                    f"({stop_label}) | PnL: ${unrealized_pnl:+.2f} | "
                    f"Bars held: {sym['bars_held']}/{MAX_HOLD_BARS}"
                )

                # Max hold duration exit
                if sym["bars_held"] >= MAX_HOLD_BARS:
                    log.info(f"MAX HOLD ({MAX_HOLD_BARS} bars) — forcing exit")
                    _exit_position(symbol, qty, current_price, unrealized_pnl,
                                   "SELL (Max Hold)", False)
                    continue

                # Signal-based sell (stops handled by check_stops loop)
                if not (current_price > entry_price * 1.005):
                    cooldown = sym["bars_since_exit"] if sym["last_exit_was_stoploss"] else 999
                    sig = get_signal(df, bars_held=sym["bars_held"], bars_since_exit=cooldown, in_position=True)
                    if sig == "sell":
                        log.info("Signal SELL triggered")
                        _exit_position(symbol, qty, current_price, unrealized_pnl,
                                       "SELL (Signal)", False)
                        continue

            else:
                state.clear_position(symbol)
                sym["bars_since_exit"] += 1
                cooldown = sym["bars_since_exit"] if sym["last_exit_was_stoploss"] else 999
                sig = get_signal(df, bars_since_exit=cooldown, in_position=False)

                if news_score <= -2:
                    sig = "hold"
                    log.info(f"News signal BLOCKED buy (score={news_score})")
                elif news_score >= 2 and sig == "hold" and rsi < RSI_OVERSOLD + 10:
                    sig = "buy"
                    log.info(f"News signal TRIGGERED buy (score={news_score})")

                filters = run_all_filters(symbol, df)
                if filters["reason"]:
                    log.info(f"[FILTER] {filters['reason']}")

                open_count = len(state.get()["positions"])
                log.info(f"Signal: {sig.upper()} | Open positions: {open_count}/{MAX_POSITIONS}")

                if sig == "buy":
                    if filters["block_buy"]:
                        log.info("Buy BLOCKED by market filter (VIX/volume/gap)")
                    elif open_count >= MAX_POSITIONS:
                        log.info(f"Buy BLOCKED — max positions ({MAX_POSITIONS}) reached")
                    else:
                        action = "BUY (News)" if news_score >= 2 else "BUY"
                        if place_buy(symbol, current_price, portfolio_value):
                            notify.send_trade(action, symbol, 0, current_price)
                            state.add_trade(symbol, action, current_price, 0)
                            entry_atr = (
                                float(df.iloc[-1]["atr"])
                                if "atr" in df.columns and not pd.isna(df.iloc[-1]["atr"])
                                else 0.0
                            )
                            sym.update({
                                "peak_price": current_price,
                                "bars_held": 0,
                                "last_exit_was_stoploss": False,
                                "entry_atr": entry_atr,
                            })
                        if OPTIONS_ENABLED and symbol not in options_held and not filters["block_options"]:
                            if buy_call(symbol, current_price, portfolio_value):
                                notify.send_trade(f"CALL {symbol}", symbol, 1, current_price)
                                state.add_trade(symbol, "BUY CALL", current_price, 1)
                                options_held.add(symbol)

        except Exception as e:
            msg = f"{symbol}: {e}"
            log.exception(f"Error processing {symbol}")
            state.add_error(msg)

    _save_sym_state()


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def main():
    log.info("=" * 50)
    log.info("Trading Bot Starting")
    log.info("=" * 50)
    log.info(f"Watching: {', '.join(WATCHLIST)}")

    _load_sym_state()
    _reconcile_positions()

    start_dashboard()
    local_ip = get_local_ip()
    log.info(f"Dashboard: http://{local_ip}:8080")

    notify.start_polling()
    notify.send(
        f"Trading Bot Started\n"
        f"Watching: {', '.join(WATCHLIST)}\n"
        f"Dashboard: http://{local_ip}:8080"
    )

    # Fast stop-check loop: every STOP_INTERVAL_MINUTES (default: 1 min)
    schedule.every(STOP_INTERVAL_MINUTES).minutes.do(check_stops)
    # Full signal scan: hourly
    schedule.every().hour.at(":01").do(run_bot)

    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    main()
