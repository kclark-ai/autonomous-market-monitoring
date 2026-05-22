"""
Crypto trading module — BTC/USD, ETH/USD, SOL/USD, AVAX/USD.
Runs 24/7 on its own hourly schedule (crypto never closes).
Uses ATR-based stops matching the equity strategy.
"""
import json
import os
import pandas as pd
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
from src.strategy import compute_indicators
import src.state as state
import src.notify as notify
import src.logger as logger

log = logger.get(__name__)

CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"]
CRYPTO_POSITION_SIZE_PCT = 0.05      # 5% of cash per crypto position
CRYPTO_ATR_HARD_MULT    = 2.5        # hard stop: entry - 2.5×ATR
CRYPTO_ATR_TRAIL_MULT   = 2.0        # trailing stop: peak - 2.0×ATR
CRYPTO_ATR_TP_MULT      = 4.0        # take profit: entry + 4.0×ATR
CRYPTO_STOP_LOSS_PCT    = 0.05       # fallback if ATR unavailable
CRYPTO_TRAILING_STOP_PCT = 0.04
CRYPTO_TAKE_PROFIT_PCT  = 0.10
CRYPTO_RSI_OVERSOLD     = 40
CRYPTO_RSI_OVERBOUGHT   = 70
CRYPTO_MIN_HOLD_BARS    = 2
CRYPTO_MAX_HOLD_BARS    = 48         # 48 hours max hold
CRYPTO_LOOKBACK_BARS    = 200

_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "crypto_state.json")
_data_client: CryptoHistoricalDataClient | None = None
_crypto_state: dict[str, dict] = {}


# ── State persistence ────────────────────────────────────────────────────────

def _get_default_sym_state() -> dict:
    return {
        "peak_price": 0.0,
        "bars_held": 0,
        "bars_since_exit": 999,
        "last_exit_was_stop": False,
        "entry_atr": 0.0,
        "entry_price": 0.0,
    }


def get_crypto_state(symbol: str) -> dict:
    if symbol not in _crypto_state:
        _crypto_state[symbol] = _get_default_sym_state()
    return _crypto_state[symbol]


def _save_state():
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(_crypto_state, f)
    except Exception as e:
        log.error(f"Failed to save crypto state: {e}")


def load_state():
    global _crypto_state
    try:
        with open(_STATE_FILE) as f:
            _crypto_state = json.load(f)
        log.info(f"Loaded crypto state for: {', '.join(_crypto_state.keys())}")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


# ── Data + broker ────────────────────────────────────────────────────────────

def _get_data_client() -> CryptoHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    return _data_client


def get_crypto_bars(symbol: str) -> pd.DataFrame:
    start = datetime.now(timezone.utc) - timedelta(days=30)
    bars = _get_data_client().get_crypto_bars(CryptoBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Hour, start=start,
    ))
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["open", "high", "low", "close", "volume"]].tail(CRYPTO_LOOKBACK_BARS)


def get_crypto_position(symbol: str):
    try:
        from src.broker import get_trading_client
        return get_trading_client().get_open_position(symbol.replace("/", ""))
    except Exception:
        return None


def _get_stop_prices(sym: dict, entry_price: float) -> tuple[float, float, float]:
    atr = sym.get("entry_atr") or 0.0
    if atr > 0:
        hard_stop   = entry_price - CRYPTO_ATR_HARD_MULT  * atr
        trail_stop  = sym["peak_price"] - CRYPTO_ATR_TRAIL_MULT * atr
        take_profit = entry_price + CRYPTO_ATR_TP_MULT * atr
    else:
        hard_stop   = entry_price * (1 - CRYPTO_STOP_LOSS_PCT)
        trail_stop  = sym["peak_price"] * (1 - CRYPTO_TRAILING_STOP_PCT)
        take_profit = entry_price * (1 + CRYPTO_TAKE_PROFIT_PCT)
    return hard_stop, trail_stop, take_profit


