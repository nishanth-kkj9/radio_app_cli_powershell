"""
core/api.py — Radio Browser API client (multi-mirror, retry, Windows-compatible)
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse

from core.config import API_TIMEOUT, ALLOWED_STREAM_SCHEMES
from utils.logger import log

# Public Radio Browser mirrors — tried in order
API_HOSTS = [
    "https://de1.api.radio-browser.info",
    "https://fr1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
]

USER_AGENT = "PowerShellRadioPro/2.0 (Windows; python-vlc)"

_BAD_FAVICON = {"", "null", "none", "undefined", "false", "0"}

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT})
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        _session.mount("http://",  adapter)
        _session.mount("https://", adapter)
    return _session


def is_safe_url(url: str) -> bool:
    """Return True only if URL uses an allowed streaming scheme with a real host."""
    try:
        p = urlparse(url)
        return p.scheme in ALLOWED_STREAM_SCHEMES and bool(p.netloc)
    except Exception:
        return False


def _clean_favicon(raw: str) -> str:
    """Sanitize a favicon URL from Radio Browser API."""
    if not raw:
        return ""
    url = raw.strip()
    if url.lower() in _BAD_FAVICON:
        return ""
    # Fix doubled URLs: e.g., "https://...https://..."
    last_https = url.rfind("https://", 1)
    last_http  = url.rfind("http://",  1)
    last_pos   = max(last_https, last_http)
    if last_pos > 0:
        url = url[last_pos:]
    try:
        p = urlparse(url)
        if p.scheme in ("http", "https") and p.netloc:
            return url
    except Exception:
        pass
    return ""


def _get(path: str, params: dict, timeout: int = API_TIMEOUT) -> list:
    """Try each API mirror; return parsed JSON list or [] on failure."""
    last_err = None
    for host in API_HOSTS:
        try:
            r = _get_session().get(
                f"{host}{path}",
                params=params,
                timeout=(4, timeout),
                verify=True,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            continue
    log(f"API failed on all mirrors: {last_err}", "error")
    return []


def fetch_stations(query: str, limit: int = 30) -> list[dict]:
    """Search stations by name; return sanitized list of station dicts."""
    try:
        data = _get(
            "/json/stations/search",
            {
                "name":       query,
                "limit":      limit,
                "hidebroken": "true",
                "order":      "clickcount",
                "reverse":    "true",
            },
        )
        stations = []
        for s in data:
            stream_url = s.get("url_resolved") or s.get("url", "")
            if not stream_url or not is_safe_url(stream_url):
                continue
            stations.append({
                "name":    s.get("name", "Unknown").strip(),
                "url":     stream_url,
                "logo":    _clean_favicon(s.get("favicon", "")),
                "country": s.get("country", "").strip(),
                "tags":    s.get("tags",    "").strip(),
                "bitrate": s.get("bitrate", 0),
                "votes":   s.get("votes",   0),
                "codec":   s.get("codec",   "").strip(),
            })
        return stations
    except Exception as e:
        log(f"API fetch error for '{query}': {e}", "error")
        return []


def fetch_stations_by_tag(tag: str, limit: int = 30) -> list[dict]:
    """Fetch stations by genre tag (more accurate than name search for genres)."""
    try:
        data = _get(
            "/json/stations/bytag/" + tag,
            {
                "limit":      limit,
                "hidebroken": "true",
                "order":      "clickcount",
                "reverse":    "true",
            },
        )
        stations = []
        for s in data:
            stream_url = s.get("url_resolved") or s.get("url", "")
            if not stream_url or not is_safe_url(stream_url):
                continue
            stations.append({
                "name":    s.get("name", "Unknown").strip(),
                "url":     stream_url,
                "logo":    _clean_favicon(s.get("favicon", "")),
                "country": s.get("country", "").strip(),
                "tags":    s.get("tags",    "").strip(),
                "bitrate": s.get("bitrate", 0),
                "votes":   s.get("votes",   0),
                "codec":   s.get("codec",   "").strip(),
            })
        return stations
    except Exception as e:
        log(f"API tag fetch error for '{tag}': {e}", "error")
        return []
