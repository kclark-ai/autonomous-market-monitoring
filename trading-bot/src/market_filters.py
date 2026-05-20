import requests
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
import yfinance as yf
import src.logger as logger

log = logger.get(__name__)

_cache: dict = {}

VIX_CAUTION = 25
VIX_PAUSE = 35
VIX_EXTREME = 45
GAP_UP_BLOCK = 0.025


def _cached(key: str, ttl_minutes: int, fetch_fn):
    now = datetime.now(timezone.utc)
    if key in _cache:
        value, ts = _cache[key]
        if (now - ts).total_seconds() < ttl_minutes * 60:
            return value
    value = fetch_fn()
    _cache[key] = (value, now)
    return value


def get_vix() -> float | None:
    def fetch():
        try:
            hist = yf.Ticker("^VIX").history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            log.warning(f"VIX fetch failed: {e}")
        return None
    return _cached("vix", 15, fetch)


def check_vix() -> dict:
    vix = get_vix()
    if vix is None:
        return {"vix": None, "level": "unknown", "block_buys": True, "block_options": True,
                "message": "VIX unavailable — new buys paused"}
    if vix >= VIX_EXTREME:
        return {"vix": vix, "level": "extreme", "block_buys": True, "block_options": True,
                "message": f"VIX {vix:.1f} - EXTREME FEAR. All new trades paused."}
    elif vix >= VIX_PAUSE:
        return {"vix": vix, "level": "pause", "block_buys": True, "block_options": True,
                "message": f"VIX {vix:.1f} - HIGH FEAR. New buys paused."}
    elif vix >= VIX_CAUTION:
        return {"vix": vix, "level": "caution", "block_buys": False, "block_options": False,
                "message": f"VIX {vix:.1f} - CAUTION."}
    return {"vix": vix, "level": "normal", "block_buys": False, "block_options": False,
            "message": f"VIX {vix:.1f} - Normal."}


def check_gap(df, current_price: float) -> dict:
    if df is None or len(df) < 10:
        return {"gap_pct": 0.0, "block_buy": False, "message": ""}
    try:
        last_date = df.index[-1].date()
        prev_bars = df[[d.date() < last_date for d in df.index]]
        if prev_bars.empty:
            return {"gap_pct": 0.0, "block_buy": False, "message": ""}
        prev_close = float(prev_bars.iloc[-1]["close"])
        gap_pct = (current_price - prev_close) / prev_close
        if gap_pct > GAP_UP_BLOCK:
            return {"gap_pct": gap_pct, "block_buy": True,
                    "message": f"Gap up {gap_pct:.1%} from prior close ${prev_close:.2f} — buying into exhaustion"}
    except Exception:
        return {"gap_pct": 0.0, "block_buy": False, "message": ""}
    return {"gap_pct": gap_pct, "block_buy": False, "message": ""}


def run_all_filters(symbol: str, df=None) -> dict:
    vix_result = check_vix()
    if vix_result["message"]:
        log.info(f"[VIX] {vix_result['message']}")

    volume_result = {"confirmed": True, "message": ""}
    if df is not None and "volume" in df.columns and len(df) >= 20:
        current_vol = float(df.iloc[-1]["volume"])
        avg_vol = float(df["volume"].tail(20).mean())
        if avg_vol > 0:
            ratio = current_vol / avg_vol
            if ratio < 0.8:
                volume_result = {"confirmed": False, "message": f"Low volume ({ratio:.0%} of avg)"}

    gap_result = {"block_buy": False, "message": ""}
    if df is not None:
        current_price = float(df.iloc[-1]["close"])
        gap_result = check_gap(df, current_price)
        if gap_result["message"]:
            log.info(f"[GAP] {gap_result['message']}")

    block_buy = vix_result["block_buys"] or not volume_result["confirmed"] or gap_result["block_buy"]
    reasons = [r for r in [
        vix_result["message"] if vix_result["block_buys"] else "",
        volume_result.get("message", ""),
        gap_result["message"] if gap_result["block_buy"] else "",
    ] if r]

    return {
        "block_buy": block_buy,
        "block_options": vix_result["block_options"],
        "tighten_stops": vix_result["level"] == "caution",
        "reason": " | ".join(reasons),
        "vix": vix_result["vix"],
    }
