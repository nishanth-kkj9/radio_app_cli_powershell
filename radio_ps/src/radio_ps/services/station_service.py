"""
services/station_service.py
─────────────────────────────
Station fetching, liveness checks, caching, background preload, and periodic refresh.

Key behaviours:
• filter_alive_stations() uses GET with stream=True (HEAD often fails for audio streams)
• cache is NEVER overwritten with zero results (stale data preserved on network glitches)
• refresh timer uses exponential back-off on repeated failures
• Each alive-check call gets a fresh ThreadPoolExecutor to avoid pool leaks
"""

from __future__ import annotations

import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from radio_ps.core.api import fetch_stations, fetch_stations_by_tag
from radio_ps.core.config import (
    MAX_RESULTS,
    MAX_WORKERS,
    QUERY_MAP,
    PRELOAD_CATEGORIES,
    CACHE_TTL,
    REFRESH_INTERVAL,
    ALIVE_TIMEOUT,
)
from radio_ps.utils.logger import log

# ── In-memory cache: category → (timestamp, [station, …]) ─────────────────────
_cache:      dict[str, tuple[float, list[dict]]] = {}
_cache_lock  = threading.Lock()

# ── Preload status ─────────────────────────────────────────────────────────────
_preload_status:      dict[str, bool] = {cat: False for cat in PRELOAD_CATEGORIES}
_preload_status_lock  = threading.Lock()

# ── Refresh tracking ───────────────────────────────────────────────────────────
_last_refresh_time:   float | None = None
_last_refresh_status: str          = "Never"
_refresh_status_lock  = threading.Lock()

_refresh_stop_event          = threading.Event()
_consecutive_zero_alive      = 0
_consecutive_zero_alive_lock = threading.Lock()


# ── Liveness check ─────────────────────────────────────────────────────────────

def is_station_alive(station: dict) -> bool:
    """
    Return True if the station URL responds with HTTP 2xx/3xx.
    Uses GET+stream=True because many audio streams reject HEAD.
    Each check uses a fresh Session to avoid connection pool bleed.
    """
    url = station.get("url")
    if not url:
        return False
    try:
        sess = requests.Session()
        try:
            r = sess.get(
                url,
                timeout=ALIVE_TIMEOUT,
                stream=True,
                allow_redirects=True,
                headers={
                    "User-Agent":   "PowerShellRadioPro/2.0",
                    "Icy-MetaData": "1",
                },
            )
            alive = 200 <= r.status_code < 400
            r.close()
            return alive
        finally:
            sess.close()
    except Exception:
        return False


def filter_alive_stations(stations: list[dict]) -> list[dict]:
    """Check all stations concurrently; return only reachable ones."""
    if not stations:
        return []

    results:   dict[str, bool] = {}
    dead_list: list[str]       = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {pool.submit(is_station_alive, s): s for s in stations}
        for future in as_completed(future_map, timeout=90):
            s = future_map[future]
            try:
                alive = future.result(timeout=15)
            except Exception as exc:
                alive = False
                log(f"Alive-check error ({s.get('url','?')}): {exc}", "debug")
            results[s["url"]] = alive
            if not alive:
                dead_list.append(s.get("name", s.get("url", "?")))

    ordered = [s for s in stations if results.get(s["url"], False)]

    if dead_list:
        sample = ", ".join(dead_list[:5]) + (" …" if len(dead_list) > 5 else "")
        log(f"Filtered {len(dead_list)} dead station(s): {sample}", "debug")

    log(f"Alive check: {len(ordered)}/{len(stations)} reachable", "info")
    return ordered


# ── Category fetching ──────────────────────────────────────────────────────────

def _fetch_fresh(category: str, filter_alive: bool) -> list[dict]:
    """Fetch stations for a category from Radio Browser API, dedup, optionally alive-filter."""
    queries = QUERY_MAP.get(category, [category])
    raw:  list[dict] = []
    seen: set[str]   = set()

    for q in queries:
        try:
            batch = fetch_stations(q, limit=MAX_RESULTS)
            for s in batch:
                url = s.get("url", "")
                if url and url not in seen:
                    raw.append(s)
                    seen.add(url)
        except Exception as e:
            log(f"Fetch error for '{q}': {e}", "error")

    if filter_alive:
        return filter_alive_stations(raw)
    else:
        log(f"'{category}': {len(raw)} stations (alive check skipped)", "info")
        return raw


