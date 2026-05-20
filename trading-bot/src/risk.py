import json
import os
from datetime import date, time as dtime
from zoneinfo import ZoneInfo

from src.config import MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, TRAILING_STOP_PCT
import src.logger as logger

log = logger.get(__name__)

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN = dtime(9, 30)
_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "risk_state.json")

_daily_realized_loss = 0.0
_daily_start_value = 0.0
_last_reset_date: date | None = None
_circuit_breaker_alerted = False


def _load_state():
    global _daily_realized_loss, _daily_start_value, _last_reset_date
    try:
        with open(_STATE_FILE) as f:
            data = json.load(f)
            _daily_realized_loss = data.get("daily_realized_loss", 0.0)
            _daily_start_value = data.get("daily_start_value", 0.0)
            date_str = data.get("last_reset_date")
            _last_reset_date = date.fromisoformat(date_str) if date_str else None
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def _save_state():
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump({
                "daily_realized_loss": _daily_realized_loss,
                "daily_start_value": _daily_start_value,
                "last_reset_date": _last_reset_date.isoformat() if _last_reset_date else None,
            }, f)
    except Exception as e:
        log.error(f"Failed to save risk state: {e}")


_load_state()


def maybe_reset_daily_loss(portfolio_value: float):
    global _daily_realized_loss, _daily_start_value, _last_reset_date, _circuit_breaker_alerted
    from datetime import datetime
    now_et = datetime.now(_ET)
    today = now_et.date()
    if _last_reset_date != today and now_et.time() >= _MARKET_OPEN:
        _daily_realized_loss = 0.0
        _daily_start_value = portfolio_value
        _last_reset_date = today
        _circuit_breaker_alerted = False
        _save_state()
        log.info(f"Daily loss counter reset for {today} | Start value: ${portfolio_value:,.2f}")


def record_loss(amount: float):
    global _daily_realized_loss
    if amount > 0:
        _daily_realized_loss += amount
        _save_state()
        limit = _daily_start_value * MAX_DAILY_LOSS_PCT if _daily_start_value else 0
        log.info(f"Daily realized loss: ${_daily_realized_loss:.2f} / limit ${limit:.2f}")


def daily_loss_exceeded() -> bool:
    if _daily_start_value <= 0:
        return False
    return _daily_realized_loss >= (_daily_start_value * MAX_DAILY_LOSS_PCT)


def total_daily_loss_exceeded(current_portfolio_value: float) -> bool:
    if _daily_start_value <= 0:
        return False
    return (_daily_start_value - current_portfolio_value) >= (_daily_start_value * MAX_DAILY_LOSS_PCT)


def get_daily_start_value() -> float:
    return _daily_start_value


def should_alert_circuit_breaker() -> bool:
    return not _circuit_breaker_alerted


def mark_circuit_breaker_alerted():
    global _circuit_breaker_alerted
    _circuit_breaker_alerted = True


def reset_daily_loss():
    global _daily_realized_loss
    _daily_realized_loss = 0.0
    _save_state()
    log.info("Daily loss counter reset manually")


def get_risk_summary() -> dict:
    limit = _daily_start_value * MAX_DAILY_LOSS_PCT if _daily_start_value else 0
    tripped = daily_loss_exceeded()
    return {
        "daily_realized_loss": _daily_realized_loss,
        "daily_loss_limit": limit,
        "daily_loss_pct": (_daily_realized_loss / _daily_start_value * 100) if _daily_start_value else 0,
        "daily_loss_limit_pct": MAX_DAILY_LOSS_PCT * 100,
        "circuit_breaker_tripped": tripped,
    }


def should_stop_loss(entry_price: float, current_price: float) -> bool:
    drop = (entry_price - current_price) / entry_price
    return drop >= STOP_LOSS_PCT


def should_trailing_stop(peak_price: float, current_price: float) -> bool:
    drop = (peak_price - current_price) / peak_price
    return drop >= TRAILING_STOP_PCT
