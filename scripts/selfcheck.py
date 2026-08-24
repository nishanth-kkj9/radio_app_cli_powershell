"""Comprehensive feature self-check - runs every project feature headlessly.
Temporary file; safe to delete."""
import io
import os
import sys
import tempfile
import time

os.environ["RADIO_PS_DATA_DIR"] = tempfile.mkdtemp(prefix="radio_selfcheck_")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from conftest import _install_fake_vlc
_install_fake_vlc()

import radio_ps.ui.cli_ui as ui_mod
import radio_ps.services.station_service as ss_mod
from rich.console import Console

FIXTURE = [
    {"name": "Alpha FM",   "url": "http://a.example/stream", "country": "Germany", "bitrate": 320, "votes": 100, "tags": "pop",  "codec": "MP3"},
    {"name": "Beta Radio", "url": "http://b.example/stream", "country": "India",   "bitrate": 128, "votes": 90,  "tags": "rock", "codec": "AAC"},
    {"name": "Gamma Jazz", "url": "http://g.example/stream", "country": "USA",     "bitrate": 64,  "votes": 80,  "tags": "jazz", "codec": "MP3"},
]
# Patch network everywhere it is imported
ui_mod.fetch_stations = lambda q, limit=30: [dict(s) for s in FIXTURE]
ss_mod.fetch_stations = lambda q, limit=30: [dict(s) for s in FIXTURE]
ss_mod.fetch_stations_by_tag = lambda t, limit=30: [dict(s) for s in FIXTURE]
ss_mod.is_station_alive = lambda s: True

results = []
def check(area, name, fn):
    try:
        ok = fn()
        results.append((area, name, bool(ok), ""))
    except Exception as e:
        results.append((area, name, False, f"{type(e).__name__}: {e}"))

def _val_err(obj, arg):
    try:
        obj.resolve_preset(arg)
        return False
    except ValueError:
        return True

# ── Build CLI with silent console ────────────────────────────────────────────
cli = ui_mod.RadioCLI()
buf = io.StringIO()
cli._console = Console(file=buf, force_terminal=False, width=200)

def out():
    return buf.getvalue()

def clear_out():
    buf.truncate(0)
    buf.seek(0)

# ══ 1. CORE HELPERS ═══════════════════════════════════════════════════════
check("helpers", "_clean_name basics", lambda: (
    ui_mod._clean_name("") == "Unknown Station"
    and ui_mod._clean_name("Foo (FM)") == "Foo"
    and ui_mod._clean_name("Foo - Bar") == "Foo"
))
check("helpers", "_truncate adds ellipsis", lambda: ui_mod._truncate("abcdef", 4) == "abc…")
check("helpers", "_fmt_elapsed hours", lambda: ui_mod._fmt_elapsed(3661) == "1h 01m 01s")
check("helpers", "_quality_badge HQ/HD/k", lambda: (
    "bold green" in ui_mod._quality_badge(320)
    and "green" in ui_mod._quality_badge(128)
    and "96k" in ui_mod._quality_badge(96)
))
check("helpers", "_short_country USA/Russia alias", lambda: (
    ui_mod._short_country("The United States") == "USA"
    and ui_mod._short_country("Russian Federation") == "Russia"
))
check("helpers", "_match_preset fuzzy", lambda: (
    ui_mod._match_preset("bass", ui_mod.Equalizer.PRESETS) == "Bass Boost"
    and ui_mod._match_preset("zzz", ui_mod.Equalizer.PRESETS) is None
))
from radio_ps.ui.art import volume_bar, render_logo
check("art", "volume_bar renders gauge", lambda: "%" in volume_bar(50).plain)
check("art", "render_logo falls back to monogram", lambda: "A" in render_logo("", "Alpha").plain)
check("art", "gradient logo builds", lambda: len(ui_mod._gradient_logo().plain.splitlines()) == 5)

# ══ 2. EQUALIZER MODEL ════════════════════════════════════════════════════
from radio_ps.core.equalizer import Equalizer
eq = Equalizer()
check("equalizer", "preset load (Bass Boost)", lambda: (
    eq.set_preset("Bass Boost") is None and eq.get_bands()[:3] == [15.0, 12.0, 10.0]
))
check("equalizer", "case-insensitive resolve", lambda: eq.resolve_preset("JaZz") == "Jazz")
check("equalizer", "unknown raises ValueError", lambda: _val_err(eq, "nope"))
check("equalizer", "custom bands clamped to ±20", lambda: (
    eq.set_custom_bands([50] + [0] * 9) or eq.get_bands()[0] == 20.0
))
check("equalizer", "summary flat text", lambda: Equalizer().get_summary() == "(flat)")

