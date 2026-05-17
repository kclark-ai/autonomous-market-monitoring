from datetime import date, time as dtime
from zoneinfo import ZoneInfo

from src.config import MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TRAILING_STOP_PCT

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN = dtime(9, 30)

_daily_realized_loss = 0.0
_daily_start_value = 0.0
_last_reset_date: date | None = None


def maybe_reset_daily_loss(portfolio_value: float):
    global _daily_realized_loss, _daily_start_value, _last_reset_date
    from datetime import datetime
    now_et = datetime.now(_ET)
    today = now_et.date()
    if _last_reset_date != today and now_et.time() >= _MARKET_OPEN:
        _daily_realized_loss = 0.0
        _daily_start_value = portfolio_value
        _last_reset_date = today
        print(f"  [RISK] Daily loss counter reset for {today} | Start value: ${portfolio_value:,.2f}")


def record_loss(amount: float):
    global _daily_realized_loss
    if amount > 0:
        _daily_realized_loss += amount
        limit = _daily_start_value * MAX_DAILY_LOSS_PCT if _daily_start_value else 0
        print(f"  [RISK] Daily loss so far: ${_daily_realized_loss:.2f} / ${limit:.2f}")


def daily_loss_exceeded() -> bool:
    if _daily_start_value <= 0:
        return False
    return _daily_realized_loss >= (_daily_start_value * MAX_DAILY_LOSS_PCT)


def reset_daily_loss():
    global _daily_realized_loss
    _daily_realized_loss = 0.0
    print("  [RISK] Daily loss counter reset.")


def should_stop_loss(entry_price: float, current_price: float) -> bool:
    drop = (entry_price - current_price) / entry_price
    return drop >= STOP_LOSS_PCT


def should_trailing_stop(peak_price: float, current_price: float) -> bool:
    drop = (peak_price - current_price) / peak_price
    return drop >= TRAILING_STOP_PCT
