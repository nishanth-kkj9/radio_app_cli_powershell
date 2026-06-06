"""
ui/cli_ui.py — PowerShell Radio Pro — Rich terminal UI
Windows-native: uses python-vlc, no cava, no WSL2, no Linux tools.

Overlap fix (v3.1):
  • Live object is re-created each REPL iteration — no stale cursor-position resume
  • _sep() helper enforces one blank line before and after every table/panel
  • Rule separator anchors Now Playing panel so it never collides with output above
"""

from __future__ import annotations

import os
import sys
import time
import threading
import queue as _queue
import random as _random
import datetime

try:
    import readline
except ImportError:
    pass

from rich.console import Console
from rich.live    import Live
from rich.table   import Table
from rich.panel   import Panel
from rich.text    import Text
from rich.rule    import Rule
from rich         import box

from core.config   import CATEGORIES, MAX_RESULTS
from core.player   import RadioPlayer
from core.equalizer import Equalizer
from core.api      import fetch_stations
from services.station_service import (
    fetch_category,
    filter_alive_stations,
    preload_categories,
    get_preload_status,
    start_refresh_timer,
    stop_refresh_timer,
    refresh_categories,
    get_last_refresh_info,
)
from utils.storage import (
    load_favorites, save_favorites,
    load_recent,    save_recent,
    load_session,   save_session,
    get_data_dir,
)
from utils.logger import log, get_log_path


# ── Constants ──────────────────────────────────────────────────────────────────

_SPINNER     = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
_AUDIO_DIR   = os.path.join("E:\\", "radio_app_cli_powershell", "radio_audios")
_MAX_MARQUEE = 60
_APP_NAME    = "PowerShell Radio Pro"
_APP_VER     = "2.0"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    if not name:
        return "Unknown Station"
    name = name.strip()
    if "(" in name:
        name = name[: name.index("(")].strip()
    if " - " in name:
        name = name.split(" - ")[0].strip()
    if name.startswith("-"):
        name = name.lstrip("- ").strip()
    return name or "Unknown Station"


def _quality_badge(bitrate: int) -> str:
    if bitrate >= 256: return "[bold green]HQ[/bold green]"
    if bitrate >= 128: return "[green]HD[/green]"
    if bitrate  > 0:   return f"[dim]{bitrate}k[/dim]"
    return ""


def _fmt_elapsed(s: int) -> str:
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}:{s:02d}"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…" if max_len >= 2 else text[:max_len]


# ── RadioCLI ───────────────────────────────────────────────────────────────────

