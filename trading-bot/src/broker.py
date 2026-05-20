import pandas as pd
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame

from src.config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL,
    BAR_TIMEFRAME, LOOKBACK_BARS, POSITION_SIZE_PCT,
    BUY_LIMIT_TOLERANCE, SELL_LIMIT_TOLERANCE,
)
import src.logger as logger

log = logger.get(__name__)
trade_log = logger.get("trades")

_paper = "paper" in ALPACA_BASE_URL.lower()
_trading: TradingClient | None = None
_data: StockHistoricalDataClient | None = None
_TF_MAP = {"1Hour": TimeFrame.Hour, "1Day": TimeFrame.Day, "1Min": TimeFrame.Minute}


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


def get_current_price(symbol: str) -> float | None:
    try:
        resp = get_data_client().get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        )
        return float(resp[symbol].price)
    except Exception as e:
        log.warning(f"Latest price fetch failed for {symbol}: {e}")
        return None


def get_open_orders(symbol: str) -> list:
    try:
        orders = get_trading_client().get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN)
        )
        return [o for o in orders if o.symbol == symbol]
    except Exception as e:
        log.warning(f"Get open orders failed for {symbol}: {e}")
        return []


def has_pending_buy(symbol: str) -> bool:
    return any(o.side == OrderSide.BUY for o in get_open_orders(symbol))


def has_pending_sell(symbol: str) -> bool:
    return any(o.side == OrderSide.SELL for o in get_open_orders(symbol))


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


def place_buy(symbol: str, price: float, portfolio_value: float | None = None) -> bool:
    if has_pending_buy(symbol):
        log.info(f"[SKIP] {symbol}: pending buy order already exists")
        return False
    account = get_account()
    cash = float(account.cash)
    pv = portfolio_value if portfolio_value is not None else float(account.portfolio_value)
    alloc = min(pv * POSITION_SIZE_PCT, cash)
    qty = int(alloc // price)
    if qty < 1:
        log.info(f"[SKIP] {symbol}: insufficient cash (${cash:.2f}) for price ${price:.2f}")
        return False
    limit_price = round(price * (1 + BUY_LIMIT_TOLERANCE), 2)
    try:
        order = get_trading_client().submit_order(LimitOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY, limit_price=limit_price,
        ))
        log.info(f"[BUY]  {symbol} x{qty} limit=${limit_price:.2f} order_id={order.id}")
        trade_log.info(f"BUY {symbol} x{qty} limit=${limit_price:.2f}")
        return True
    except Exception as e:
        log.error(f"Buy failed for {symbol}: {e}")
        return False


def place_sell(symbol: str, qty: int, price: float, use_market: bool = False) -> bool:
    """use_market=True for stop-loss exits where fill certainty > price precision."""
    if has_pending_sell(symbol):
        log.info(f"[SKIP] {symbol}: pending sell order already exists")
        return False
    try:
        if use_market:
            order_req = MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order_type = "MARKET"
        else:
            limit_price = round(price * (1 - SELL_LIMIT_TOLERANCE), 2)
            order_req = LimitOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY, limit_price=limit_price,
            )
            order_type = f"limit=${limit_price:.2f}"
        order = get_trading_client().submit_order(order_req)
        log.info(f"[SELL] {symbol} x{qty} {order_type} order_id={order.id}")
        trade_log.info(f"SELL {symbol} x{qty} {order_type}")
        return True
    except Exception as e:
        log.error(f"Sell failed for {symbol}: {e}")
        return False


def get_news(symbol: str, limit: int = 5) -> list:
    try:
        return get_trading_client().get_news(symbol, limit=limit)
    except Exception:
        return []
