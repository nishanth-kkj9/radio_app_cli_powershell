"""
utils/logger.py - Rotating file logger.
All logs are always auto-saved to radio_log.txt in the project folder.
No log command in UI - everything goes directly to the log file.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# Fixed log directory - same as data dir
_LOG_DIR  = os.path.join("E:\\", "radio_app_cli_powershell", "radio_ps")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "radio_log.txt")

_logger = logging.getLogger("radio_ps")

if not _logger.handlers:
    _logger.setLevel(logging.DEBUG)
    _fh = RotatingFileHandler(
        _LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    _fh.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)-7s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    _logger.addHandler(_fh)


def log(msg: str, level: str = "info") -> None:
    """Log at the given level: info / warning / error / debug."""
    getattr(_logger, level, _logger.info)(msg)


def get_log_path() -> str:
    return _LOG_FILE
