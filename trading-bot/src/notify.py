import threading
import time
import requests
from src.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import src.state as state

_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
_enabled = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def send(text: str):
    if not _enabled:
        return
    try:
        requests.post(f"{_BASE}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        print(f"  [TELEGRAM] Send failed: {e}")


def send_trade(action: str, symbol: str, qty: int, price: float, pnl: float = None):
    if not _enabled:
        return
    if "BUY" in action.upper():
        icon = "BUY"
    elif pnl is not None and pnl >= 0:
        icon = "WIN"
    else:
        icon = "LOSS"
    pnl_str = f"  |  P&L: ${pnl:+.2f}" if pnl is not None else ""
    send(f"{icon} {action}  {symbol} x{qty} @ ${price:.2f}{pnl_str}")


def send_alert(text: str):
    send(f"ALERT: {text}")


def _handle_command(text: str):
    cmd = text.strip().lower().split()[0].replace("/", "")
    if cmd == "status":
        s = state.get()
        status = "Running" if s["bot_running"] else "Paused"
        send(f"Bot: {status}\nPortfolio: ${s['portfolio_value']:,.2f}\nCash: ${s['cash']:,.2f}\nLast tick: {s['last_tick'] or 'not yet'}")
    elif cmd == "positions":
        s = state.get()
        if not s["positions"]:
            send("No open positions.")
            return
        lines = ["Open Positions"]
        for sym, p in s["positions"].items():
            lines.append(f"{sym} x{p['qty']} entry ${p['entry_price']:.2f} -> ${p['current_price']:.2f} (${p['unrealized_pnl']:+.2f})")
        send("\n".join(lines))
    elif cmd == "trades":
        s = state.get()
        trades = s["trade_history"][:10]
        if not trades:
            send("No trades yet.")
            return
        lines = ["Recent Trades"]
        for t in trades:
            pnl_str = f"  ${t['pnl']:+.2f}" if t["pnl"] is not None else ""
            lines.append(f"{t['time']}  {t['action']} {t['symbol']} x{t['qty']} @ ${t['price']:.2f}{pnl_str}")
        send("\n".join(lines))
    elif cmd == "stop":
        state.set_bot_running(False)
        send("Bot paused. Send /start to resume.")
    elif cmd == "start":
        state.set_bot_running(True)
        send("Bot resumed.")
    elif cmd == "help":
        send("/status /positions /trades /stop /start /help")
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
                    _handle_command(text)
        except Exception as e:
            print(f"  [TELEGRAM] Poll error: {e}")
            time.sleep(10)


def start_polling():
    if not _enabled:
        print("  [TELEGRAM] Not configured — skipping. Add TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to .env")
        return
    threading.Thread(target=_poll_loop, daemon=True, name="telegram-poll").start()
    print("  [TELEGRAM] Command listener started.")


def get_chat_id():
    resp = requests.get(f"{_BASE}/getUpdates", timeout=10).json()
    updates = resp.get("result", [])
    if not updates:
        print("No messages found. Send any message to your bot first.")
        return
    for u in updates:
        chat = u.get("message", {}).get("chat", {})
        print(f"Chat ID: {chat.get('id')}  |  From: {chat.get('first_name')}")
