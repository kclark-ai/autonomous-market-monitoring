import feedparser
import re
import time
from datetime import datetime, timedelta, timezone
from src.config import WATCHLIST

_BULLISH = [
    "trade deal", "deal signed", "cut taxes", "tax cut", "deregulation",
    "record high", "strong economy", "growth", "jobs report", "rate cut",
    "stimulus", "approved", "agreement", "ceasefire", "peace deal",
    "great company", "doing great", "winning", "tremendous",
]

_BEARISH = [
    "tariff", "tariffs", "sanction", "sanctions", "ban", "banned",
    "trade war", "shutdown", "default", "recession", "crisis",
    "rate hike", "inflation", "investigation", "indicted", "charged",
    "collapse", "bankrupt", "layoffs", "war", "attack",
]

_STOCK_KEYWORDS: dict[str, list[str] | None] = {
    "spacex": ["SPCE"], "starlink": ["SPCE"], "apple": ["AAPL"],
    "iphone": ["AAPL"], "nvidia": ["NVDA"], "microsoft": ["MSFT"],
    "tesla": ["TSLA"], "elon musk": ["TSLA"], "elon": ["TSLA"],
    "amazon": ["AMZN"], "google": ["GOOGL"], "meta": ["META"],
    "china": None, "federal reserve": None, "fed ": None,
    "interest rate": None, "oil": None,
}

_news_cache: dict[str, tuple[int, str, datetime]] = {}
_trump_cache: list[dict] = []
_last_trump_fetch = datetime.min.replace(tzinfo=timezone.utc)
_TRUMP_RSS = "https://truthsocial.com/@realDonaldTrump.rss"
_CACHE_TTL_MINUTES = 30


def _score_text(text: str) -> int:
    t = text.lower()
    score = 0
    for kw in _BULLISH:
        if kw in t:
            score += 1
    for kw in _BEARISH:
        if kw in t:
            score -= 1
    return max(-3, min(3, score))


def _affected_symbols(text: str) -> list[str]:
    t = text.lower()
    symbols: set[str] = set()
    market_wide = False
    for kw, tickers in _STOCK_KEYWORDS.items():
        if kw in t:
            if tickers is None:
                market_wide = True
            else:
                symbols.update(tickers)
    for sym in WATCHLIST:
        if sym.lower() in t:
            symbols.add(sym)
    if market_wide:
        return list(set(WATCHLIST))
    return list(symbols)


def fetch_trump_posts(max_age_hours: int = 4) -> list[dict]:
    global _trump_cache, _last_trump_fetch
    now = datetime.now(timezone.utc)
    if (now - _last_trump_fetch).total_seconds() < _CACHE_TTL_MINUTES * 60:
        return _trump_cache
    results = []
    try:
        feed = feedparser.parse(_TRUMP_RSS)
        cutoff = now - timedelta(hours=max_age_hours)
        for entry in feed.entries[:20]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published and published < cutoff:
                continue
            text = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or entry.get("title", "")).strip()
            score = _score_text(text)
            symbols = _affected_symbols(text)
            if score != 0 or symbols:
                results.append({"text": text[:280], "score": score, "symbols": symbols,
                                 "published": published, "source": "Trump/TruthSocial"})
        _trump_cache = results
        _last_trump_fetch = now
    except Exception as e:
        print(f"  [NEWS] Trump RSS fetch failed: {e}")
    return results


def get_news_signal(symbol: str) -> tuple[int, str]:
    all_signals: list[tuple[int, str]] = []
    for post in fetch_trump_posts():
        if not post["symbols"] or symbol in post["symbols"]:
            all_signals.append((post["score"], f"[Trump] {post['text'][:100]}"))
    if not all_signals:
        return 0, ""
    total_score = sum(s for s, _ in all_signals)
    avg = total_score / len(all_signals)
    final_score = max(-3, min(3, round(avg)))
    all_signals.sort(key=lambda x: abs(x[0]), reverse=True)
    return final_score, all_signals[0][1]


_IPO_CANDIDATES = ["SPACEX", "STRLK", "STRLINK"]
_ipo_found: str | None = None


def check_spacex_ipo() -> str | None:
    global _ipo_found
    if _ipo_found:
        return _ipo_found
    from src.broker import get_asset
    for ticker in _IPO_CANDIDATES:
        try:
            asset = get_asset(ticker)
            if asset and asset.tradable:
                _ipo_found = ticker
                return ticker
        except Exception:
            pass
    return None
