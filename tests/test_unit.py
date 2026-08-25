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


# ── UI helpers: country shortening & EQ fuzzy match ─────────────────────────

def test_short_country_aliases_and_truncation():
    from radio_ps.ui.cli_ui import _short_country

    assert _short_country("The United States") == "USA"
    assert _short_country("Russian Federation") == "Russia"
    assert _short_country("Germany") == "Germany"
    assert _short_country("") == ""
    assert len(_short_country("A Very Long Country Name Indeed")) <= 14


def test_match_preset_fuzzy():
    from radio_ps.core.equalizer import Equalizer
    from radio_ps.ui.cli_ui import _match_preset

    presets = Equalizer.PRESETS
    assert _match_preset("bass", presets) == "Bass Boost"
    assert _match_preset("JAZZ", presets) == "Jazz"
    assert _match_preset("treble", presets) == "Treble Boost"
    assert _match_preset("vocal", presets) == "Vocal Boost"
    assert _match_preset("doesnotexist", presets) is None


def test_alive_filter_skips_empty_urls(data_dir):
    # Hardening: stations without a URL must never reach liveness checks.
    from radio_ps.services import station_service as ss

    ss._cache.clear()
    orig = ss.is_station_alive
    ss.is_station_alive = lambda s: True  # even a "yes-man" can't revive these
    try:
        out = ss.filter_alive_stations([
            {"name": "bad", "url": ""},
            {"name": "ok", "url": "http://x/stream"},
        ])
        assert [s["url"] for s in out] == ["http://x/stream"]
    finally:
        ss.is_station_alive = orig


# ── Artwork renderer (sextant) ────────────────────────────────────────────────

def test_sextant_table_covers_all_64_masks():
    from radio_ps.ui.art import _SEX_CHAR

    assert len(_SEX_CHAR) == 64
    assert len(set(_SEX_CHAR.values())) == 64          # bijective
    assert _SEX_CHAR[0b000000] == " "
    assert _SEX_CHAR[0b111111] == "\u2588"             # FULL BLOCK
    assert _SEX_CHAR[0b010101] == "\u258c"             # LEFT HALF
    assert _SEX_CHAR[0b101010] == "\u2590"             # RIGHT HALF
    for ch in _SEX_CHAR.values():
        assert len(ch) == 1


def test_sextant_bits_match_mask_layout():
    # bit i = sub-position i+1, numbered UL,UR,ML,MR,LL,LR (row-major 2 wide)
    from radio_ps.ui.art import _SEX_BITS

    assert _SEX_BITS[0b000001] == [True, False, False, False, False, False]  # UL
    assert _SEX_BITS[0b000010] == [False, True, False, False, False, False]  # UR
    assert _SEX_BITS[0b001100] == [False, False, True, True, False, False]   # mid row
    assert _SEX_BITS[0b110000] == [False, False, False, False, True, True]   # bottom row


def _solid_canvas(rgb, size=(48, 48)):
    from PIL import Image

    return Image.new("RGB", size, rgb)


def test_render_sextant_solid_color_uses_full_block():
    from radio_ps.ui.art import _render_sextant

    art = _render_sextant(_solid_canvas((200, 50, 50)))
    lines = art.plain.splitlines()
    assert len(lines) == 16                             # 48px tall -> 16 sextant rows
    assert set(lines[0]) == {"\u2588"}                  # solid -> full blocks everywhere


def test_render_half_fallback_shape():
    from radio_ps.ui.art import _render_half

    art = _render_half(_solid_canvas((10, 200, 10)))
    assert set(art.plain.splitlines()[0]) == {"\u2580"}  # half-block upper


def test_monogram_deterministic_and_contains_initials():
    from radio_ps.ui.art import _monogram

    a = _monogram("Alpha Beta FM")
    b = _monogram("Alpha Beta FM")
    assert a.plain == b.plain
    assert "A" in a.plain and "B" in a.plain


def test_badge_color_stable_across_processes():
    # Regression: badge colors must not use salted str hash(), which changes
    # every process. CRC-32 of the name bytes is stable across restarts.
    import zlib

    from radio_ps.ui.art import _PALETTE, _badge_color

    assert _badge_color("") == _PALETTE[zlib.crc32(b"") % len(_PALETTE)]
    for name in ("Alpha Beta FM", "Radio City", "Жанна FM"):
        expected = _PALETTE[zlib.crc32(name.encode("utf-8")) % len(_PALETTE)]
        assert _badge_color(name) == expected


def test_map_station_rejects_unsafe_records():
    from radio_ps.core.api import _map_station

    good = {
        "name": "  Test FM ",
        "url_resolved": "http://example.com/stream",
        "favicon": "",
        "country": " Germany ",
        "tags": "pop",
        "bitrate": 128,
        "votes": 5,
        "codec": "MP3",
    }
    st = _map_station(good)
    assert st is not None
    assert st["name"] == "Test FM"
    assert st["country"] == "Germany"
    assert st["url"] == "http://example.com/stream"
    # Missing / unsafe URLs must be dropped entirely
    assert _map_station({"url": ""}) is None
    assert _map_station({"url": "javascript:alert(1)"}) is None
    # Falls back to plain url when url_resolved absent
    assert _map_station({"name": "x", "url": "https://a.y/s"})["url"] == "https://a.y/s"


def test_version_single_source_of_truth():
    import radio_ps
    from radio_ps.main import __version__ as main_ver
    from radio_ps.ui import cli_ui

    assert main_ver == radio_ps.__version__
    assert cli_ui._APP_VER == radio_ps.__version__
    assert isinstance(radio_ps.__version__, str) and radio_ps.__version__


