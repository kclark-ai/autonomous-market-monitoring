import pandas as pd
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
from src.strategy import compute_indicators

CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"]
CRYPTO_POSITION_SIZE_PCT = 0.10
CRYPTO_STOP_LOSS_PCT = 0.05
CRYPTO_TRAILING_STOP_PCT = 0.04
CRYPTO_RSI_OVERSOLD = 55
CRYPTO_RSI_OVERBOUGHT = 72
CRYPTO_MIN_HOLD_BARS = 2
CRYPTO_LOOKBACK_BARS = 200

_paper = "paper" in ALPACA_BASE_URL.lower()
_data_client: CryptoHistoricalDataClient | None = None
from src.broker import get_trading_client


def _get_data_client() -> CryptoHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    return _data_client


def get_crypto_bars(symbol: str) -> pd.DataFrame:
    start = datetime.now(timezone.utc) - timedelta(days=90)
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
        return get_trading_client().get_open_position(symbol.replace("/", ""))
    except Exception:
        return None


def crypto_buy(symbol: str, price: float, cash: float) -> bool:
    alloc = cash * CRYPTO_POSITION_SIZE_PCT
    if alloc <= 0:
        return False
    try:
        order = get_trading_client().submit_order(MarketOrderRequest(
            symbol=symbol.replace("/", ""), notional=round(alloc, 2),
            side=OrderSide.BUY, time_in_force=TimeInForce.GTC,
        ))
        print(f"  [CRYPTO BUY]  {symbol} ~${alloc:.2f} @ ${price:,.2f}")
        return True
    except Exception as e:
        print(f"  [CRYPTO ERR] Buy failed {symbol}: {e}")
        return False


def crypto_sell(symbol: str, qty: float, price: float) -> bool:
    try:
        get_trading_client().submit_order(MarketOrderRequest(
            symbol=symbol.replace("/", ""), qty=round(qty, 6),
            side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
        ))
        print(f"  [CRYPTO SELL] {symbol} {qty:.6f} @ ${price:,.2f}")
        return True
    except Exception as e:
        print(f"  [CRYPTO ERR] Sell failed {symbol}: {e}")
        return False


_crypto_state: dict[str, dict] = {}


def get_crypto_state(symbol: str) -> dict:
    if symbol not in _crypto_state:
        _crypto_state[symbol] = {"peak_price": 0.0, "bars_held": 0,
                                   "bars_since_exit": 999, "last_exit_was_stop": False}
    return _crypto_state[symbol]


def run_crypto_tick(cash: float) -> list[str]:
    actions = []
    for symbol in CRYPTO_SYMBOLS:
        sym = get_crypto_state(symbol)
        print(f"\n  [CRYPTO {symbol}]")
        try:
            df = compute_indicators(get_crypto_bars(symbol))
            current_price = float(df.iloc[-1]["close"])
            rsi = float(df.iloc[-1]["rsi"])
            print(f"    Price: ${current_price:,.2f} | RSI: {rsi:.1f}")
            position = get_crypto_position(symbol)
            if position:
                entry_price = float(position.avg_entry_price)
                qty = float(position.qty)
                unrealized_pnl = float(position.unrealized_pl)
                sym["bars_held"] += 1
                if current_price > sym["peak_price"]:
                    sym["peak_price"] = current_price
                if current_price <= entry_price * (1 - CRYPTO_STOP_LOSS_PCT):
                    if crypto_sell(symbol, qty, current_price):
                        sym.update({"peak_price": 0.0, "bars_held": 0, "bars_since_exit": 0, "last_exit_was_stop": True})
                        actions.append(f"SELL SL {symbol}")
                elif sym["bars_held"] >= CRYPTO_MIN_HOLD_BARS and current_price <= sym["peak_price"] * (1 - CRYPTO_TRAILING_STOP_PCT):
                    if crypto_sell(symbol, qty, current_price):
                        sym.update({"peak_price": 0.0, "bars_held": 0, "bars_since_exit": 0, "last_exit_was_stop": False})
                        actions.append(f"SELL TRAIL {symbol}")
            else:
                sym["bars_since_exit"] += 1
                if rsi < CRYPTO_RSI_OVERSOLD and current_price > float(df.iloc[-1]["trend_sma"]):
                    if crypto_buy(symbol, current_price, cash):
                        sym.update({"peak_price": current_price, "bars_held": 0, "last_exit_was_stop": False})
                        actions.append(f"BUY {symbol}")
        except Exception as e:
            print(f"    ERROR {symbol}: {e}")
    return actions
