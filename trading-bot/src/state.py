import threading
from datetime import datetime

_lock = threading.Lock()

_state = {
    "bot_running": True,
    "portfolio_value": 0.0,
    "cash": 0.0,
    "daily_pnl": 0.0,
    "positions": {},
    "trade_history": [],
    "last_tick": None,
    "errors": [],
}

_pending_symbols: set[str] = set()
_approved_symbols: set[str] = set()


def get():
    with _lock:
        return dict(_state)


def set_bot_running(val: bool):
    with _lock:
        _state["bot_running"] = val


def is_running() -> bool:
    with _lock:
        return _state["bot_running"]


def update_portfolio(portfolio_value: float, cash: float, daily_pnl: float):
    with _lock:
        _state["portfolio_value"] = portfolio_value
        _state["cash"] = cash
        _state["daily_pnl"] = daily_pnl
        _state["last_tick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def update_position(symbol: str, qty: int, entry_price: float, peak_price: float, current_price: float):
    with _lock:
        unrealized_pnl = (current_price - entry_price) * qty
        _state["positions"][symbol] = {
            "qty": qty,
            "entry_price": entry_price,
            "peak_price": peak_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "pct_change": ((current_price - entry_price) / entry_price) * 100,
        }


def clear_position(symbol: str):
    with _lock:
        _state["positions"].pop(symbol, None)


def add_trade(symbol: str, action: str, price: float, qty: int, pnl: float = None):
    with _lock:
        _state["trade_history"].insert(0, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": symbol,
            "action": action,
            "price": price,
            "qty": qty,
            "pnl": pnl,
        })
        _state["trade_history"] = _state["trade_history"][:50]


def add_error(msg: str):
    with _lock:
        _state["errors"].insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
        _state["errors"] = _state["errors"][:10]


def add_pending_symbol(symbol: str):
    with _lock:
        _pending_symbols.add(symbol)


def approve_symbol(symbol: str):
    with _lock:
        _approved_symbols.add(symbol)
        _pending_symbols.discard(symbol)


def get_pending_symbols() -> set[str]:
    with _lock:
        return set(_pending_symbols)


def get_approved_symbols() -> set[str]:
    with _lock:
        return set(_approved_symbols)
