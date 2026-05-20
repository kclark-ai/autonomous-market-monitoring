import math
from datetime import date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce, AssetClass
from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
import src.logger as logger

log = logger.get(__name__)

OPTIONS_SIZE_PCT = 0.02
OPTIONS_TAKE_PROFIT = 0.50
OPTIONS_STOP_LOSS = 0.50
OPTIONS_MIN_DTE = 7

_paper = "paper" in ALPACA_BASE_URL.lower()
_client: TradingClient | None = None


def _get_client() -> TradingClient:
    global _client
    if _client is None:
        _client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=_paper)
    return _client


def _estimate_premium(current_price: float, strike_price: float, dte: int) -> float:
    """
    Rough Black-Scholes-inspired premium estimate for when live quotes aren't available.
    Uses ~30% implied volatility assumption for typical large-cap equities.
    Returns estimated cost per contract (already multiplied by 100).
    """
    intrinsic = max(0.0, current_price - strike_price)
    # time value: ATM option ≈ underlying * IV * sqrt(T) where IV≈0.30, T in years
    t_years = max(dte, 1) / 365.0
    iv = 0.30
    time_value = current_price * iv * math.sqrt(t_years) * 0.4  # 0.4 ≈ N(d1) for near-ATM
    premium_per_share = intrinsic + time_value
    return premium_per_share * 100  # one contract = 100 shares


def find_call_contract(symbol: str, current_price: float) -> object | None:
    today = date.today()
    try:
        result = _get_client().get_option_contracts(GetOptionContractsRequest(
            underlying_symbols=[symbol], type=ContractType.CALL,
            expiration_date_gte=(today + timedelta(days=21)).isoformat(),
            expiration_date_lte=(today + timedelta(days=35)).isoformat(),
            strike_price_gte=str(round(current_price * 0.99, 0)),
            strike_price_lte=str(round(current_price * 1.05, 0)),
            limit=20,
        ))
        contracts = result.option_contracts
        if not contracts:
            return None
        contracts.sort(key=lambda c: (float(c.strike_price), c.expiration_date))
        return contracts[0]
    except Exception as e:
        log.error(f"Contract lookup failed for {symbol}: {e}")
        return None


def buy_call(symbol: str, current_price: float, portfolio_value: float) -> bool:
    max_spend = portfolio_value * OPTIONS_SIZE_PCT
    contract = find_call_contract(symbol, current_price)
    if not contract:
        log.info(f"[OPTIONS] No suitable call contract found for {symbol}")
        return False

    strike = float(contract.strike_price)
    dte = (date.fromisoformat(str(contract.expiration_date)) - date.today()).days
    estimated_cost = _estimate_premium(current_price, strike, dte)

    if estimated_cost > max_spend:
        log.info(
            f"[OPTIONS] {symbol}: estimated cost ${estimated_cost:.0f} "
            f"exceeds budget ${max_spend:.0f}"
        )
        return False
    try:
        order = _get_client().submit_order(MarketOrderRequest(
            symbol=contract.symbol, qty=1, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))
        log.info(
            f"[CALL] {contract.symbol}  strike=${strike}  "
            f"exp={contract.expiration_date} ({dte}DTE)  "
            f"est_cost=${estimated_cost:.0f}  order_id={order.id}"
        )
        return True
    except Exception as e:
        log.error(f"Buy call failed for {symbol}: {e}")
        return False


def close_option(option_symbol: str, qty: int, reason: str) -> bool:
    try:
        _get_client().submit_order(MarketOrderRequest(
            symbol=option_symbol, qty=qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        ))
        log.info(f"[OPT EXIT] {option_symbol} x{qty} - {reason}")
        return True
    except Exception as e:
        log.error(f"Option close failed for {option_symbol}: {e}")
        return False


def check_options_positions(sell_signals: set[str]) -> list[dict]:
    closed = []
    try:
        positions = _get_client().get_all_positions()
    except Exception as e:
        log.error(f"Failed to fetch positions: {e}")
        return closed
    for pos in positions:
        if pos.asset_class != AssetClass.US_OPTION:
            continue
        symbol = pos.symbol
        qty = int(pos.qty)
        entry_price = float(pos.avg_entry_price)
        current_price = float(pos.current_price) if pos.current_price else 0.0
        unrealized_pnl = float(pos.unrealized_pl) if pos.unrealized_pl else 0.0
        if entry_price <= 0:
            continue
        pct_change = (current_price - entry_price) / entry_price
        dte = _days_to_expiry(symbol)
        underlying = _underlying_from_occ(symbol)
        reason = None
        if pct_change >= OPTIONS_TAKE_PROFIT:
            reason = f"+{pct_change*100:.0f}% take profit"
        elif pct_change <= -OPTIONS_STOP_LOSS:
            reason = f"{pct_change*100:.0f}% stop loss"
        elif dte is not None and dte <= OPTIONS_MIN_DTE:
            reason = f"{dte} DTE - time exit"
        elif underlying in sell_signals:
            reason = f"stock SELL signal on {underlying}"
        if reason:
            if close_option(symbol, qty, reason):
                closed.append({"symbol": symbol, "underlying": underlying,
                                "pnl": unrealized_pnl, "reason": reason})
    return closed


def get_open_option_symbols() -> set[str]:
    try:
        positions = _get_client().get_all_positions()
        return {_underlying_from_occ(p.symbol) for p in positions if p.asset_class == AssetClass.US_OPTION}
    except Exception:
        return set()


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
