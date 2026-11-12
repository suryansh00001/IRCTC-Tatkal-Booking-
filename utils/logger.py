# utils/logger.py — Colored, file+console logger (colorlog optional)

import logging
import os
from config.settings import LOG_DIR, LOG_FILE, LOG_LEVEL

os.makedirs(LOG_DIR, exist_ok=True)

# colorlog is optional — graceful fallback to standard logging
try:
    import colorlog
    COLORLOG_AVAILABLE = True
except ImportError:
    COLORLOG_AVAILABLE = False


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

    # ── Console handler ──
    console = logging.StreamHandler()
    if COLORLOG_AVAILABLE:
        console.setFormatter(colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] %(levelname)-8s%(reset)s %(blue)s%(name)s%(reset)s — %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG":    "cyan",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            }
        ))
    else:
        console.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
            datefmt="%H:%M:%S"
        ))
    logger.addHandler(console)

    # ── File handler ──
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not open log file: {e}")

    return logger
