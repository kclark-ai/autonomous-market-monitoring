import pandas as pd
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetAssetsRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from src.config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL,
    BAR_TIMEFRAME, LOOKBACK_BARS, POSITION_SIZE_PCT
)

_paper = "paper" in ALPACA_BASE_URL.lower()
_trading: TradingClient | None = None
_data: StockHistoricalDataClient | None = None


def get_trading_client() -> TradingClient:
    global _trading
    if _trading is None:
        _trading = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=_paper)
    return _trading


def get_data_client() -> StockHistoricalDataClient:
    global _data
    if _data is None:
        _data = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    return _data


def get_client() -> TradingClient:
    return get_trading_client()


_TF_MAP = {"1Hour": TimeFrame.Hour, "1Day": TimeFrame.Day, "1Min": TimeFrame.Minute}


def get_bars(symbol: str) -> pd.DataFrame:
    tf = _TF_MAP.get(BAR_TIMEFRAME, TimeFrame.Hour)
    start = datetime.now(timezone.utc) - timedelta(days=90)
    bars = get_data_client().get_stock_bars(StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        feed="iex",
    ))
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "volume"]]
    return df.tail(LOOKBACK_BARS)


def get_account():
    return get_trading_client().get_account()


def get_clock():
    return get_trading_client().get_clock()


def get_position(symbol: str):
    try:
        result = get_trading_client().get_open_position(symbol)
        if result is None:
            return None
        if hasattr(result, 'empty') and result.empty:
            return None
        return result
    except Exception:
        return None


def get_asset(symbol: str):
    try:
        return get_trading_client().get_asset(symbol)
    except Exception:
        return None


def get_all_positions():
    return get_trading_client().get_all_positions()


def place_buy(symbol: str, price: float) -> bool:
    cash = float(get_account().cash)
    alloc = cash * POSITION_SIZE_PCT
    qty = int(alloc // price)
    if qty < 1:
        print(f"  [SKIP] {symbol}: insufficient cash (${cash:.2f}) for price ${price:.2f}")
        return False
    try:
        order = get_trading_client().submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        ))
        print(f"  [BUY]  {symbol} x{qty} @ ~${price:.2f} | order_id={order.id}")
        return True
    except Exception as e:
        print(f"  [ERR]  Buy failed for {symbol}: {e}")
        return False


def place_sell(symbol: str, qty: int, price: float) -> bool:
    try:
        order = get_trading_client().submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        ))
        print(f"  [SELL] {symbol} x{qty} @ ~${price:.2f} | order_id={order.id}")
        return True
    except Exception as e:
        print(f"  [ERR]  Sell failed for {symbol}: {e}")
        return False


def get_news(symbol: str, limit: int = 5) -> list:
    try:
        return get_trading_client().get_news(symbol, limit=limit)
    except Exception:
        return []
