import requests
from datetime import datetime, timedelta, timezone
from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
import src.logger as logger

log = logger.get(__name__)

_BULLISH = [
    "upgrade", "outperform", "beat estimates", "record revenue", "record earnings",
    "deal signed", "acquisition", "partnership", "fda approved", "approved",
    "raised guidance", "buyback", "dividend increase", "rate cut", "stimulus",
    "strong demand", "beat expectations", "positive trial", "cleared",
]

_BEARISH = [
    "downgrade", "underperform", "missed estimates", "missed expectations",
    "lawsuit", "recall", "probe", "investigation", "tariff", "sanction", "ban",
    "layoffs", "default", "recession", "rate hike", "fine", "penalty",
    "fraud", "warning letter", "subpoena", "data breach", "bankruptcy",
    "revenue warning", "guidance cut", "plant closure",
]

_cache: dict[str, tuple[list, datetime]] = {}
_CACHE_TTL_MINUTES = 30
_NEWS_MAX_AGE_HOURS = 24

_ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


def _fetch_alpaca_news(symbol: str, limit: int = 15) -> list[dict]:
    now = datetime.now(timezone.utc)
    if symbol in _cache:
        data, ts = _cache[symbol]
        if (now - ts).total_seconds() < _CACHE_TTL_MINUTES * 60:
            return data
    try:
        resp = requests.get(
            _ALPACA_NEWS_URL,
            headers={
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            },
            params={"symbols": symbol, "limit": limit, "sort": "desc"},
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("news", [])
        _cache[symbol] = (articles, now)
        return articles
    except Exception as e:
        log.warning(f"News fetch failed for {symbol}: {e}")
        cached = _cache.get(symbol)
        return cached[0] if cached else []


def _score_text(text: str) -> int:
    t = text.lower()
    score = sum(1 for kw in _BULLISH if kw in t) - sum(1 for kw in _BEARISH if kw in t)
    return max(-3, min(3, score))


def get_news_signal(symbol: str) -> tuple[int, str]:
    articles = _fetch_alpaca_news(symbol)
    if not articles:
        return 0, ""

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_NEWS_MAX_AGE_HOURS)
    signals: list[tuple[int, str]] = []

    for a in articles:
        raw_date = a.get("created_at", "")
        try:
            pub = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if pub < cutoff:
                continue
        except Exception:
            pass
        headline = a.get("headline", "")
        summary = a.get("summary", "")
        score = _score_text(f"{headline} {summary}")
        if score != 0:
            signals.append((score, headline[:120]))

    if not signals:
        return 0, ""

    avg = sum(s for s, _ in signals) / len(signals)
    signals.sort(key=lambda x: abs(x[0]), reverse=True)
    return max(-3, min(3, round(avg))), signals[0][1]


_IPO_CANDIDATES = ["SPACEX", "STRLK", "STRLINK"]
_ipo_checked: set[str] = set()


def check_spacex_ipo() -> str | None:
    from src.broker import get_asset
    for ticker in _IPO_CANDIDATES:
        if ticker in _ipo_checked:
            continue
        try:
            asset = get_asset(ticker)
            if asset and asset.tradable:
                return ticker
        except Exception:
            pass
        _ipo_checked.add(ticker)
    return None
