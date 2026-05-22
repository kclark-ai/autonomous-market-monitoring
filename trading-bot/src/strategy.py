import pandas as pd
import pandas_ta as ta
from src.config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    SMA_SHORT, SMA_LONG, TREND_SMA,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL_PERIOD,
    MIN_HOLD_BARS, COOLDOWN_BARS, ATR_PERIOD,
)
import src.logger as logger

log = logger.get(__name__)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=ATR_PERIOD)
    df["rsi"] = ta.rsi(df["close"], length=14)
    df["sma_short"] = ta.sma(df["close"], length=SMA_SHORT)
    df["sma_long"] = ta.sma(df["close"], length=SMA_LONG)
    df["trend_sma"] = ta.sma(df["close"], length=TREND_SMA)
    macd = ta.macd(df["close"], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL_PERIOD)
    df["macd"] = macd[f"MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL_PERIOD}"]
    df["macd_signal"] = macd[f"MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL_PERIOD}"]
    df["macd_hist"] = macd[f"MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL_PERIOD}"]
    return df.dropna()


def get_signal(
    df: pd.DataFrame,
    bars_held: int = 0,
    bars_since_exit: int = 999,
    in_position: bool = False,
) -> str:
    if len(df) < 2:
        return "hold"

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    rsi = float(curr["rsi"])
    price = float(curr["close"])
    trend_sma = float(curr["trend_sma"])
    macd_hist = float(curr["macd_hist"])
    p_sma_s = float(prev["sma_short"])
    p_sma_l = float(prev["sma_long"])
    c_sma_s = float(curr["sma_short"])
    c_sma_l = float(curr["sma_long"])

    ma_cross_up = p_sma_s <= p_sma_l and c_sma_s > c_sma_l
    ma_cross_down = p_sma_s >= p_sma_l and c_sma_s < c_sma_l
    prev_macd_hist = float(prev["macd_hist"])
    macd_bullish = macd_hist > 0 and macd_hist > prev_macd_hist
    macd_bearish = macd_hist < 0 and macd_hist < prev_macd_hist
    in_uptrend = price > trend_sma

    if in_position:
        if bars_held < MIN_HOLD_BARS:
            return "hold"
        conditions_met = sum([rsi > RSI_OVERBOUGHT, ma_cross_down, macd_bearish])
        if conditions_met >= 2:
            return "sell"
        return "hold"

    if bars_since_exit < COOLDOWN_BARS:
        return "hold"
    if not in_uptrend:
        return "hold"

    rsi_dip = rsi < RSI_OVERSOLD and macd_bullish
    ma_bounce = ma_cross_up and macd_bullish
    # Trend-following: buy into an established uptrend with healthy RSI
    # No MACD requirement — MACD oscillates too much on hourly bars
    trend_momentum = (
        in_uptrend
        and 45 <= rsi < RSI_OVERBOUGHT
        and c_sma_s > c_sma_l   # short MA above long MA (trend healthy)
    )

    if rsi_dip or ma_bounce or trend_momentum:
        return "buy"
    return "hold"