class RadioCLI:
    VALID_CATS = {k for _, k in CATEGORIES} | {"recent"}

    def __init__(self):
        self.console = Console(highlight=False)
        session      = load_session()

        self.player = RadioPlayer(on_permanent_failure=self._on_station_dead)
        self.player.equalizer.set_on_change_callback(self.player._apply_eq)

        self._volume: int = session.get("volume", 70)
        self.player.set_volume(self._volume)

        self.stations:        list[dict]  = []
        self.all_stations:    list[dict]  = []
        self.current_station: dict | None = None
        self.current_cat                  = "top"
        self._station_idx: int            = -1

        self.favorites: list[dict] = load_favorites()
        self._fav_urls: set[str]   = {s["url"] for s in self.favorites}
        self.recent:    list[dict] = load_recent()

        self._muted      = False
        self._play_start = 0.0

        self._sleep_end:   float | None           = None
        self._sleep_timer: threading.Timer | None = None

        self._live_track = ""
        self._meta_stop  = threading.Event()

        self._tick:        int = 0
        self._marquee_off: int = 0

        self._dead_queue: _queue.Queue = _queue.Queue()

        # Live is re-created each REPL iteration — no stale resume
        self._live:        Live | None             = None
        self._anim_stop    = threading.Event()
        self._anim_thread: threading.Thread | None = None

        self._last_station: dict | None = session.get("last_station")

    # ── Spacing helper ─────────────────────────────────────────────────────────

    def _sep(self) -> None:
        """Print exactly one blank line — used before AND after every table/panel."""
        self.console.print()

    # ── Dead-station callback ──────────────────────────────────────────────────

    def _on_station_dead(self, url: str) -> None:
        self._dead_queue.put(url)
        log(f"Dead station queued: {url}", "info")

    def _process_dead_queue(self) -> None:
        while True:
            try:
                url = self._dead_queue.get_nowait()
            except _queue.Empty:
                break
            name = next(
                (_clean_name(s.get("name", "?")) for s in self.stations
                 if s.get("url") == url),
                url,
            )
            log(f"Station permanently failed: {name}", "warning")
            if self.current_station and self.current_station.get("url") == url:
                self.current_station = None
                self._station_idx    = -1
                self._play_start     = 0.0
                self._stop_meta_poll()

    # ── Entry ──────────────────────────────────────────────────────────────────

    def run(self, start_category: str | None = None) -> None:
        self._print_banner()

        cat = start_category if start_category in self.VALID_CATS else "top"
        self.current_cat = cat
        self._load_category(cat, silent=False)

        threading.Thread(target=preload_categories, daemon=True, name="preload").start()
        start_refresh_timer()

        if self._last_station and self._last_station.get("url"):
            self.console.print(
                f"[dim]► Resuming: {_clean_name(self._last_station.get('name',''))}…[/dim]"
            )
            self._play_station(self._last_station, silent=True)

        self._show_stations()
        self._print_help_hint()
        self._repl()

    # ── REPL ───────────────────────────────────────────────────────────────────

    def _repl(self) -> None:
        """
        Main command loop.

        Overlap fix: a FRESH Live object is created every iteration.
        This prevents Rich from trying to move the cursor up to an old
        position and overwriting static output (tables/panels) above.
        """
        self._anim_stop.clear()
        self._anim_thread = threading.Thread(
            target=self._anim_loop, daemon=True, name="anim"
        )
        self._anim_thread.start()

        # Start first Live panel
        self._live = self._make_live()
        self._live.start()

        while True:
            # ── Freeze panel ─────────────────────────────────────────────────
            if self._live:
                try:
                    self._live.stop()
                except Exception:
                    pass
                self._live = None

            # ── Prompt ───────────────────────────────────────────────────────
            try:
                self.console.print()
                self.console.print("[dim]Command (h=help, q=quit):[/dim] ", end="")
                raw = input().strip()
            except (KeyboardInterrupt, EOFError):
                self._quit()
                return

            # ── Handle command ───────────────────────────────────────────────
            if not raw:
                self._show_stations()
            else:
                self._handle_command(raw)

            # ── Restart Live with FRESH object ───────────────────────────────
            if not self._anim_stop.is_set():
                self.console.print(Rule(style="bright_black"))
                self._live = self._make_live()
                self._live.start()

    def _make_live(self) -> Live:
        """Always create a brand-new Live — never reuse to avoid cursor-resume."""
        return Live(
            self._build_now_panel(),
            console=self.console,
            refresh_per_second=5,
            transient=False,
            vertical_overflow="visible",
            auto_refresh=True,
        )

    # ── Command dispatcher ─────────────────────────────────────────────────────

    def _handle_command(self, raw: str) -> None:
        parts = raw.split(maxsplit=1)
        verb  = parts[0].lower()
        arg   = parts[1].strip() if len(parts) > 1 else ""

        if verb.isdigit():
            self._cmd_play(verb)
            return

        dispatch = {
            "p":             self._cmd_play,   "play":     self._cmd_play,
            "stop":          lambda _: self._cmd_stop(),
            "n":             self._cmd_next,   "next":     self._cmd_next,
            "b":             self._cmd_prev,   "prev":     self._cmd_prev,
            "r":             self._cmd_random, "rand":     self._cmd_random,
                                               "random":   self._cmd_random,
            "now":           self._cmd_now,
            "info":          self._cmd_info,
            "s":             self._cmd_search, "search":   self._cmd_search,
            "cat":           self._cmd_category, "category": self._cmd_category,
            "ls":            lambda _: self._show_stations(),
            "list":          lambda _: self._show_stations(),
            "sort":          self._cmd_sort,
            "v":             self._cmd_volume, "vol":      self._cmd_volume,
                                               "volume":   self._cmd_volume,
            "m":             lambda _: self._cmd_mute(),
            "mute":          lambda _: self._cmd_mute(),
            "f":             self._cmd_fav,    "fav":      self._cmd_fav,
                                               "favorite": self._cmd_fav,
            "eq":            self._cmd_eq,     "equalizer": self._cmd_eq,
            "sleep":         self._cmd_sleep,
            "record":        self._cmd_record,
            "rec":           self._cmd_record,
            "stoprec":       lambda _: self._cmd_stoprec(),
            "stoprecord":    lambda _: self._cmd_stoprec(),
            "vlcinfo":       lambda _: self._cmd_vlcinfo(),
            "datadir":       lambda _: self._cmd_datadir(),
            # log command removed — all events auto-saved to radio_log.txt
            "preload_status": self._cmd_preload_status,
            "refresh":       lambda _: self._cmd_refresh(),
            "clean":         lambda _: self._cmd_clean(),
            "cls":           lambda _: self._cmd_clean(),
            "clear":         lambda _: self._cmd_clean(),
            "h":             lambda _: self._print_help(),
            "help":          lambda _: self._print_help(),
            "q":             lambda _: self._quit(),
            "quit":          lambda _: self._quit(),
            "exit":          lambda _: self._quit(),
        }

        fn = dispatch.get(verb)
        if fn:
            fn(arg)
        else:
            self.console.print(
                f"[red]Unknown command:[/red] [bold]{verb}[/bold]  "
                "— type [bold cyan]h[/bold cyan] for help"
            )

    # ── Playback commands ──────────────────────────────────────────────────────

    def _cmd_play(self, arg: str) -> None:
        if not arg:
            self.console.print("[red]Usage:[/red] play <number>")
            return
        try:
            idx = int(arg) - 1
        except ValueError:
            self.console.print("[red]Usage:[/red] play <number>")
            return
        if 0 <= idx < len(self.stations):
            self._play_station(self.stations[idx])
        else:
            self.console.print(f"[red]Invalid.[/red] Choose 1–{len(self.stations)}")

    def _cmd_next(self, _: str) -> None:
        if not self.stations:
            self.console.print("[yellow]No stations loaded[/yellow]")
            return
        self._play_station(self.stations[(self._station_idx + 1) % len(self.stations)])

    def _cmd_prev(self, _: str) -> None:
        if not self.stations:
            self.console.print("[yellow]No stations loaded[/yellow]")
            return
        idx = (self._station_idx - 1) % len(self.stations) if self._station_idx >= 0 \
              else len(self.stations) - 1
        self._play_station(self.stations[idx])

    def _cmd_random(self, _: str) -> None:
        if not self.stations:
            self.console.print("[yellow]No stations loaded[/yellow]")
            return
        self._play_station(_random.choice(self.stations))

    def _cmd_stop(self) -> None:
        self._stop_meta_poll()
        self.player.stop()
        self.current_station = None
        self._station_idx    = -1
        self._play_start     = 0.0
        self.console.print("[yellow]⏹  Stopped[/yellow]")
        self._show_stations()
        self._force_panel_update()

    # ── Info commands ──────────────────────────────────────────────────────────

    def _cmd_now(self, _: str) -> None:
        if not self.current_station:
            self.console.print("[yellow]Nothing is playing[/yellow]")
            return
        name    = _clean_name(self.current_station.get("name", ""))
        elapsed = _fmt_elapsed(int(time.time() - self._play_start))
        state   = self.player.get_state_label()
        line = (
            f"[bold green]▶[/bold green] [bold]{name}[/bold]"
            f"  [dim]{elapsed}[/dim]"
            f"  [dim cyan]{state}[/dim cyan]"
        )
        if self.player.reconnecting:
            line += "  [yellow]🔄 Reconnecting…[/yellow]"
        self.console.print(line)
        if self._live_track:
            self.console.print(f"   [italic cyan]{self._live_track}[/italic cyan]")
        if self.player.is_recording():
            self.console.print(
                f"   [red]⏺ Recording → {self.player.get_recording_path()}[/red]"
            )

    def _cmd_info(self, _: str) -> None:
        if not self.current_station:
            self.console.print("[yellow]Nothing is playing.[/yellow]")
            return
        s    = self.current_station
        meta = self.player.get_current_metadata()

        t = Table(
            title="[bold cyan]📻  Now Playing — Station Info[/bold cyan]",
            box=box.ROUNDED, border_style="cyan",
            show_header=False,
            padding=(0, 1),
        )
        t.add_column("Field", style="bold cyan", min_width=14, no_wrap=True)
        t.add_column("Value", style="white",     min_width=36)
        t.add_row("Station",     _clean_name(s.get("name", "")))
        t.add_row("Country",     s.get("country", "") or "—")
        t.add_row("Tags",        s.get("tags",    "") or "—")
        t.add_row("Codec",       s.get("codec",   "") or "—")
        t.add_row("Bitrate",     f"{s.get('bitrate', 0)} kbps" if s.get("bitrate") else "—")
        t.add_row("URL",         s.get("url", ""))
        t.add_row("Now Playing", meta.get("title", "") or "—")
        t.add_row("Artist",      meta.get("artist","") or "—")
        t.add_row("VLC State",   self.player.get_state_label())
        t.add_row("Volume",      f"{self._volume}%  {'🔇 Muted' if self._muted else ''}")
        if self.player.is_recording():
            t.add_row("Recording", f"[bold red]⏺  {self.player.get_recording_path() or '—'}[/bold red]")

        self._sep()
        self.console.print(t)
        self._sep()

    # ── Browse commands ────────────────────────────────────────────────────────

    def _cmd_search(self, query: str) -> None:
        if not query:
            self.console.print("[red]Usage:[/red] search <query>")
            return
        with self.console.status(f"[cyan]{_SPINNER[0]} Searching '{query}'…[/cyan]"):
            results = fetch_stations(query, limit=MAX_RESULTS)
            if results:
                results = filter_alive_stations(results)
        if results:
            self.stations     = results
            self.current_cat  = "search"
            self._station_idx = -1
            self.console.print(f"[green]Found {len(results)} alive station(s)[/green]")
            self._show_stations()
        else:
            self.console.print(f"[yellow]No alive stations found for '{query}'[/yellow]")

    def _cmd_sort(self, arg: str) -> None:
        key_map = {
            "name":    lambda s: _clean_name(s.get("name", "")).lower(),
            "bitrate": lambda s: s.get("bitrate", 0),
            "votes":   lambda s: s.get("votes",   0),
            "country": lambda s: s.get("country", "").lower(),
        }
        key = arg.strip().lower() if arg else "name"
        fn  = key_map.get(key)
        if not fn:
            self.console.print(
                "[red]Sort by:[/red]  "
                "[bold]name[/bold]  [bold]bitrate[/bold]  "
                "[bold]votes[/bold]  [bold]country[/bold]"
            )
            return
        reverse       = key in ("bitrate", "votes")
        self.stations = sorted(self.stations, key=fn, reverse=reverse)
        self.console.print(f"[green]Sorted by {key}  {'↓ high→low' if reverse else 'A→Z'}[/green]")
        self._show_stations()

    def _cmd_category(self, cat: str) -> None:
        cat_key = cat.strip().lower()
        if cat_key.isdigit():
            idx = int(cat_key) - 1
            if 0 <= idx < len(CATEGORIES):
                cat_key = CATEGORIES[idx][1]
            else:
                self.console.print(f"[red]Choose 1–{len(CATEGORIES)}[/red]")
                return

        if cat_key not in self.VALID_CATS:
            valid = ", ".join(k for _, k in CATEGORIES) + ", recent"
            self.console.print(
                f"[red]Unknown category '{cat_key}'[/red]\n"
                f"[dim]Available: {valid}[/dim]"
            )
            return
        self.current_cat  = cat_key
        self._station_idx = -1
        self._load_category(cat_key, silent=False)
        self._show_stations()

    def _cmd_preload_status(self, _: str) -> None:
        status               = get_preload_status()
        refresh_time, rstatus = get_last_refresh_info()

        t = Table(
            title="[bold cyan]⟳  Background Preload Status[/bold cyan]",
            box=box.ROUNDED, border_style="cyan",
            header_style="bold cyan",
            padding=(0, 1),
        )
        t.add_column("Category", style="bold cyan", min_width=12)
        t.add_column("Status",   style="white",     min_width=18)
        for cat, loaded in status.items():
            t.add_row(
                cat,
                "[green]✓ Loaded[/green]" if loaded else "[yellow]⟳ Loading…[/yellow]",
            )

        self._sep()
        self.console.print(t)
        self._sep()
        self.console.print(
            f"[dim]  Last refresh: {refresh_time}  ·  Status: {rstatus}[/dim]"
        )
        self._sep()

    # ── Audio commands ─────────────────────────────────────────────────────────

    def _cmd_volume(self, arg: str) -> None:
        if not arg:
            self.console.print(f"[cyan]Volume:[/cyan] {self._volume}%")
            return
        try:
            vol = int(arg)
            if 0 <= vol <= 100:
                self._volume = vol
                self.player.set_volume(vol)
                self.console.print(f"[cyan]Volume → {vol}%[/cyan]")
            else:
                self.console.print("[red]Volume must be 0–100[/red]")
        except ValueError:
            self.console.print("[red]Usage:[/red] vol <0–100>")

    def _cmd_mute(self) -> None:
        self._muted = self.player.toggle_mute()
        self.console.print(
            f"[cyan]{'🔇 Muted' if self._muted else '🔊 Unmuted'}[/cyan]"
        )

    def _cmd_fav(self, arg: str) -> None:
        if not arg:
            self.console.print("[red]Usage:[/red] fav <number>")
            return
        try:
            idx = int(arg) - 1
        except ValueError:
            self.console.print("[red]Usage:[/red] fav <number>")
            return
        if not (0 <= idx < len(self.stations)):
            self.console.print(f"[red]Invalid.[/red] Choose 1–{len(self.stations)}")
            return
        station = self.stations[idx]
        url     = station["url"]
        name    = _clean_name(station.get("name", ""))
        if url in self._fav_urls:
            self.favorites  = [f for f in self.favorites if f["url"] != url]
            self._fav_urls.discard(url)
            self.console.print(f"[yellow]♡ Removed from favorites:[/yellow] {name}")
        else:
            self.favorites.append(station)
            self._fav_urls.add(url)
            self.console.print(f"[red]❤ Added to favorites:[/red] {name}")
        save_favorites(self.favorites)

    def _cmd_eq(self, arg: str) -> None:
        presets = list(Equalizer.PRESETS.keys())
        arg_l   = arg.lower()

        # ── Show current band values ───────────────────────────────────────
        if arg_l == "custom":
            bands  = self.player.equalizer.get_bands()
            labels = Equalizer.BAND_LABELS

            t = Table(
                title="[bold cyan]🎛  Current EQ Band Values[/bold cyan]",
                box=box.ROUNDED, border_style="cyan",
                header_style="bold cyan",
                show_lines=True,
                padding=(0, 1),
            )
            t.add_column("Band",  style="cyan",  width=7,  no_wrap=True)
            t.add_column("Gain",  style="white", width=10, justify="right", no_wrap=True)
            t.add_column("Level Bar", style="green", min_width=24)

            for label, gain in zip(labels, bands):
                blocks = int(abs(gain) / 2)
                bar    = ("▮" * blocks) if blocks else "·"
                color  = "green" if gain > 0 else ("red" if gain < 0 else "bright_black")
                t.add_row(
                    label,
                    f"[{color}]{gain:+.1f} dB[/{color}]",
                    f"[{color}]{bar}[/{color}]",
                )

            self._sep()
            self.console.print(t)
            self._sep()
            self.console.print(
                "[dim]  eq custom <b0 b1 … b9>  — set 10 bands (−20 to +20 dB each)[/dim]\n"
                "[dim]  Example: eq custom 8 6 0 0 0 0 0 4 6 8[/dim]"
            )
            self._sep()
            return

        # ── Set custom bands ───────────────────────────────────────────────
        if arg_l.startswith("custom "):
            try:
                gains = [float(x) for x in arg[7:].split()]
                if len(gains) != 10:
                    self.console.print(f"[red]Need exactly 10 values, got {len(gains)}[/red]")
                    return
                self.player.equalizer.set_custom_bands(gains)
                self.player.toggle_equalizer(True)
                self.console.print("[green]✓ Custom EQ applied[/green]")
                self.console.print(f"  [dim]{self.player.equalizer.get_summary()}[/dim]")
            except ValueError:
                self.console.print("[red]Values must be numbers between −20 and 20[/red]")
            return

        # ── List presets ───────────────────────────────────────────────────
        if not arg:
            eq_state   = self.player.equalizer
            cur_preset = eq_state.current_preset
            eq_enabled = eq_state.enabled

            t = Table(
                title="[bold cyan]🎛  Equalizer Presets[/bold cyan]",
                box=box.ROUNDED, border_style="cyan",
                header_style="bold cyan",
                show_lines=True,
                padding=(0, 1),
            )
            t.add_column("#",       style="dim",        width=3,  justify="right", no_wrap=True)
            t.add_column("Preset",  style="bold white", min_width=14, no_wrap=True)
            t.add_column("Band Gains (60Hz → 16kHz)", style="dim", min_width=32)
            t.add_column("Active",  style="dim",        width=10, justify="center", no_wrap=True)

            for i, p in enumerate(presets, 1):
                eq_tmp = Equalizer()
                eq_tmp.set_preset(p)
                eq_tmp.enabled = True
                summary = eq_tmp.get_summary()

                is_active  = (p == cur_preset and eq_enabled)
                is_cur_off = (p == cur_preset and not eq_enabled)

                if is_active:
                    badge = "[bold green]◄ ON[/bold green]"
                    name_mk = f"[bold green]{p}[/bold green]"
                elif is_cur_off:
                    badge = "[yellow]◄ OFF[/yellow]"
                    name_mk = f"[yellow]{p}[/yellow]"
                else:
                    badge   = ""
                    name_mk = p

                t.add_row(str(i), name_mk, summary, badge)

            self._sep()
            self.console.print(t)
            self._sep()

            # Usage panel — separate, below table, with its own clean borders
            status_line = (
                f"  EQ Power: [bold]{'ON' if eq_enabled else 'OFF'}[/bold]"
                f"   Preset: [cyan]{cur_preset}[/cyan]"
            )
            self.console.print(Panel(
                Text.from_markup(
                    status_line + "\n\n"
                    "  [dim]eq <name|#>              — apply preset[/dim]\n"
                    "  [dim]eq custom                — view band values[/dim]\n"
                    "  [dim]eq custom <b0…b9>        — set 10 bands (−20 to +20 dB)[/dim]"
                ),
                title="[dim]EQ Status & Usage[/dim]",
                border_style="bright_black",
                box=box.ROUNDED,
                padding=(0, 2),
            ))
            self._sep()
            return

        # ── Apply preset by name or number ─────────────────────────────────
        try:
            idx     = int(arg) - 1
            matched = presets[idx] if 0 <= idx < len(presets) else None
        except ValueError:
            matched = next((p for p in presets if p.lower() == arg.lower()), None)

        if matched:
            self.player.set_equalizer_preset(matched)
            self.player.toggle_equalizer(matched != "None")
            self.console.print(f"[green]✓ EQ preset:[/green] [bold]{matched}[/bold]")
            if matched not in ("None", "Custom"):
                self.console.print(f"  [dim]{self.player.equalizer.get_summary()}[/dim]")
        else:
            self.console.print(
                f"[red]Unknown preset '{arg}'[/red] — type [bold]eq[/bold] to list"
            )

    def _cmd_sleep(self, arg: str) -> None:
        if self._sleep_timer and self._sleep_timer.is_alive():
            self._sleep_timer.cancel()
            self._sleep_timer = None
            self._sleep_end   = None
            self.console.print("[yellow]💤 Sleep timer cancelled[/yellow]")
            return
        if not arg:
            self.console.print(
                "[cyan]Usage:[/cyan] sleep <minutes>  [dim](run again to cancel)[/dim]"
            )
            return
        try:
            minutes = int(arg)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            self.console.print("[red]Usage:[/red] sleep <minutes>")
            return
        self._sleep_end   = time.time() + minutes * 60
        self._sleep_timer = threading.Timer(minutes * 60, self._sleep_fire)
        self._sleep_timer.daemon = True
        self._sleep_timer.start()
        wake_at = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        self.console.print(
            f"[green]💤 Sleep timer set: {minutes} min "
            f"(stops at {wake_at.strftime('%H:%M:%S')})[/green]"
        )

    def _sleep_fire(self) -> None:
        self._stop_meta_poll()
        self.player.stop()
        self.current_station = None
        self._sleep_end      = None
        self._sleep_timer    = None
        self._sep()
        self.console.print("[yellow]💤 Sleep timer — playback stopped[/yellow]")
        self._sep()

    # ── Recording commands ─────────────────────────────────────────────────────

    def _cmd_record(self, arg: str) -> None:
        """
        record [filename]
        Start recording the current stream to a file.
        Audio saved to E:\\radio_app_cli_powershell\\radio_audios by default.
        """
        if not self.current_station:
            self.console.print("[red]Nothing is playing. Play a station first.[/red]")
            return

        if self.player.is_recording():
            rec_path = self.player.get_recording_path() or "—"
            self._sep()
            self.console.print(Panel(
                Text.from_markup(
                    f"  [bold red]⏺  RECORDING IN PROGRESS[/bold red]\n\n"
                    f"  [dim]File :[/dim]  {rec_path}\n"
                    f"  [dim]Type  [bold]stoprec[/bold] to stop and save.[/dim]"
                ),
                title="[bold red]● REC[/bold red]",
                border_style="red",
                box=box.ROUNDED,
                padding=(0, 2),
            ))
            self._sep()
            return

        url = self.current_station.get("url", "")
        if not url:
            self.console.print("[red]No stream URL available.[/red]")
            return

        os.makedirs(_AUDIO_DIR, exist_ok=True)

        if arg:
            output_path = arg
            if not os.path.isabs(output_path):
                output_path = os.path.join(_AUDIO_DIR, output_path)
            if not output_path.lower().endswith((".mp3", ".aac", ".ogg", ".flac", ".wav")):
                output_path += ".mp3"
        else:
            ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            sname = _clean_name(self.current_station.get("name", "station"))
            safe  = "".join(c for c in sname if c.isalnum() or c in " _-")[:30].strip()
            fname = f"{safe}_{ts}.mp3".replace(" ", "_")
            output_path = os.path.join(_AUDIO_DIR, fname)

        ok = self.player.record(url, output_path)
        if ok:
            self._sep()
            self.console.print(Panel(
                Text.from_markup(
                    f"  [bold red]⏺  RECORDING STARTED[/bold red]\n\n"
                    f"  [dim]Station:[/dim]  [bold]{_clean_name(self.current_station.get('name',''))}[/bold]\n"
                    f"  [dim]File   :[/dim]  {output_path}\n\n"
                    f"  [dim]Type  [bold]stoprec[/bold]  to stop and save recording.[/dim]"
                ),
                title="[bold red]● REC[/bold red]",
                border_style="red",
                box=box.ROUNDED,
                padding=(0, 2),
            ))
            self._sep()
            log(f"Recording started: {output_path}", "info")
        else:
            self.console.print(
                "[red]Recording failed.[/red] Check VLC installation and disk space."
            )

    def _cmd_stoprec(self) -> None:
        """Stop any active recording and show saved file path."""
        if not self.player.is_recording():
            # Normal state — no recording symbol, just a quiet message
            self.console.print("[dim]No active recording.[/dim]")
            return

        saved = self.player.stop_recording()
        self._sep()
        if saved:
            self.console.print(Panel(
                Text.from_markup(
                    f"  [bold green]✔  RECORDING COMPLETE[/bold green]\n\n"
                    f"  [dim]Saved to:[/dim]  {saved}\n\n"
                    f"  [dim]Play back with any media player.[/dim]"
                ),
                title="[bold green]● REC DONE[/bold green]",
                border_style="green",
                box=box.ROUNDED,
                padding=(0, 2),
            ))
        else:
            self.console.print(Panel(
                Text.from_markup("  [green]✔  Recording stopped.[/green]"),
                border_style="green",
                box=box.ROUNDED,
                padding=(0, 2),
            ))
        self._sep()
        log("Recording stopped by user", "info")

    # ── VLC / System info commands ─────────────────────────────────────────────

    def _cmd_vlcinfo(self) -> None:
        """Display detailed VLC/libvlc information in a clean box."""
        try:
            import vlc

            def _dec(b):
                if isinstance(b, bytes):
                    return b.decode("utf-8", errors="replace").strip()
                return str(b).strip() if b else "—"

            ver       = _dec(vlc.libvlc_get_version())
            compiler  = _dec(vlc.libvlc_get_compiler())
            changeset = _dec(vlc.libvlc_get_changeset())

            vlc_path = "—"
            for candidate in [
                r"C:\Program Files\VideoLAN\VLC",
                r"C:\Program Files (x86)\VideoLAN\VLC",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\VideoLAN\VLC"),
            ]:
                if os.path.isfile(os.path.join(candidate, "libvlc.dll")):
                    vlc_path = candidate
                    break

            vlc_module_path = getattr(sys.modules.get("vlc"), "__file__", "—") or "—"
            vlc_py_ver      = getattr(vlc, "__version__", "—")

            audio_out = "—"
            try:
                aouts = self.player._instance.audio_output_enumerate_devices()
                if aouts:
                    devs = []
                    for a in aouts:
                        d = _dec(getattr(a, "description", b""))
                        if d and d not in devs:
                            devs.append(d)
                    audio_out = ", ".join(devs[:4]) or "—"
            except Exception:
                pass

            data_dir = os.path.join("E:\\", "radio_app_cli_powershell", "radio_ps")

            t = Table(
                title="[bold cyan]🔊  VLC / libvlc Information[/bold cyan]",
                box=box.ROUNDED, border_style="cyan",
                show_header=True,
                header_style="bold cyan",
                show_lines=True,
                padding=(0, 1),
            )
            t.add_column("Field", style="bold cyan",  min_width=20, no_wrap=True)
            t.add_column("Value", style="white",      min_width=44)

            rows = [
                ("libvlc Version",    ver),
                ("Compiler",          compiler),
                ("Changeset",         changeset),
                ("VLC Install Dir",   vlc_path),
                ("python-vlc Path",   vlc_module_path),
                ("python-vlc Version",vlc_py_ver),
                ("Audio Devices",     audio_out),
                ("EQ Bands",          "60Hz  170Hz  310Hz  600Hz  1kHz  3kHz  6kHz  12kHz  14kHz  16kHz"),
                ("EQ Gain Range",     "−20 dB  to  +20 dB  per band"),
                ("Recording Dir",     _AUDIO_DIR),
                ("Data / Log Dir",    data_dir),
                ("Log File",          os.path.join(data_dir, "radio_log.txt")),
            ]
            for field, val in rows:
                t.add_row(field, val)

            self._sep()
            self.console.print(t)
            self._sep()

        except Exception as e:
            self.console.print(f"[red]Could not get VLC info: {e}[/red]")
            log(f"vlcinfo error: {e}", "error")

    def _cmd_datadir(self) -> None:
        d = get_data_dir()
        self._sep()
        self.console.print(Panel(
            Text.from_markup(
                f"  [bold cyan]Data & Log Directory[/bold cyan]\n\n"
                f"  [white]{d}[/white]\n\n"
                f"  [dim]favorites.json[/dim]  — saved favorite stations\n"
                f"  [dim]recent.json   [/dim]  — recently played\n"
                f"  [dim]session.json  [/dim]  — last station + volume\n"
                f"  [dim]radio_log.txt [/dim]  — all application events (auto-saved)\n\n"
                f"  [bold cyan]Recorded Audio Directory[/bold cyan]\n\n"
                f"  [white]{_AUDIO_DIR}[/white]"
            ),
            title="[dim]datadir[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 2),
        ))
        self._sep()

    # log command removed — all events auto-saved to radio_log.txt automatically.

    def _cmd_refresh(self) -> None:
        self.console.print("[cyan]Refreshing all categories in background…[/cyan]")
        threading.Thread(target=refresh_categories, daemon=True).start()
        self.console.print("[green]Refresh started — cache updates in background.[/green]")

    # ── Clean terminal ─────────────────────────────────────────────────────────

    def _cmd_clean(self) -> None:
        # Stop Live first so it doesn't linger
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        os.system("cls" if os.name == "nt" else "clear")
        self.console.clear()
        self._print_banner()
        self._show_stations()
        self._print_help_hint()

    # ── Internal: play station ─────────────────────────────────────────────────

    def _play_station(self, station: dict, silent: bool = False) -> None:
        if (self.current_station
                and self.current_station["url"] == station["url"]
                and self.player.is_playing()):
            self._cmd_stop()
            return

        self._stop_meta_poll()

        success = self.player.play(station["url"])
        if not success:
            self.console.print(
                "[red]⚠ Could not play this station[/red] "
                "[dim](URL blocked or VLC not found)[/dim]"
            )
            log(f"Play failed: {station.get('name')} — {station['url']}", "warning")
            return

        self.current_station = station
        self._play_start     = time.time()
        self._marquee_off    = 0

        self._station_idx = next(
            (i for i, s in enumerate(self.stations) if s["url"] == station["url"]),
            -1,
        )

        self.recent = [s for s in self.recent if s["url"] != station["url"]]
        self.recent.insert(0, station)
        self.recent = self.recent[:20]

        if not silent:
            name    = _clean_name(station.get("name", ""))
            country = station.get("country", "")
            bitrate = station.get("bitrate", 0)
            codec   = station.get("codec",   "")
            detail  = [x for x in [country, codec, f"{bitrate}kbps" if bitrate else ""] if x]
            self.console.print(f"\n[bold green]▶  Now Playing:[/bold green] [bold]{name}[/bold]")
            if detail:
                self.console.print(f"   [dim]{' · '.join(detail)}[/dim]")

        self._start_meta_poll()
        log(f"PLAY: {station.get('name')} — {station['url']}")
        self._force_panel_update()

    def _force_panel_update(self) -> None:
        if self._live and not self._anim_stop.is_set():
            try:
                self._live.update(self._build_now_panel())
            except Exception:
                pass

    def _load_category(self, cat: str, silent: bool = False) -> None:
        if cat == "favorites":
            self.stations = self.all_stations = list(self.favorites)
        elif cat == "recent":
            self.stations = self.all_stations = list(self.recent)
        else:
            label = dict(CATEGORIES).get(cat, cat.title())
            if not silent:
                with self.console.status(f"[cyan]{_SPINNER[0]} Loading {label}…[/cyan]"):
                    stations = fetch_category(cat, filter_alive=True, use_cache=True)
            else:
                stations = fetch_category(cat, filter_alive=True, use_cache=True)
            self.stations = self.all_stations = stations
            if not silent:
                self.console.print(f"[green]Loaded {len(stations)} alive station(s) — {label}[/green]")

    # ── Metadata poll thread ───────────────────────────────────────────────────

    def _start_meta_poll(self) -> None:
        self._meta_stop.clear()
        self._live_track = ""
        threading.Thread(target=self._meta_loop, daemon=True, name="meta-poll").start()

    def _stop_meta_poll(self) -> None:
        self._meta_stop.set()
        self._live_track = ""

    def _meta_loop(self) -> None:
        while not self._meta_stop.wait(3.0):
            if not self.player.is_playing():
                break
            try:
                meta   = self.player.get_current_metadata()
                title  = meta.get("title",  "").strip()
                artist = meta.get("artist", "").strip()
                if artist and title:
                    self._live_track = f"{artist} – {title}"
                elif title:
                    self._live_track = title
                else:
                    self._live_track = ""
            except Exception:
                pass

    # ── Animation loop ─────────────────────────────────────────────────────────

    def _anim_loop(self) -> None:
        """5 fps animation — THE only thread that calls Live.update()."""
        while not self._anim_stop.wait(0.2):
            try:
                self._tick = (self._tick + 1) % 10_000
                if self._tick % 4 == 0:
                    self._marquee_off += 1
                self._process_dead_queue()
                if self._live and not self._anim_stop.is_set():
                    self._live.update(self._build_now_panel())
            except Exception as e:
                log(f"Anim tick error: {e}", "debug")

    # ── Now-Playing panel ──────────────────────────────────────────────────────

    def _build_now_panel(self) -> Panel:
        playing      = (self.current_station is not None
                        and self.player.is_playing()
                        and not self.player.reconnecting)
        reconnecting = self.player.reconnecting
        tick         = self._tick
        station      = self.current_station or {}
        recording    = self.player.is_recording()
        state        = self.player.get_state_label()

        # Title bar
        if playing:
            elapsed   = _fmt_elapsed(int(time.time() - self._play_start))
            rec_badge = "  [bold red]⏺ REC[/bold red]" if recording else ""
            title_txt = (
                f"[bold green]◉ NOW PLAYING[/bold green]"
                f"[dim] ── {elapsed}[/dim]{rec_badge}"
            )
            border = "cyan"
        elif reconnecting:
            attempt   = getattr(self.player, "_reconnect_count", "?")
            title_txt = (
                f"[bold yellow]⟳ RECONNECTING[/bold yellow]"
                f"[dim] ── attempt {attempt}[/dim]"
            )
            border = "yellow"
        else:
            title_txt = f"[bright_black]○  {_APP_NAME}[/bright_black]"
            border    = "bright_black"

        # Line 1: station name
        l1 = Text()
        if playing or reconnecting:
            name = _clean_name(station.get("name", ""))
            if len(name) > 60:
                name = name[:57] + "…"
            l1.append(f"  {name}", style="bold white" if playing else "yellow")
        else:
            l1.append("  Nothing playing", style="dim")

        # Line 2: track / status
        l2 = Text()
        track = self._live_track

        if reconnecting:
            spin = _SPINNER[tick % len(_SPINNER)]
            l2.append(f"  {spin} Reconnecting to stream…", style="yellow")
        elif playing and track:
            if len(track) > _MAX_MARQUEE:
                padded  = track + "     "
                loop    = padded * 3
                off     = self._marquee_off % len(padded)
                display = loop[off: off + _MAX_MARQUEE]
            else:
                display = track
            l2.append("  🎵 ", style="")
            l2.append(display, style="italic cyan")
        elif playing:
            country = station.get("country", "")
            tag     = (station.get("tags") or "").split(",")[0].strip()
            bitrate = station.get("bitrate", 0)
            parts   = [x for x in [country, tag, f"{bitrate}kbps" if bitrate else ""] if x]
            vlc_state_str = f"  [{state}]" if state not in ("playing", "buffering") else ""
            l2.append(
                f"  {' · '.join(parts)}{vlc_state_str}" if parts
                else f"  {state.capitalize()}…",
                style="dim",
            )
        else:
            l2.append("  Select a station to begin listening", style="dim")

        # Line 3: recording indicator
        l_rec = Text()
        if recording:
            rec_path = self.player.get_recording_path() or ""
            rec_short = ("…" + rec_path[-38:]) if len(rec_path) > 38 else rec_path
            l_rec.append(f"  ⏺ REC → {rec_short}", style="bold red")

        # Line 4: sleep timer
        l3 = Text()
        if self._sleep_end:
            remaining = max(0, int(self._sleep_end - time.time()))
            m, s = divmod(remaining, 60)
            l3.append(f"  💤 Sleep in {m}:{s:02d}", style="dim yellow")

        content = Text()
        content.append_text(l1)
        content.append("\n")
        content.append_text(l2)
        if recording:
            content.append("\n")
            content.append_text(l_rec)
        if self._sleep_end:
            content.append("\n")
            content.append_text(l3)

        return Panel(content, title=title_txt, border_style=border, padding=(0, 1))

    # ── Station list display ───────────────────────────────────────────────────

    def _show_stations(self) -> None:
        self._sep()

        if not self.stations:
            self.console.print(Panel(
                "[dim]No stations. Try [bold]search <query>[/bold] "
                "or [bold]cat <n>[/bold][/dim]",
                border_style="bright_black",
                box=box.ROUNDED,
                padding=(0, 1),
            ))
            self._sep()
            return

        cat_map   = dict(CATEGORIES)
        cat_label = cat_map.get(self.current_cat, self.current_cat.title())
        count     = len(self.stations)
        cur_url   = self.current_station["url"] if self.current_station else ""

        table = Table(
            title=f"📻  {cat_label}  ·  {count} station{'s' if count != 1 else ''}",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold cyan",
            show_lines=False,
            expand=False,
            padding=(0, 1),
        )
        table.add_column("#",       style="dim",          width=4,  justify="right", no_wrap=True)
        table.add_column("Station", style="white",        min_width=28, max_width=44)
        table.add_column("Country", style="bright_black", min_width=12, max_width=18)
        table.add_column("Tags",    style="bright_black", min_width=10, max_width=16)
        table.add_column("Codec",   style="dim",          width=6,  no_wrap=True)
        table.add_column("Quality", width=6,              justify="center", no_wrap=True)
        table.add_column("♥",       width=2,              justify="center", no_wrap=True)

        for i, s in enumerate(self.stations[:MAX_RESULTS], 1):
            playing      = s["url"] == cur_url
            is_fav       = s["url"] in self._fav_urls
            name_str     = _truncate(_clean_name(s.get("name", "Unknown")), 42)
            country_str  = _truncate(s.get("country") or "—", 18)
            tags_str     = _truncate((s.get("tags") or "").split(",")[0].strip(), 16) or "—"
            codec_str    = (s.get("codec") or "—")[:6]

            table.add_row(
                f"[bold cyan]{i}[/bold cyan]" if playing else f"[dim]{i}[/dim]",
                f"[bold green]▶ {name_str}[/bold green]" if playing else name_str,
                country_str,
                tags_str,
                codec_str,
                _quality_badge(s.get("bitrate", 0)),
                "[red]❤[/red]" if is_fav else "",
            )

        self.console.print(table)
        self._sep()
        self.console.print(
            "[dim]  p<#>  n  b  r   f<#>  s<query>  sort<key>  cat<n>  "
            "eq  sleep  record  stoprec  info  vlcinfo[/dim]"
        )
        self._sep()

    # ── Banner / Help ──────────────────────────────────────────────────────────

    def _print_banner(self) -> None:
        self.console.clear()
        self._sep()
        try:
            import vlc
            vlc_ver = vlc.libvlc_get_version()
            if isinstance(vlc_ver, bytes):
                vlc_ver = vlc_ver.decode("utf-8")
            vlc_str = f"[green]VLC {vlc_ver}[/green]"
        except Exception:
            vlc_str = "[yellow]VLC (version unknown)[/yellow]"

        self.console.print(Panel(
            Text.from_markup(
                f"  [bold cyan]{_APP_NAME}[/bold cyan]"
                f"  [bright_magenta]v{_APP_VER}[/bright_magenta]\n"
                f"  [dim]Powered by Radio Browser API  ·  {vlc_str}[/dim]"
            ),
            box=box.DOUBLE_EDGE,
            border_style="cyan",
            expand=False,
        ))
        self._sep()

    def _print_help_hint(self) -> None:
        self.console.print(
            "[dim]  h=help  q=quit  clean=clear  record=start recording  "
            "stoprec=stop recording  vlcinfo=VLC info[/dim]"
        )
        self._sep()

    def _print_help(self) -> None:
        t = Table(
            title=f"[bold cyan]{_APP_NAME} — Help[/bold cyan]",
            box=box.ROUNDED, border_style="cyan",
            header_style="bold cyan",
            show_lines=False,
            padding=(0, 1),
        )
        t.add_column("Command",     style="bold cyan", min_width=28, no_wrap=True)
        t.add_column("Description", style="white")

        for cmd, desc in [
            ("<number>  or  p <n>",       "Play station by number"),
            ("stop",                      "Stop playback"),
            ("n  /  next",                "Next station in list"),
            ("b  /  prev",                "Previous station"),
            ("r  /  rand",                "Random station from current list"),
            ("now",                       "One-line status + live track + VLC state"),
            ("info",                      "Full station details + ICY metadata"),
            ("", ""),
            ("s <query>",                 "Search alive stations"),
            ("cat <name|number>",         "Switch category"),
            ("",                          "[dim]  top  hindi  kannada  pop  rock  jazz"
                                          "  classical  news  favorites  recent[/dim]"),
            ("ls",                        "Redraw station list"),
            ("sort <key>",                "Sort: name  bitrate  votes  country"),
            ("", ""),
            ("v <0-100>",                 "Set volume (0–100)"),
            ("m",                         "Toggle mute"),
            ("f <n>",                     "Toggle station as favorite"),
            ("eq",                        "Show EQ presets table"),
            ("eq <preset|#>",             "Apply EQ preset by name or number"),
            ("eq custom",                 "Show current band values"),
            ("eq custom <b0…b9>",         "Set 10 custom bands (−20 to +20 dB)"),
            ("sleep <minutes>",           "Sleep timer (run again to cancel)"),
            ("", ""),
            ("record [filename]",         "Record stream to file (MP3 by default)"),
            ("stoprec",                   "Stop recording — shows saved file path"),
            ("", ""),
            ("vlcinfo",                   "Show detailed VLC / libvlc information"),
            ("datadir",                   "Show data and recording directory paths"),
            ("preload_status",            "Show background preload progress"),
            ("refresh",                   "Force refresh all category caches"),
            ("clean / cls",               "Clear terminal and redisplay"),
            ("", ""),
            ("h",                         "This help"),
            ("q",                         "Quit and save session"),
        ]:
            t.add_row(cmd, desc)

        self._sep()
        self.console.print(t)
        self._sep()

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def _quit(self) -> None:
        if self._sleep_timer and self._sleep_timer.is_alive():
            self._sleep_timer.cancel()
        self._stop_meta_poll()
        self._anim_stop.set()
        stop_refresh_timer()
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
        try:
            self.player.stop_recording()
            self.player.shutdown()
            save_session(self._volume, self.current_station)
            save_recent(self.recent)
        except Exception as e:
            log(f"Shutdown error: {e}", "warning")
        self._sep()
        self.console.print("[bold cyan]👋 Goodbye! Session saved.[/bold cyan]")
        self._sep()
        sys.exit(0)