def _crypto_buy(symbol: str, price: float, cash: float, atr: float) -> bool:
    alloc = cash * CRYPTO_POSITION_SIZE_PCT
    if alloc < 1:
        return False
    try:
        from src.broker import get_trading_client
        get_trading_client().submit_order(MarketOrderRequest(
            symbol=symbol.replace("/", ""),
            notional=round(alloc, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
        ))
        log.info(f"[{symbol}] BUY ~${alloc:.2f} @ ${price:,.2f} | ATR={atr:.2f}")
        return True
    except Exception as e:
        log.error(f"[{symbol}] Buy failed: {e}")
        return False


def _crypto_sell(symbol: str, qty: float, price: float, reason: str) -> bool:
    try:
        from src.broker import get_trading_client
        get_trading_client().submit_order(MarketOrderRequest(
            symbol=symbol.replace("/", ""),
            qty=round(qty, 6),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
        ))
        log.info(f"[{symbol}] SELL {qty:.6f} @ ${price:,.2f} ({reason})")
        return True
    except Exception as e:
        log.error(f"[{symbol}] Sell failed: {e}")
        return False


def _exit(symbol: str, qty: float, price: float, entry_price: float,
          reason: str, is_stop: bool):
    sym = get_crypto_state(symbol)
    unrealized_pnl = (price - entry_price) * qty
    if _crypto_sell(symbol, qty, price, reason):
        notify.send_trade(reason, symbol, qty, price, unrealized_pnl)
        state.add_trade(symbol, reason, price, int(qty), unrealized_pnl)
        state.clear_position(symbol)
        _crypto_state[symbol] = _get_default_sym_state()
        _crypto_state[symbol]["last_exit_was_stop"] = is_stop
        _save_state()


# ── Main tick ────────────────────────────────────────────────────────────────

def run_crypto_tick(cash: float):
    """Hourly crypto scan — runs 24/7 regardless of equity market hours."""
    log.info("── Crypto tick ──")
    for symbol in CRYPTO_SYMBOLS:
        sym = get_crypto_state(symbol)
        log.info(f"--- [{symbol}] ---")
        try:
            df = compute_indicators(get_crypto_bars(symbol))
            row = df.iloc[-1]
            price = float(row["close"])
            atr   = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else 0.0
            rsi   = float(row["rsi"]) if "rsi" in row and not pd.isna(row["rsi"]) else 50.0
            trend_ok = price > float(row["trend_sma"]) if "trend_sma" in row else True

            position = get_crypto_position(symbol)

            if position is not None:
                entry_price = float(position.avg_entry_price)
                qty         = float(position.qty)
                sym["bars_held"] += 1

                if price > sym["peak_price"]:
                    sym["peak_price"] = price

                hard_stop, trail_stop, take_profit = _get_stop_prices(sym, entry_price)
                stop_type = "ATR" if sym.get("entry_atr") else "Fixed"
                unrealized_pnl = (price - entry_price) * qty

                log.info(
                    f"Entry: ${entry_price:,.2f} | Now: ${price:,.2f} | "
                    f"TP: ${take_profit:,.2f} | Stop: ${hard_stop:,.2f} "
                    f"({stop_type}) | PnL: ${unrealized_pnl:+.2f} | "
                    f"Bars: {sym['bars_held']}/{CRYPTO_MAX_HOLD_BARS}"
                )

                state.update_position(
                    symbol, int(qty), entry_price, sym["peak_price"], price,
                    hard_stop=hard_stop, trail_stop=trail_stop,
                    take_profit=take_profit, entry_atr=sym.get("entry_atr", 0.0),
                )

                # Exits — priority order
                if sym["bars_held"] >= CRYPTO_MAX_HOLD_BARS:
                    log.info(f"[{symbol}] MAX HOLD — forcing exit")
                    _exit(symbol, qty, price, entry_price, "SELL (Max Hold)", False)
                    continue

                if price >= take_profit:
                    log.info(f"[{symbol}] TAKE PROFIT")
                    _exit(symbol, qty, price, entry_price, "SELL (Take Profit)", False)
                    continue

                if price <= hard_stop:
                    log.warning(f"[{symbol}] HARD STOP")
                    _exit(symbol, qty, price, entry_price, "SELL (Stop Loss)", True)
                    continue

                if sym["bars_held"] >= CRYPTO_MIN_HOLD_BARS and price <= trail_stop:
                    action = "SELL (Trail+)" if unrealized_pnl >= 0 else "SELL (Trail-)"
                    log.warning(f"[{symbol}] TRAILING STOP → {action}")
                    _exit(symbol, qty, price, entry_price, action, False)
                    continue

            else:
                state.clear_position(symbol)
                sym["bars_since_exit"] += 1

                log.info(f"Price: ${price:,.2f} | RSI: {rsi:.1f} | Uptrend: {trend_ok}")

                # Entry: RSI oversold dip OR trend-following momentum
                sma_s = float(df.iloc[-1]["sma_short"]) if "sma_short" in df.columns else 0
                sma_l = float(df.iloc[-1]["sma_long"])  if "sma_long"  in df.columns else 0
                rsi_dip = rsi < CRYPTO_RSI_OVERSOLD and trend_ok
                trend_momentum = (
                    trend_ok
                    and 45 <= rsi < CRYPTO_RSI_OVERBOUGHT
                    and sma_s > sma_l
                )
                if (rsi_dip or trend_momentum) and cash > 0:
                    if _crypto_buy(symbol, price, cash, atr):
                        notify.send_trade("BUY (Crypto)", symbol, 0, price)
                        state.add_trade(symbol, "BUY (Crypto)", price, 0)
                        sym.update({
                            "peak_price": price,
                            "bars_held": 0,
                            "last_exit_was_stop": False,
                            "entry_atr": atr,
                            "entry_price": price,
                        })

        except Exception as e:
            log.exception(f"Error processing {symbol}")
            state.add_error(f"{symbol}: {e}")

    _save_state()
