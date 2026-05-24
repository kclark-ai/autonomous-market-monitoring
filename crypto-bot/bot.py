#!/usr/bin/env python3
"""
bot.py — Crypto trading bot entry point.

Runs 24/7, scanning every 15 minutes.
Starts a Flask dashboard in a background thread on port 5002.
"""

from __future__ import annotations
import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Project path ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    ALL_SYMBOLS, AI_TOKENS, CRYPTO_PAIRS,
    SCAN_INTERVAL_MIN, DASHBOARD_PORT, DASHBOARD_HOST,
    LOG_FILE,
)
from alpaca_client import AlpacaClient
from regime import detect_regime
from momentum import momentum_signal
from mean_reversion import mean_reversion_signal
from ai_watchlist import is_ai_token, check_volume_spike
from risk import calculate_qty, stop_price, target_price, can_open, is_stop_hit, is_target_hit
import state_manager as state

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot")


# ── Dashboard thread ───────────────────────────────────────────────────────────

def _start_dashboard() -> None:
    try:
        from dashboard import create_app
        app = create_app()
        logger.info(f"Dashboard running at http://localhost:{DASHBOARD_PORT}")
        app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT,
                debug=False, use_reloader=False)
    except Exception as exc:
        logger.error(f"Dashboard failed: {exc}")


# ── Scan cycle ─────────────────────────────────────────────────────────────────

