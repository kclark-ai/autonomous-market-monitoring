import threading
import time
import requests
from src.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import src.state as state
import src.logger as logger

log = logger.get(__name__)

_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
_enabled = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
_ALLOWED_CHAT_ID = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None


def send(text: str):
    if not _enabled:
        return
    try:
        requests.post(f"{_BASE}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


def send_trade(action: str, symbol: str, qty: int, price: float, pnl: float = None):
    if not _enabled:
        return
    if "BUY" in action.upper():
        icon = "BUY"
    elif pnl is not None and pnl >= 0:
        icon = "WIN"
    else:
        icon = "LOSS"
    pnl_str = f"  |  P&amp;L: ${pnl:+.2f}" if pnl is not None else ""
    send(f"{icon} {action}  {symbol} x{qty} @ ${price:.2f}{pnl_str}")


def send_alert(text: str):
    send(f"ALERT: {text}")


def _authorized(msg: dict) -> bool:
    if _ALLOWED_CHAT_ID is None:
        return False
    return msg.get("chat", {}).get("id") == _ALLOWED_CHAT_ID


def _handle_command(text: str, msg: dict):
    if not _authorized(msg):
        log.warning(f"Rejected command from unauthorized chat: {msg.get('chat', {}).get('id')}")
        return
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").lower()

    if cmd == "status":
        s = state.get()
        status = "Running" if s["bot_running"] else "Paused"
        send(
            f"Bot: {status}\n"
            f"Portfolio: ${s['portfolio_value']:,.2f}\n"
            f"Cash: ${s['cash']:,.2f}\n"
            f"Last tick: {s['last_tick'] or 'not yet'}"
        )
    elif cmd == "positions":
        s = state.get()
        if not s["positions"]:
            send("No open positions.")
            return
        lines = ["<b>Open Positions</b>"]
        for sym, p in s["positions"].items():
            lines.append(
                f"{sym} x{p['qty']}  entry ${p['entry_price']:.2f} → "
                f"${p['current_price']:.2f}  ({p['unrealized_pnl']:+.2f})"
            )
        send("\n".join(lines))
    elif cmd == "trades":
        s = state.get()
        trades = s["trade_history"][:10]
        if not trades:
            send("No trades yet.")
            return
        lines = ["<b>Recent Trades</b>"]
        for t in trades:
            pnl_str = f"  ${t['pnl']:+.2f}" if t["pnl"] is not None else ""
            lines.append(f"{t['time']}  {t['action']} {t['symbol']} x{t['qty']} @ ${t['price']:.2f}{pnl_str}")
        send("\n".join(lines))
    elif cmd == "stop":
        state.set_bot_running(False)
        log.info("Bot paused via Telegram command")
        send("Bot paused. Send /start to resume.")
    elif cmd == "start":
        state.set_bot_running(True)
        log.info("Bot resumed via Telegram command")
        send("Bot resumed.")
    elif cmd == "approve":
        if len(parts) < 2:
            send("Usage: /approve TICKER")
            return
        ticker = parts[1].upper()
        state.approve_symbol(ticker)
        log.info(f"Symbol {ticker} approved via Telegram")
        send(f"{ticker} approved and will be added to watchlist on next tick.")
    elif cmd == "pending":
        pending = state.get_pending_symbols()
        if not pending:
            send("No symbols pending approval.")
        else:
            send(f"Pending approval: {', '.join(pending)}\nUse /approve TICKER to add.")
    elif cmd == "help":
        send("/status /positions /trades /stop /start /pending /approve TICKER /help")
    else:
        send(f"Unknown command: /{cmd}")


def _poll_loop():
    offset = 0
    while True:
        if not _enabled:
            time.sleep(60)
            continue
        try:
            resp = requests.get(f"{_BASE}/getUpdates", params={
                "offset": offset, "timeout": 30, "allowed_updates": ["message"],
            }, timeout=40)
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                if text.startswith("/"):
                    _handle_command(text, msg)
        except Exception as e:
            log.warning(f"Telegram poll error: {e}")
            time.sleep(10)


def start_polling():
    if not _enabled:
        log.info("Telegram not configured — skipping. Add TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to .env")
        return
    threading.Thread(target=_poll_loop, daemon=True, name="telegram-poll").start()
    log.info("Telegram command listener started")


def get_chat_id():
    resp = requests.get(f"{_BASE}/getUpdates", timeout=10).json()
    updates = resp.get("result", [])
    if not updates:
        print("No messages found. Send any message to your bot first.")
        return
    for u in updates:
        chat = u.get("message", {}).get("chat", {})
        print(f"Chat ID: {chat.get('id')}  |  From: {chat.get('first_name')}")
