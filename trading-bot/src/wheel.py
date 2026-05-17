from datetime import date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce, AssetClass
from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL

WHEEL_SYMBOLS = ["PLTR", "AMD", "SOXX", "ARKK", "IONQ", "NET", "CRWD", "QQQ"]
CSP_OTM_PCT = 0.05
CC_OTM_PCT = 0.05
MIN_DTE = 14
MAX_DTE = 21
TAKE_PROFIT_PCT = 0.50

_paper = "paper" in ALPACA_BASE_URL.lower()
_client: TradingClient | None = None


def _get_client() -> TradingClient:
    global _client
    if _client is None:
        _client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=_paper)
    return _client


def _underlying_from_occ(occ_symbol: str) -> str:
    for i, ch in enumerate(occ_symbol):
        if ch.isdigit():
            return occ_symbol[:i]
    return occ_symbol


def _days_to_expiry(occ_symbol: str) -> int | None:
    try:
        underlying = _underlying_from_occ(occ_symbol)
        date_str = occ_symbol[len(underlying):len(underlying)+6]
        exp = date(2000 + int(date_str[:2]), int(date_str[2:4]), int(date_str[4:6]))
        return (exp - date.today()).days
    except Exception:
        return None


def manage_wheel_positions() -> list[dict]:
    closed = []
    try:
        positions = _get_client().get_all_positions()
    except Exception:
        return closed
    for pos in positions:
        if pos.asset_class != AssetClass.US_OPTION:
            continue
        symbol = pos.symbol
        underlying = _underlying_from_occ(symbol)
        if underlying not in WHEEL_SYMBOLS:
            continue
        if float(pos.qty) >= 0:
            continue
        qty = abs(int(float(pos.qty)))
        avg_entry = float(pos.avg_entry_price)
        unrealized_pnl = float(pos.unrealized_pl) if pos.unrealized_pl else 0.0
        if avg_entry <= 0:
            continue
        pct_profit = unrealized_pnl / (avg_entry * qty * 100)
        dte = _days_to_expiry(symbol)
        reason = None
        if pct_profit >= TAKE_PROFIT_PCT:
            reason = f"50% profit target ({pct_profit*100:.0f}%)"
        elif dte is not None and dte <= 2:
            reason = f"{dte} DTE - close before expiry"
        if reason:
            try:
                _get_client().submit_order(MarketOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
                ))
                closed.append({"symbol": symbol, "underlying": underlying, "pnl": unrealized_pnl, "reason": reason})
                print(f"  [WHEEL CLOSE] {symbol} - {reason}")
            except Exception as e:
                print(f"  [WHEEL] Close failed for {symbol}: {e}")
    return closed
