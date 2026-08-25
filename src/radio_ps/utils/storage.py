"""
utils/storage.py - Persistent JSON storage (favorites, recent, session).
All data files stored in %APPDATA%\\PowerShellRadioPro (override with
RADIO_PS_DATA_DIR). All writes are atomic (tmp + os.replace) to prevent
corruption. Legacy data written into the old in-package location is
migrated once on first load.
"""

from __future__ import annotations

import json
import os
import shutil

from radio_ps.utils.logger import log
from radio_ps.utils.paths import get_app_data_dir

MAX_RECENT = 20


def get_data_dir() -> str:
    return get_app_data_dir()


def _file(name: str) -> str:
    d = get_app_data_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def fav_file() -> str:
    return _file("favorites.json")


def recent_file() -> str:
    return _file("recent.json")


def session_file() -> str:
    return _file("session.json")


_migrated = False


def _ensure_migrated() -> None:
    """One-time migration of JSON data from the legacy in-package location."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    # Legacy dir was <pkg>/radio_ps derived from this file's old parents.
    here = os.path.dirname(os.path.abspath(__file__))
    legacy = os.path.normpath(os.path.join(here, "..", "..", "radio_ps"))
    for name in ("favorites.json", "recent.json", "session.json"):
        dst = _file(name)
        src = os.path.join(legacy, name)
        try:
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copyfile(src, dst)
                log(f"Migrated {name} from {legacy}", "info")
        except OSError as e:
            log(f"Migration of {name} failed: {e}", "warning")


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
    _ensure_migrated()
    path = fav_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
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
    return _atomic_write(fav_file(), data)


# Recently Played

def load_recent() -> list[dict]:
    _ensure_migrated()
    path = recent_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict) and d.get("url")][:MAX_RECENT]
    except Exception as e:
        log(f"Could not load recent: {e}", "debug")
        return []


def save_recent(data: list[dict]) -> bool:
    return _atomic_write(recent_file(), data[:MAX_RECENT])


# Session

def load_session() -> dict:
    _ensure_migrated()
    defaults = {"volume": 70, "last_station": None}
    path = session_file()
    if not os.path.exists(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else defaults
    except Exception as e:
        log(f"Could not load session: {e}", "warning")
        return defaults


def save_session(volume: int, last_station: dict | None) -> bool:
    return _atomic_write(session_file(), {"volume": volume, "last_station": last_station})