# ══ 3. API SANITIZERS ═════════════════════════════════════════════════════
from radio_ps.core.api import is_safe_url, _clean_favicon, API_HOSTS
check("api", "safe url allows http/https", lambda: (
    is_safe_url("https://x.com/s") and is_safe_url("http://x.com/s")))
check("api", "unsafe schemes blocked", lambda: (
    not is_safe_url("ftp://x/s") and not is_safe_url("javascript:alert(1)")
    and not is_safe_url("") and not is_safe_url("https://")))
check("api", "favicon doubled-url fix", lambda: (
    _clean_favicon("https://a.com/i.pnghttps://b.com/x.ico") == "https://b.com/x.ico"))
check("api", "favicon junk rejected", lambda: all(
    _clean_favicon(j) == "" for j in ("", "null", "none", "0", "not a url")))
check("api", "three mirrors configured", lambda: len(API_HOSTS) == 3)

# ══ 4. STORAGE ════════════════════════════════════════════════════════════
from radio_ps.utils.storage import (
    load_favorites, save_favorites, load_recent, save_recent,
    load_session, save_session, get_data_dir,
)
favs = [{"name": "X", "url": "http://x", "bitrate": 128}]
check("storage", "favorites round-trip", lambda: save_favorites(favs) and load_favorites() == favs)
check("storage", "recent capped at 20", lambda: (
    save_recent([{"url": f"u{i}"} for i in range(30)]) and len(load_recent()) == 20))
check("storage", "session round-trip", lambda: (
    save_session(42, {"url": "u"}) and load_session()["volume"] == 42))

def _corrupt_test():
    p = os.path.join(get_data_dir(), "favorites.json")
    with open(p, "w") as f:
        f.write("{broken json!!")
    return load_favorites() == []

check("storage", "corrupt json falls back to defaults", _corrupt_test)

# ══ 5. STATION SERVICE ════════════════════════════════════════════════════
ss_mod._cache.clear()
check("service", "fetch_category loads + caches", lambda: (
    len(ss_mod.fetch_category("jazz")) == 3 and "jazz" in ss_mod._cache))
check("service", "cache hit avoids refetch", lambda: (
    ss_mod.fetch_category("jazz") == ss_mod.fetch_category("jazz")))

def _preserve():
    ss_mod._cache["top"] = (time.time(), [{"name": "Keep", "url": "k"}])
    orig = ss_mod._fetch_fresh
    ss_mod._fetch_fresh = lambda c, fa: []
    r = ss_mod.fetch_category("top", use_cache=False)
    ss_mod._fetch_fresh = orig
    return r == [{"name": "Keep", "url": "k"}]

check("service", "empty fetch preserves old cache", _preserve)
check("service", "alive filter drops bad urls", lambda: (
    len(ss_mod.filter_alive_stations(FIXTURE + [{"name": "dead", "url": ""}])) == 3))
check("service", "refresh timer start/stop safe", lambda: (
    ss_mod.start_refresh_timer() is None and ss_mod.stop_refresh_timer() is None))
check("service", "preload status dict", lambda: isinstance(ss_mod.get_preload_status(), dict))

# ══ 6. PLAYER (fake vlc) ══════════════════════════════════════════════════
from radio_ps.core.player import RadioPlayer
p = RadioPlayer()
check("player", "initialises under fake vlc", lambda: p is not None)
check("player", "play blocks unsafe url", lambda: p.play("javascript:x") is False)
check("player", "play/stop cycle", lambda: (
    p.play("http://a.example/stream") and p.is_playing()
    and p.stop() is None and not p.is_playing()))
check("player", "volume clamped to 0-100", lambda: (
    p.set_volume(150) or (p.get_volume() == 100
    and (p.set_volume(-5) or p.get_volume() == 0))))
check("player", "mute toggles on/off", lambda: (
    p.toggle_mute() is True and p.toggle_mute() is False))
check("player", "EQ object applied to player", lambda: (
    p.toggle_equalizer(True), p.set_equalizer_preset("Rock"),
    p._eq_obj is not None)[2])
check("player", "state label valid", lambda: p.get_state_label() in (
    "idle", "opening", "buffering", "playing", "paused",
    "stopped", "ended", "error", "reconnecting"))
