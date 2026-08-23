"""Pure unit tests: equalizer, api sanitizers, storage. No network, no UI."""

import time

import pytest


# ── Equalizer ──────────────────────────────────────────────────────────────

def test_eq_preset_bass_boost():
    from radio_ps.core.equalizer import Equalizer

    eq = Equalizer()
    eq.set_preset("Bass Boost")
    bands = eq.get_bands()
    assert bands[0] == 15 and bands[1] == 12 and bands[2] == 10


def test_eq_case_insensitive_preset():
    from radio_ps.core.equalizer import Equalizer

    eq = Equalizer()
    eq.set_preset("jazz")
    assert eq.current_preset == "Jazz"
    assert eq.get_bands() != [0.0] * 10


def test_eq_unknown_preset_rejected():
    from radio_ps.core.equalizer import Equalizer

    with pytest.raises(ValueError):
        Equalizer().resolve_preset("doesnotexist")


def test_eq_custom_bands_clamped():
    from radio_ps.core.equalizer import Equalizer

    eq = Equalizer()
    eq.set_custom_bands([50.0] + [0.0] * 9)
    assert eq.get_bands()[0] == 20.0


def test_eq_summary_flat():
    from radio_ps.core.equalizer import Equalizer

    assert Equalizer().get_summary() == "(flat)"


# ── api.py sanitizers ──────────────────────────────────────────────────────

def test_is_safe_url_allows_http_https():
    from radio_ps.core.api import is_safe_url

    assert is_safe_url("https://example.com/stream") is True
    assert is_safe_url("http://example.com/stream") is True


def test_is_safe_url_blocks_bad_schemes_and_hosts():
    from radio_ps.core.api import is_safe_url

    assert is_safe_url("ftp://example.com/x") is False
    assert is_safe_url("javascript:alert(1)") is False
    assert is_safe_url("https://") is False
    assert is_safe_url("") is False


def test_clean_favicon_doubled_url():
    from radio_ps.core.api import _clean_favicon

    raw = "https://a.com/icon.pnghttps://b.com/real.ico"
    assert _clean_favicon(raw) == "https://b.com/real.ico"


def test_clean_favicon_junk_values():
    from radio_ps.core.api import _clean_favicon

    for junk in ("", "null", "none", "undefined", "false", "0", "not a url"):
        assert _clean_favicon(junk) == ""


# ── storage round-trips (isolated data dir from fixture) ───────────────────

def test_favorites_round_trip(data_dir):
    from radio_ps.utils.storage import load_favorites, save_favorites

    favs = [{"name": "X", "url": "http://x", "bitrate": 128}]
    assert save_favorites(favs) is True
    assert load_favorites() == favs


def test_legacy_string_list_favorites(data_dir):
    import json
    import os

    from radio_ps.utils import storage
    from radio_ps.utils.paths import get_app_data_dir

    os.makedirs(get_app_data_dir(), exist_ok=True)
    path = os.path.join(get_app_data_dir(), "favorites.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(["http://a", "http://b"], f)
    favs = storage.load_favorites()
    assert [f["url"] for f in favs] == ["http://a", "http://b"]


def test_session_round_trip(data_dir):
    from radio_ps.utils.storage import load_session, save_session

    save_session(33, {"url": "http://s", "name": "S"})
    session = load_session()
    assert session["volume"] == 33
    assert session["last_station"]["url"] == "http://s"


# ── station_service cache preservation ─────────────────────────────────────

def test_cache_preserved_on_empty_fetch(data_dir, monkeypatch):
    from radio_ps.services import station_service as ss

    ss._cache.clear()
    cached = [{"url": "http://keep", "name": "Keep"}]
    ss._cache["top"] = (time.time(), list(cached))
    monkeypatch.setattr(ss, "_fetch_fresh", lambda cat, filter_alive: [])
    out = ss.fetch_category("top")
    assert out == cached
