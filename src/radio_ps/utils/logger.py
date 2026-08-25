"""
utils/logger.py - Rotating file logger.
All logs are always auto-saved to radio_log.txt in the app data folder
(%APPDATA%\\PowerShellRadioPro, override with RADIO_PS_DATA_DIR).
Handler is created lazily on first log call; if the data directory is
unwritable the app keeps running without file logging.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from radio_ps.utils.paths import get_app_data_dir

_logger = logging.getLogger("radio_ps")
_logger.setLevel(logging.DEBUG)


def _log_file() -> str:
    return os.path.join(get_app_data_dir(), "radio_log.txt")


def _ensure_handler() -> None:
    if _logger.handlers:
        return
    try:
        os.makedirs(get_app_data_dir(), exist_ok=True)
        fh = RotatingFileHandler(
            _log_file(), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)-7s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        _logger.addHandler(fh)
    except OSError:
        # No writable data dir - drop messages instead of crashing the app.
        _logger.addHandler(logging.NullHandler())


def log(msg: str, level: str = "info") -> None:
    """Log at the given level: info / warning / error / debug."""
    _ensure_handler()
    getattr(_logger, level, _logger.info)(msg)


def get_log_path() -> str:
    return _log_file()