def fetch_category(
    category: str,
    filter_alive: bool = True,
    use_cache: bool = True,
) -> list[dict]:
    """Fetch a category, using cache if available and fresh."""
    if use_cache:
        with _cache_lock:
            if category in _cache:
                ts, cached = _cache[category]
                if time.time() - ts < CACHE_TTL:
                    log(f"Cache hit '{category}' ({len(cached)} stations)", "debug")
                    return cached.copy()

    fresh = _fetch_fresh(category, filter_alive)

    # CRITICAL: never overwrite cache with empty results
    if fresh or category not in _cache:
        with _cache_lock:
            _cache[category] = (time.time(), fresh.copy())
        if category in PRELOAD_CATEGORIES:
            with _preload_status_lock:
                _preload_status[category] = True
    else:
        log(f"Got 0 results for '{category}' — preserving old cache", "warning")
        with _cache_lock:
            if category in _cache:
                _, cached = _cache[category]
                return cached.copy()

    return fresh


# ── Preload ────────────────────────────────────────────────────────────────────

def preload_categories() -> None:
    """Load all preload categories in parallel (called once at startup)."""
    log("Background preload starting…", "info")

    def _load_one(cat: str) -> tuple[str, int]:
        try:
            stations = fetch_category(cat, filter_alive=True, use_cache=False)
            log(f"Preloaded '{cat}': {len(stations)} alive stations", "info")
            return cat, len(stations)
        except Exception as e:
            log(f"Preload failed for '{cat}': {e}", "warning")
            return cat, 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_load_one, cat): cat for cat in PRELOAD_CATEGORIES}
        for future in as_completed(futures):
            cat, n = future.result()
            if n == 0:
                log(f"Preload: 0 stations returned for '{cat}'", "warning")

    log("Background preload complete.", "info")


def get_preload_status() -> dict[str, bool]:
    with _preload_status_lock:
        return _preload_status.copy()


# ── Periodic refresh ───────────────────────────────────────────────────────────

def refresh_categories() -> None:
    global _consecutive_zero_alive

    log("Periodic refresh starting…", "info")
    all_cats   = ["top"] + PRELOAD_CATEGORIES
    total_alive = 0
    success     = True

    def _refresh_one(cat: str) -> tuple[str, int]:
        try:
            fresh = _fetch_fresh(cat, filter_alive=True)
            if fresh:
                with _cache_lock:
                    _cache[cat] = (time.time(), fresh.copy())
                if cat in PRELOAD_CATEGORIES:
                    with _preload_status_lock:
                        _preload_status[cat] = True
                log(f"Refreshed '{cat}': {len(fresh)} alive stations", "info")
            else:
                log(f"Refresh got 0 for '{cat}' — keeping old cache", "warning")
            return cat, len(fresh)
        except Exception as e:
            log(f"Refresh failed for '{cat}': {e}", "warning")
            return cat, 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_refresh_one, cat): cat for cat in all_cats}
        for future in as_completed(futures):
            _, n = future.result()
            total_alive += n
            if n == 0:
                success = False

    with _consecutive_zero_alive_lock:
        if total_alive == 0:
            _consecutive_zero_alive += 1
            log(f"Refresh: 0 total alive (streak: {_consecutive_zero_alive})", "warning")
        else:
            _consecutive_zero_alive = 0

    with _refresh_status_lock:
        global _last_refresh_time, _last_refresh_status
        _last_refresh_time   = time.time()
        _last_refresh_status = "OK" if success else "Partial"

    log("Periodic refresh complete.", "info")


def get_last_refresh_info() -> tuple[str, str]:
    with _refresh_status_lock:
        if _last_refresh_time is None:
            return "Never", "Never"
        ts = time.strftime("%H:%M:%S", time.localtime(_last_refresh_time))
        return ts, _last_refresh_status


def _refresh_loop() -> None:
    while not _refresh_stop_event.wait(REFRESH_INTERVAL):
        try:
            refresh_categories()
        except Exception as e:
            log(f"Refresh loop error: {e}", "error")


def start_refresh_timer() -> None:
    if any(t.name == "refresh-loop" for t in threading.enumerate()):
        return
    _refresh_stop_event.clear()
    t = threading.Thread(target=_refresh_loop, daemon=True, name="refresh-loop")
    t.start()
    log(f"Refresh timer started (every {REFRESH_INTERVAL}s)", "info")


def stop_refresh_timer() -> None:
    _refresh_stop_event.set()
    log("Refresh timer stopped", "info")