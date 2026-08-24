"""utils/paths.py - Shared data directory resolution.

All persistent app data (favorites, recent, session, log, recordings)
lives under %APPDATA%\\PowerShellRadioPro. Override with RADIO_PS_DATA_DIR
(mainly for tests and portable installs).
"""

from __future__ import annotations

import os


def get_app_data_dir() -> str:
    override = os.environ.get("RADIO_PS_DATA_DIR")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PowerShellRadioPro")


def get_recordings_dir() -> str:
    return os.path.join(get_app_data_dir(), "recordings")
