import requests
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
import yfinance as yf

_cache: dict = {}

def _cached(key: str, ttl_minutes: int, fetch_fn):
    now = datetime.now(timezone.utc)
    if key in _cache:
        value, ts = _cache[key]
        if (now - ts).total_seconds() < ttl_minutes * 60:
            return value
    value = fetch_fn()
    _cache[key] = (value, now)
    return value

VIX_CAUTION = 25
VIX_PAUSE = 35
VIX_EXTREME = 45

def get_vix() -> float | None:
    def fetch():
        try:
            hist = yf.Ticker("^VIX").history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            print(f"  [VIX] Fetch failed: {e}")
        return None
    return _cached("vix", 15, fetch)

def check_vix() -> dict:
    vix = get_vix()
    if vix is None:
        return {"vix": None, "level": "unknown", "block_buys": False, "block_options": False, "message": "VIX unavailable"}
    if vix >= VIX_EXTREME:
        return {"vix": vix, "level": "extreme", "block_buys": True, "block_options": True, "message": f"VIX {vix:.1f} - EXTREME FEAR. All new trades paused."}
    elif vix >= VIX_PAUSE:
        return {"vix": vix, "level": "pause", "block_buys": True, "block_options": True, "message": f"VIX {vix:.1f} - HIGH FEAR. New buys paused."}
    elif vix >= VIX_CAUTION:
        return {"vix": vix, "level": "caution", "block_buys": False, "block_options": False, "message": f"VIX {vix:.1f} - CAUTION."}
    return {"vix": vix, "level": "normal", "block_buys": False, "block_options": False, "message": f"VIX {vix:.1f} - Normal."}

def run_all_filters(symbol: str, df=None) -> dict:
    vix_result = check_vix()
    if vix_result["message"]:
        print(f"    [VIX] {vix_result['message']}")
    volume_result = {"confirmed": True, "message": ""}
    if df is not None and "volume" in df.columns and len(df) >= 20:
        current_vol = float(df.iloc[-1]["volume"])
        avg_vol = float(df["volume"].tail(20).mean())
        if avg_vol > 0:
            ratio = current_vol / avg_vol
            if ratio < 0.7:
                volume_result = {"confirmed": False, "message": f"Low volume ({ratio:.0%} of avg)"}
    block_buy = vix_result["block_buys"] or not volume_result["confirmed"]
    return {
        "block_buy": block_buy,
        "block_options": vix_result["block_options"],
        "tighten_stops": vix_result["level"] == "caution",
        "reason": vix_result["message"] if vix_result["block_buys"] else volume_result.get("message", ""),
        "vix": vix_result["vix"],
    }
