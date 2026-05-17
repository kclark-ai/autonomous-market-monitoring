import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WATCHLIST = os.getenv("WATCHLIST", "AAPL,MSFT").split(",")

MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", 1000))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", 200))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", 0.03))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 0.06))
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", 0.20))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", 4))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", 0.05))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", 0.035))

RSI_OVERSOLD = 40
RSI_OVERBOUGHT = 65
SMA_SHORT = 9
SMA_LONG = 21
TREND_SMA = 50
BAR_TIMEFRAME = "1Hour"
LOOKBACK_BARS = 60
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL_PERIOD = 9
MIN_HOLD_BARS = 3
COOLDOWN_BARS = 2