def test_station_cache_survives_restart(data_dir):
    # The category cache must persist to disk and come back on next launch.
    from radio_ps.services import station_service as ss

    ss._cache.clear()
    ss._disk_loaded = False
    cached = [{"url": "http://persist", "name": "Persist FM", "bitrate": 128}]
    ss._cache["top"] = (time.time(), [dict(cached[0])])
    ss._save_cache_disk()

    ss._cache.clear()          # simulate a process restart
    ss._disk_loaded = False
    out = ss.fetch_category("top")     # cache hit → no network
    assert out == cached


def test_refresh_backoff_grows_and_caps():
    from radio_ps.core.config import REFRESH_INTERVAL
    from radio_ps.services.station_service import _next_refresh_interval as nxt

    assert nxt(0) == float(REFRESH_INTERVAL)
    assert nxt(-3) == float(REFRESH_INTERVAL)   # negative streak guarded
    assert nxt(1) == float(REFRESH_INTERVAL) * 2
    assert nxt(99) == 3600.0                    # capped at 1 hour


def test_prep_image_outputs_exact_grid():
    from PIL import Image
    from radio_ps.ui.art import _prep_image, _PX_W, _PX_H

    img = Image.new("RGB", (37, 11), (120, 40, 200))
    canvas = _prep_image(img)
    assert canvas.size == (_PX_W, _PX_H) == (48, 48)


def test_art_mode_env_override_switches_renderer(monkeypatch):
    import io as _io

    from PIL import Image
    from radio_ps.ui import art

    buf = _io.BytesIO()
    Image.new("RGB", (50, 50), (9, 99, 200)).save(buf, "PNG")
    monkeypatch.setattr(art, "fetch_logo", lambda u: buf.getvalue())
    monkeypatch.setenv("RADIO_PS_ART", "half")
    half = art.render_logo("u", "X").plain.splitlines()
    assert len(half) == 16 and set(half[0]) == {"\u2580"}
    monkeypatch.setenv("RADIO_PS_ART", "sextant")
    sex = art.render_logo("u", "X").plain.splitlines()
    assert len(sex) == 16 and len(sex[0]) == 24


def test_render_logo_falls_back_to_monogram_on_bad_image(monkeypatch):
    from radio_ps.ui import art

    monkeypatch.setattr(art, "fetch_logo", lambda u: b"not-an-image")
    out = art.render_logo("u", "Alpha Beta")
    assert "A" in out.plain and "B" in out.plain


# ── Sixel encoder ─────────────────────────────────────────────────────────────

def test_sixel_encode_structure():
    from PIL import Image

    from radio_ps.ui.sixel import encode

    img = Image.new("RGB", (12, 12), (255, 0, 0))
    out = encode(img)
    assert out.startswith("\x1bPq") and out.endswith("\x1b\\")
    assert '"1;1;12;12' in out                 # raster attrs carry size
    assert "#0;2;100;0;0" in out               # red defined on 0-100 scale


def test_sixel_height_not_multiple_of_six():
    from PIL import Image

    from radio_ps.ui.sixel import encode

    out = encode(Image.new("RGB", (6, 7), (0, 255, 0)))
    body = out[len("\x1bPq"):out.index("\x1b\\")]
    assert body.count("-") == 1


def test_art_mode_env_parsing(monkeypatch):
    from radio_ps.ui.art import art_mode

    monkeypatch.setenv("RADIO_PS_ART", "sixel")
    assert art_mode() == "sixel"
    monkeypatch.setenv("RADIO_PS_ART", "half")
    assert art_mode() == "half"
    monkeypatch.setenv("RADIO_PS_ART", "junk")
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert art_mode() == "half"
    monkeypatch.setenv("WT_SESSION", "x")
    assert art_mode() == "sextant"
    monkeypatch.delenv("RADIO_PS_ART")
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert art_mode() == "half"
    monkeypatch.setenv("WT_SESSION", "x")
    assert art_mode() == "sextant"


def test_render_sixel_returns_sequence(monkeypatch):
    import io as _io

    from PIL import Image
    from radio_ps.ui import art

    buf = _io.BytesIO()
    Image.new("RGB", (40, 40), (10, 10, 240)).save(buf, "PNG")
    monkeypatch.setattr(art, "fetch_logo", lambda u: buf.getvalue())
    out = art.render_sixel("u")
    assert out is not None and out.startswith("\x1bPq")


def test_render_sixel_none_without_logo(monkeypatch):
    from radio_ps.ui import art

    monkeypatch.setattr(art, "fetch_logo", lambda u: None)
    assert art.render_sixel("u") is None


# ── CLI screen clearing ──────────────────────────────────────────────────────

def _fake_cli(is_terminal):
    import io

    from rich.console import Console
    from radio_ps.ui import cli_ui

    cli = cli_ui.RadioCLI.__new__(cli_ui.RadioCLI)
    cli._console = Console(
        file=io.StringIO(), force_terminal=is_terminal, color_system=None
    )
    return cli


def test_clear_screen_uses_native_clear(monkeypatch):
    # On a real terminal the platform clear command must be invoked.
    import os

    from radio_ps.ui import cli_ui

    cli = _fake_cli(is_terminal=True)
    calls = []
    monkeypatch.setattr(cli_ui.os, "system", lambda cmd: calls.append(cmd) or 0)
    cli._clear_screen()
    expected = "cls" if os.name == "nt" else "clear"
    assert calls == [expected]


def test_clear_screen_noop_without_terminal(monkeypatch):
    # Pipes/tests must never shell out to cls/clear.
    from radio_ps.ui import cli_ui

    cli = _fake_cli(is_terminal=False)
    calls = []
    monkeypatch.setattr(cli_ui.os, "system", lambda cmd: calls.append(cmd) or 0)
    cli._clear_screen()
    assert calls == []