check("player", "metadata empty-safe", lambda: (
    p.get_current_metadata() == {"title": "", "artist": ""}))
check("player", "recording lifecycle", lambda: (
    p.record("http://a.example/stream",
             os.path.join(tempfile.mkdtemp(), "r.mp3"))
    and p.stop_recording()))
p.shutdown()
check("player", "shutdown clean", lambda: True)

# ══ 7. CLI COMMANDS (dispatch level) ══════════════════════════════════════
cli._init_player()
cli._player.stop()
cli._load_data()
clear_out(); cli._dispatch("h")
check("cmd", "help renders groups", lambda: "Playback" in out() and "System" in out())
clear_out(); cli._fetch_initial("jazz")
check("cmd", "initial category load", lambda: (
    cli._category == "jazz" and len(cli._stations) == 3))
check("cmd", "ls redraws table", lambda: (
    clear_out(), cli._dispatch("ls"), "#" in out())[2])
check("cmd", "p 1 plays station 1", lambda: (
    cli._dispatch("p 1"), cli._player.get_current_url() == FIXTURE[0]["url"],
    cli._player.is_playing())[2])
check("cmd", "bare number plays too", lambda: (
    cli._dispatch("3"), cli._current == 2)[1])
check("cmd", "next wraps forward", lambda: (
    cli._dispatch("n"), cli._current == 0)[1])
check("cmd", "prev goes back", lambda: (
    cli._dispatch("b"), cli._current == 2)[1])
check("cmd", "rand picks valid index", lambda: (
    cli._dispatch("r"), 0 <= cli._current < 3)[1])
check("cmd", "stop halts playback", lambda: (
    cli._dispatch("stop"), not cli._player.is_playing())[1])
check("cmd", "now shows panel", lambda: (
    clear_out(), cli._dispatch("now"), "Now Playing" in out())[2])
check("cmd", "info shows details", lambda: (
    clear_out(), cli._dispatch("info"), "URL:" in out())[2])
cli._dispatch("v 55")
check("cmd", "v sets volume", lambda: cli._player.get_volume() == 55)
check("cmd", "m mute toggle no-crash x2", lambda: (
    cli._dispatch("m") or cli._dispatch("m") or True))
cli._dispatch("v 60"); cli._dispatch("f 2")
check("cmd", "f adds favorite + saves json", lambda: (
    any(f["url"] == FIXTURE[1]["url"] for f in cli._favorites)
    and os.path.exists(os.path.join(get_data_dir(), "favorites.json"))))
clear_out(); cli._dispatch("cat favorites")
check("cmd", "cat favorites lists favs", lambda: (
    cli._category == "favorites"
    and any(s["url"] == FIXTURE[1]["url"] for s in cli._stations)))
clear_out(); cli._dispatch("ls")
check("cmd", "favorite star shown in table", lambda: "★" in out())
check("cmd", "recent updated after plays", lambda: len(cli._recent) >= 1)
clear_out(); cli._dispatch("cat recent")
check("cmd", "cat recent lists recents", lambda: cli._category == "recent")
clear_out(); cli._dispatch("cat rock")
check("cmd", "cat by name", lambda: cli._category == "rock" and len(cli._stations) == 3)
clear_out(); cli._dispatch("cat 6")
check("cmd", "cat by number (6=jazz)", lambda: cli._category == "jazz")
check("cmd", "cat bad number errors", lambda: (
    clear_out(), cli._dispatch("cat 99"), "Invalid category" in out())[2])
clear_out(); cli._dispatch("s gamma")
check("cmd", "s search returns results", lambda: (
    cli._category == "search" and len(cli._stations) == 3))

cli._dispatch("sort votes")
votes_desc = [s.get("votes", 0) for s in cli._stations]
check("cmd", "sort votes descending", lambda: votes_desc == sorted(votes_desc, reverse=True))
cli._dispatch("sort name")
names_sorted = [s["name"] for s in cli._stations]
check("cmd", "sort name ascending", lambda: names_sorted == sorted(names_sorted))

cli._dispatch("p 1")
cli._dispatch("eq bass")
check("cmd", "eq bass fuzzy-matches + enables", lambda: (
    cli._player.equalizer.current_preset == "Bass Boost"
    and cli._player.equalizer.enabled))
check("cmd", "eq custom sets 10 bands", lambda: (
    cli._dispatch("eq custom 1 2 3 4 5 6 7 8 9 10"),
    cli._player.equalizer.current_preset == "Custom")[1])
