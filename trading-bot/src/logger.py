import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)


def setup():
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = RotatingFileHandler(
        os.path.join(_LOG_DIR, "bot.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    trade_fh = RotatingFileHandler(
        os.path.join(_LOG_DIR, "trades.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=30,
    )
    trade_fh.setFormatter(fmt)
    logging.getLogger("trades").addHandler(trade_fh)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
