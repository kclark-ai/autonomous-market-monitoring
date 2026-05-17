import time
import schedule
import socket
from datetime import datetime, timezone

from src.config import WATCHLIST, RSI_OVERSOLD, MIN_HOLD_BARS, TRAILING_STOP_PCT
from src.broker import get_clock, get_account, get_bars, get_position, place_buy, place_sell
from src.strategy import compute_indicators, get_signal
from src.risk import daily_loss_exceeded, maybe_reset_daily_loss, record_loss, reset_daily_loss, should_stop_loss, should_trailing_stop
from src.options import buy_call, check_options_positions, get_open_option_symbols
from src.news import get_news_signal, check_spacex_ipo
from src.market_filters import run_all_filters
import src.state as state
import src.notify as notify
from src.dashboard import start_dashboard

_sym_state: dict[str, dict] = {}


def get_sym_state(symbol: str) -> dict:
    if symbol not in _sym_state:
        _sym_state[symbol] = {"peak_price": 0.0, "bars_held": 0,
                               "bars_since_exit": 999, "last_exit_was_stoploss": False}
    return _sym_state[symbol]


def market_is_open() -> bool:
    return get_clock().is_open


def run_bot():
    if not state.is_running():
        print("  [BOT] Paused. Skipping tick.")
        return

    print(f"\n{'='*50}")
    print(f"  Bot tick: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    if not market_is_open():
        print("  Market is closed. Skipping.")
        return

    account = get_account()
    portfolio_value = float(account.portfolio_value)
    cash = float(account.cash)

    maybe_reset_daily_loss(portfolio_value)

    if daily_loss_exceeded():
        msg = "Daily loss limit reached. No new trades today."
        print(f"  {msg}")
        notify.send_alert(msg)
        return

    state.update_portfolio(portfolio_value=portfolio_value, cash=cash, daily_pnl=0.0)
    print(f"  Portfolio: ${portfolio_value:,.2f} | Cash: ${cash:,.2f}")

    ipo_ticker = check_spacex_ipo()
    if ipo_ticker and ipo_ticker not in WATCHLIST:
        WATCHLIST.append(ipo_ticker)
        notify.send_alert(f"SpaceX IPO detected! Added {ipo_ticker} to watchlist.")

    sell_signals: set[str] = set()
    _signal_cache: dict[str, str] = {}

    for symbol in WATCHLIST:
        try:
            bars = get_bars(symbol)
            df = compute_indicators(bars)
            sym = get_sym_state(symbol)
            position = get_position(symbol)
            if position is not None:
                cooldown = sym["bars_since_exit"] if sym["last_exit_was_stoploss"] else 999
                sig = get_signal(df, bars_held=sym["bars_held"], bars_since_exit=cooldown, in_position=True)
                if sig == "sell":
                    sell_signals.add(symbol)
            _signal_cache[symbol] = df
        except Exception:
            pass

    closed_options = check_options_positions(sell_signals)
    for opt in closed_options:
        notify.send_trade(f"CLOSE CALL {opt['symbol']}", opt["underlying"], 1, 0.0, opt["pnl"])
        state.add_trade(opt["underlying"], "OPT EXIT", 0.0, 1, opt["pnl"])

    options_held = get_open_option_symbols()

    for symbol in WATCHLIST:
        print(f"\n  [{symbol}]")
        sym = get_sym_state(symbol)
        try:
            cached = _signal_cache.get(symbol)
            df = cached if cached is not None else compute_indicators(get_bars(symbol))
            current_price = float(df.iloc[-1]["close"])
            rsi = float(df.iloc[-1]["rsi"])
            trend_ok = current_price > float(df.iloc[-1]["trend_sma"])
            news_score, news_text = get_news_signal(symbol)
            news_label = f" | +{news_score} BULLISH" if news_score > 0 else (f" | {news_score} BEARISH" if news_score < 0 else "")
            if news_text:
                print(f"    News: {news_text[:80]}")
            print(f"    Price: ${current_price:.2f} | RSI: {rsi:.1f} | Uptrend: {trend_ok}{news_label}")
            position = get_position(symbol)

            if position is not None:
                entry_price = float(position.avg_entry_price)
                qty = int(position.qty)
                unrealized_pnl = float(position.unrealized_pl)
                sym["bars_held"] += 1
                if current_price > sym["peak_price"]:
                    sym["peak_price"] = current_price
                state.update_position(symbol, qty, entry_price, sym["peak_price"], current_price)
                trailing_stop_price = sym["peak_price"] * (1 - TRAILING_STOP_PCT)
                print(f"    Entry: ${entry_price:.2f} | Peak: ${sym['peak_price']:.2f} | Trail: ${trailing_stop_price:.2f} | PnL: ${unrealized_pnl:+.2f}")

                if should_stop_loss(entry_price, current_price):
                    print(f"    HARD STOP LOSS triggered")
                    if place_sell(symbol, qty, current_price):
                        record_loss(abs(unrealized_pnl) if unrealized_pnl < 0 else 0)
                        notify.send_trade("SELL (Stop Loss)", symbol, qty, current_price, unrealized_pnl)
                        state.add_trade(symbol, "SELL (SL)", current_price, qty, unrealized_pnl)
                        state.clear_position(symbol)
                        sym.update({"peak_price": 0.0, "bars_held": 0, "bars_since_exit": 0, "last_exit_was_stoploss": True})
                    continue

                if sym["bars_held"] >= MIN_HOLD_BARS and should_trailing_stop(sym["peak_price"], current_price):
                    print(f"    TRAILING STOP triggered")
                    if place_sell(symbol, qty, current_price):
                        action = "SELL (Trail+)" if unrealized_pnl >= 0 else "SELL (Trail-)"
                        notify.send_trade(action, symbol, qty, current_price, unrealized_pnl)
                        state.add_trade(symbol, action, current_price, qty, unrealized_pnl)
                        state.clear_position(symbol)
                        sym.update({"peak_price": 0.0, "bars_held": 0, "bars_since_exit": 0, "last_exit_was_stoploss": False})
                    continue

                if not (current_price > entry_price * 1.005):
                    cooldown = sym["bars_since_exit"] if sym["last_exit_was_stoploss"] else 999
                    sig = get_signal(df, bars_held=sym["bars_held"], bars_since_exit=cooldown, in_position=True)
                    if sig == "sell":
                        if place_sell(symbol, qty, current_price):
                            notify.send_trade("SELL (Signal)", symbol, qty, current_price, unrealized_pnl)
                            state.add_trade(symbol, "SELL (SIG)", current_price, qty, unrealized_pnl)
                            state.clear_position(symbol)
                            sym.update({"peak_price": 0.0, "bars_held": 0, "bars_since_exit": 0, "last_exit_was_stoploss": False})
            else:
                state.clear_position(symbol)
                sym["bars_since_exit"] += 1
                cooldown = sym["bars_since_exit"] if sym["last_exit_was_stoploss"] else 999
                sig = get_signal(df, bars_since_exit=cooldown, in_position=False)

                if news_score <= -2:
                    sig = "hold"
                    print(f"    News signal BLOCKED buy (score={news_score})")
                elif news_score >= 2 and sig == "hold" and rsi < RSI_OVERSOLD + 10:
                    sig = "buy"
                    print(f"    News signal TRIGGERED buy (score={news_score})")

                filters = run_all_filters(symbol, df)
                if filters["reason"]:
                    print(f"    [FILTER] {filters['reason']}")

                print(f"    Signal: {sig.upper()}")
                if sig == "buy":
                    if filters["block_buy"]:
                        print(f"    Buy BLOCKED by market filter (VIX/volume)")
                    else:
                        action = "BUY (News)" if news_score >= 2 else "BUY"
                        if place_buy(symbol, current_price):
                            notify.send_trade(action, symbol, 0, current_price)
                            state.add_trade(symbol, action, current_price, 0)
                            sym.update({"peak_price": current_price, "bars_held": 0, "last_exit_was_stoploss": False})
                        if symbol not in options_held and not filters["block_options"]:
                            if buy_call(symbol, current_price, portfolio_value):
                                notify.send_trade(f"CALL {symbol}", symbol, 1, current_price)
                                state.add_trade(symbol, "BUY CALL", current_price, 1)
                                options_held.add(symbol)

        except Exception as e:
            msg = f"{symbol}: {e}"
            print(f"    ERROR {msg}")
            state.add_error(msg)


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
    print("\n" + "="*50)
    print("  Trading Bot Starting")
    print("="*50)
    print(f"  Watching: {', '.join(WATCHLIST)}\n")

    start_dashboard()
    local_ip = get_local_ip()
    print(f"\n  Dashboard: http://{local_ip}:5000")

    notify.start_polling()
    notify.send(f"Trading Bot Started\nWatching: {', '.join(WATCHLIST)}\nDashboard: http://{local_ip}:5000")

    try:
        run_bot()
    except Exception as e:
        print(f"  [BOT] First tick failed: {e}")

    schedule.every().hour.do(run_bot)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