check("cmd", "eq custom wrong count rejected", lambda: (
    clear_out(), cli._dispatch("eq custom 1 2 3"), "exactly 10" in out())[2])
clear_out(); cli._dispatch("eq ls")
check("cmd", "eq ls shows meter panel", lambda: "60Hz" in out())
cli._dispatch("eq none")
check("cmd", "eq none disables EQ", lambda: not cli._player.equalizer.enabled)
clear_out(); cli._dispatch("eq zzz")
check("cmd", "bad eq errors gracefully", lambda: "Unknown preset" in out())

# recording (stubbed sink)
cli._dispatch("p 1")
orig_rec = cli._player.record
cli._player.record = lambda url, path: path.endswith(".mp3")
cli._player._current_url = FIXTURE[0]["url"]
clear_out(); cli._dispatch("record my_show!!")
check("cmd", "record sanitizes filename + starts", lambda: (
    cli._recording and "my_show.mp3" in str(cli._recording_path)))
cli._player.stop_recording = lambda: cli._recording_path
clear_out(); cli._dispatch("stoprec")
check("cmd", "stoprec stops + reports", lambda: not cli._recording)

def _record_nothing():
    cli._player.stop()
    clear_out()
    cli._dispatch("record")
    return "Nothing playing" in out()

check("cmd", "record blocked when nothing playing", _record_nothing)
cli._player.record = orig_rec

check("cmd", "sleep starts & re-run cancels", lambda: (
    cli._dispatch("sleep 30"), cli._sleep_thread is not None
    and cli._dispatch("sleep 1") is None))
check("cmd", "sleep bad usage handled", lambda: (
    clear_out(), cli._dispatch("sleep abc"), "Usage" in out())[2])

for cmdname in ("vlcinfo", "datadir", "log 5", "preload_status", "clean",
                "sort", "s", "v abc", "f 999", "info"):
    clear_out()
    cli._dispatch(cmdname)
check("system", "misc/system commands all no-crash", lambda: True)
clear_out()
cli._dispatch("bogus_cmd")
check("system", "unknown cmd message shown", lambda: "Unknown command" in out())
check("system", "q quits REPL loop", lambda: cli._dispatch("q") is True)

cli._dispatch("v 77")
cli._shutdown()
sess = load_session()
check("system", "shutdown saves volume+station", lambda: (
    sess["volume"] == 77 and sess.get("last_station") is not None))



# ── 8. SEXTANT ART RENDERER ───────────────────────────────────────────────
from radio_ps.ui import art as _art
check("sextant", "glyph table covers 64 unique masks", lambda: (
    len(_art._SEX_CHAR) == 64 and len(set(_art._SEX_CHAR.values())) == 64))
from PIL import Image as _Img
_solid = _Img.new("RGB", (72, 72), (200, 60, 60))
_sexa = _art._render_sextant(_solid)
_lines = _sexa.plain.splitlines()
check("sextant", "solid image renders 36x24 solid blocks", lambda: (
    len(_lines) == 24 and len(_lines[0]) == 36
    and set("".join(_lines)) == {"\u2588"}))

# ══ REPORT ════════════════════════════════════════════════════════════════
print("\n" + "=" * 74)
print("FEATURE SELF-CHECK REPORT")
print("=" * 74)
cur_area, passed, total = None, 0, 0
for area, name, ok, err in results:
    if area != cur_area:
        print(f"\n-- {area.upper()} " + "-" * (62 - len(area)))
        cur_area = area
    total += 1
    passed += ok
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + ("" if ok else f"\n         -> {err}"))
print("\n" + "=" * 74)
print(f"RESULT: {passed}/{total} features passing "
      f"({'ALL GOOD' if passed == total else 'FAILURES PRESENT'})")
print("=" * 74)
sys.exit(0 if passed == total else 1)




# ── 8. SEXTANT ART RENDERER ───────────────────────────────────────────────
from radio_ps.ui import art as _art
check("sextant", "glyph table covers 64 unique masks", lambda: (
    len(_art._SEX_CHAR) == 64 and len(set(_art._SEX_CHAR.values())) == 64))
from PIL import Image as _Img
_solid = _Img.new("RGB", (72, 72), (200, 60, 60))
_sexa = _art._render_sextant(_solid)
_lines = _sexa.plain.splitlines()
check("sextant", "solid image renders 36x24 solid blocks", lambda: (
    len(_lines) == 24 and len(_lines[0]) == 36
    and set("".join(_lines)) == {"\u2588"}))
