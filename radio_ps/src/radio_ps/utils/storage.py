"""
utils/storage.py - Persistent JSON storage (favorites, recent, session).
All data files stored in the radio_ps data folder.
All writes are atomic (write-to-tmp + os.replace) to prevent corruption.
"""

from __future__ import annotations

import json
import os
from radio_ps.utils.logger import log

# Storage directory - derived from this file's location
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "radio_ps")
os.makedirs(_DATA_DIR, exist_ok=True)

FAV_FILE     = os.path.join(_DATA_DIR, "favorites.json")
RECENT_FILE  = os.path.join(_DATA_DIR, "recent.json")
SESSION_FILE = os.path.join(_DATA_DIR, "session.json")

MAX_RECENT = 20


# Atomic write helper

def _atomic_write(path: str, data) -> bool:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError as e:
        log(f"Failed to write {path}: {e}", "error")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


# Favorites

def load_favorites() -> list[dict]:
    if not os.path.exists(FAV_FILE):
        return []
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        if data and isinstance(data[0], str):
            return [
                {"name": "Saved Station", "url": u, "logo": "",
                 "country": "", "tags": "", "bitrate": 0, "votes": 0}
                for u in data if isinstance(u, str) and u
            ]
        return [d for d in data if isinstance(d, dict) and d.get("url")]
    except Exception as e:
        log(f"Could not load favorites: {e}", "warning")
        return []


def save_favorites(data: list[dict]) -> bool:
    return _atomic_write(FAV_FILE, data)


# Recently Played

def load_recent() -> list[dict]:
    if not os.path.exists(RECENT_FILE):
        return []
    try:
        with open(RECENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict) and d.get("url")][:MAX_RECENT]
    except Exception as e:
        log(f"Could not load recent: {e}", "debug")
        return []


def save_recent(data: list[dict]) -> bool:
    return _atomic_write(RECENT_FILE, data[:MAX_RECENT])


# Session

def load_session() -> dict:
    defaults = {"volume": 70, "last_station": None}
    if not os.path.exists(SESSION_FILE):
        return defaults
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else defaults
    except Exception as e:
        log(f"Could not load session: {e}", "warning")
        return defaults


def save_session(volume: int, last_station: dict | None) -> bool:
    return _atomic_write(SESSION_FILE, {"volume": volume, "last_station": last_station})


# Data directory info

def get_data_dir() -> str:
    return _DATA_DIR