def run_scan(client: AlpacaClient) -> None:
    scan_num = state.get().get("scan_count", 0) + 1
    logger.info("=" * 65)
    logger.info(f"SCAN #{scan_num} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # ── Account ────────────────────────────────────────────────────────────────
    account = client.get_account()
    if not account:
        logger.error("Cannot reach Alpaca account — skipping scan")
        state.log_error("Could not fetch account info")
        return

    portfolio_value = account["portfolio_value"]
    logger.info(
        f"Portfolio: ${portfolio_value:,.2f}  "
        f"Cash: ${account['cash']:,.2f}  "
        f"Buying power: ${account['buying_power']:,.2f}"
    )

    # ── Open positions ─────────────────────────────────────────────────────────
    positions = client.get_positions()
    logger.info(f"Open positions: {len(positions)}/{4}")

    # ── Exit checks (stop loss / take profit) ──────────────────────────────────
    for sym, pos in list(positions.items()):
        entry   = pos["entry_price"]
        current = pos["current_price"]

        if is_stop_hit(entry, current):
            pct = (current - entry) / entry * 100
            logger.warning(
                f"🔴 STOP LOSS  {sym}  entry=${entry:.4f}  "
                f"current=${current:.4f}  {pct:+.1f}%"
            )
            result = client.sell_position(sym)
            if result:
                state.add_trade(_trade_record(
                    sym, "sell", pos["qty"], current,
                    reason="STOP_LOSS", strategy="risk", pl_pct=pct,
                ))
                del positions[sym]

        elif is_target_hit(entry, current):
            pct = (current - entry) / entry * 100
            logger.info(
                f"🟢 TAKE PROFIT {sym}  entry=${entry:.4f}  "
                f"current=${current:.4f}  +{pct:.1f}%"
            )
            result = client.sell_position(sym)
            if result:
                state.add_trade(_trade_record(
                    sym, "sell", pos["qty"], current,
                    reason="TAKE_PROFIT", strategy="risk", pl_pct=pct,
                ))
                del positions[sym]

    # ── Signal loop ────────────────────────────────────────────────────────────
    regime_data:   dict = {}
    ai_data:       dict = {}
    signal_data:   dict = {}

    for sym in ALL_SYMBOLS:
        logger.info(f"  [{sym}] fetching bars...")

        df = client.get_bars(sym)
        if df is None or len(df) < 30:
            logger.warning(f"  [{sym}] skipped — insufficient data ({len(df) if df is not None else 0} bars)")
            continue

        # Regime
        regime_info = detect_regime(df)
        regime_data[sym] = regime_info
        regime      = regime_info["regime"]
        adx_val     = regime_info.get("adx")
        logger.info(f"  [{sym}] regime={regime.upper()}  ADX={adx_val}")

        # AI watchlist volume check
        ai_info = {}
        if is_ai_token(sym):
            ai_info = check_volume_spike(df, sym)
            ai_data[sym] = ai_info
            if ai_info["triggered"]:
                logger.info(f"  [{sym}] ⚡ AI VOLUME SPIKE  {ai_info['reason']}")

        # Choose strategy
        if regime == "trending":
            sig = momentum_signal(df)
            sig["strategy"] = "momentum"

        elif regime == "sideways":
            sig = mean_reversion_signal(df)
            sig["strategy"] = "mean_reversion"

            # AI override: volume spike in sideways → try momentum instead
            if ai_info.get("triggered") and sig["signal"] == "neutral":
                mom = momentum_signal(df)
                if mom["signal"] == "buy":
                    mom["strategy"] = "ai_watchlist"
                    sig = mom
                    logger.info(f"  [{sym}] AI watchlist override → momentum buy")

        else:
            sig = {"signal": "neutral", "reason": "regime unknown", "strategy": "none"}

        signal_data[sym] = sig
        logger.info(
            f"  [{sym}] signal={sig['signal'].upper()}  "
            f"strategy={sig.get('strategy')}  "
            f"reason={sig.get('reason')}"
        )

        # ── Execute ────────────────────────────────────────────────────────────
        if sig["signal"] == "buy":
            allowed, reason = can_open(positions, sym)
            if not allowed:
                logger.info(f"  [{sym}] buy blocked: {reason}")
                continue

            price        = float(df["close"].iloc[-1])
            qty          = calculate_qty(portfolio_value, price)
            dollar_amount = qty * price
            if qty <= 0:
                continue

            if account["cash"] < dollar_amount:
                logger.info(
                    f"  [{sym}] buy skipped — insufficient cash "
                    f"(${account['cash']:,.2f} available, ${dollar_amount:,.2f} needed)"
                )
                continue

            logger.info(f"  [{sym}] → BUY {qty} @ ~${price:.4f}")
            order = client.buy(sym, qty)

            if order:
                positions[sym] = {
                    "alpaca_symbol": sym.replace("/", ""),
                    "qty":           qty,
                    "entry_price":   price,
                    "current_price": price,
                    "market_value":  qty * price,
                    "unrealized_pl": 0.0,
                    "unrealized_plpc": 0.0,
                    "side":          "long",
                }
                state.add_trade(_trade_record(
                    sym, "buy", qty, price,
                    reason=sig.get("reason", ""),
                    strategy=sig.get("strategy", ""),
                    regime=regime,
                    stop=stop_price(price),
                    target=target_price(price),
                ))
                logger.info(f"  [{sym}] ✓ BUY order submitted  stop=${stop_price(price):.4f}  target=${target_price(price):.4f}")

        elif sig["signal"] == "sell" and sym in positions:
            pos   = positions[sym]
            price = float(df["close"].iloc[-1])
            pct   = (price - pos["entry_price"]) / pos["entry_price"] * 100

            logger.info(f"  [{sym}] → SELL  {pct:+.1f}%")
            result = client.sell_position(sym)
            if result:
                state.add_trade(_trade_record(
                    sym, "sell", pos["qty"], price,
                    reason=sig.get("reason", ""),
                    strategy=sig.get("strategy", ""),
                    pl_pct=pct,
                ))
                del positions[sym]
                logger.info(f"  [{sym}] ✓ SELL order submitted")

    # ── Update shared state ────────────────────────────────────────────────────
    now      = datetime.now(timezone.utc)
    next_run = now + timedelta(minutes=SCAN_INTERVAL_MIN)

    # Enrich positions with stop/target levels for the dashboard
    enriched: dict = {}
    for sym, pos in positions.items():
        enriched[sym] = {
            **pos,
            "stop_price":   stop_price(pos["entry_price"]),
            "target_price": target_price(pos["entry_price"]),
        }

    state.update_many({
        "status":          "running",
        "last_scan":       now.isoformat(),
        "next_scan":       next_run.isoformat(),
        "scan_count":      scan_num,
        "portfolio_value": portfolio_value,
        "cash":            account["cash"],
        "positions":       enriched,
        "regimes":         regime_data,
        "ai_watchlist":    ai_data,
        "signals":         signal_data,
    })

    logger.info(f"Scan #{scan_num} done. Next scan: {next_run.strftime('%H:%M UTC')}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _trade_record(sym, side, qty, price, **kwargs) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol":    sym,
        "side":      side,
        "qty":       qty,
        "price":     price,
        **kwargs,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("🚀 Crypto Bot starting")
    logger.info(f"   Symbols  : {ALL_SYMBOLS}")
    logger.info(f"   AI tokens: {AI_TOKENS}")
    logger.info(f"   Interval : {SCAN_INTERVAL_MIN} min")
    logger.info(f"   Dashboard: http://localhost:{DASHBOARD_PORT}")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.critical("ALPACA_API_KEY / ALPACA_SECRET_KEY not set — check your .env")
        sys.exit(1)

    # Dashboard in background thread
    threading.Thread(target=_start_dashboard, daemon=True, name="dashboard").start()

    state.set_status("running")
    client = AlpacaClient()

    while True:
        try:
            run_scan(client)
        except KeyboardInterrupt:
            logger.info("Shutdown requested (KeyboardInterrupt)")
            state.set_status("stopped")
            break
        except Exception as exc:
            logger.error(f"Unhandled error in scan: {exc}", exc_info=True)
            state.log_error(str(exc))

        logger.info(f"Sleeping {SCAN_INTERVAL_MIN} min …")
        try:
            time.sleep(SCAN_INTERVAL_MIN * 60)
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
            state.set_status("stopped")
            break


if __name__ == "__main__":
    main()
