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

from radio_ps.core.config   import CATEGORIES, MAX_RESULTS
from radio_ps.core.player   import RadioPlayer
from radio_ps.core.equalizer import Equalizer
from radio_ps.core.api      import fetch_stations
from radio_ps.services.station_service import (
    fetch_category,
    filter_alive_stations,
    preload_categories,
    get_preload_status,
    start_refresh_timer,
    stop_refresh_timer,
    refresh_categories,
    get_last_refresh_info,
)
from radio_ps.utils.storage import (
    load_favorites, save_favorites,
    load_recent,    save_recent,
    load_session,   save_session,
    get_data_dir,
)
from radio_ps.utils.logger import log, get_log_path


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
    def __init__(self):
        self._console = Console(force_terminal=True)
        self._player = None
        self._stations: list[dict] = []
        self._by_url: dict[str, dict] = {}
        self._current = 0
        self._category = "top"
        self._favorites: list[dict] = []
        self._recent: list[dict] = []
        self._history: list[int] = []
        self._history_pos = 0
        self._recording = False
        self._recording_path = None
        self._sleep_timer: int | None = None
        self._sleep_thread: threading.Thread | None = None
        self._sleep_cancel = threading.Event()
        self._start_time: float | None = None

    def run(self, start_category: str | None = None) -> None:
        self._init_player()
        self._load_data()
        cat = start_category or "top"
        self._category = cat
        self._show_welcome()
        self._fetch_initial(cat)
        self._cmd_loop()

    # ── Init ────────────────────────────────────────────────────────────────────

    def _init_player(self) -> None:
        self._player = RadioPlayer(on_permanent_failure=self._on_permanent_failure)
        session = load_session()
        vol = session.get("volume", 70)
        self._player.set_volume(vol)
        last = session.get("last_station")
        if last:
            url = last.get("url")
            if url:
                self._player.play(url)
                self._current = 0
                self._start_time = time.time()
        log("Player initialized", "info")

    def _load_data(self) -> None:
        self._favorites = load_favorites()
        self._recent = load_recent()
        log(f"Loaded {len(self._favorites)} favorites, {len(self._recent)} recent", "info")

    def _show_welcome(self) -> None:
        self._console.print()
        self._console.print(f"[bold cyan]{_APP_NAME}[/bold cyan] [dim]v{_APP_VER}[/dim]")
        self._console.print("[dim]Internet radio for Windows PowerShell[/dim]")
        self._console.print()
        self._console.print("[dim]Commands: p/n/b/r = play/next/prev/rand | v/m = vol/mute[/dim]")
        self._console.print("[dim]        s/f/eq = search/fav/equalizer | record = record[/dim]")
        self._console.print("[dim]        q = quit | h = help[/dim]")
        self._sep()

    def _fetch_initial(self, category: str) -> None:
        self._console.print(f"[cyan]Loading {category}...[/cyan]")
        self._load_category(category)
        self._list_stations()
        preload_categories()
        start_refresh_timer()
        self._sep()

    # ── Core ───────────────────────────────────────────────────────────────────

    def _load_category(self, category: str) -> None:
        if category == "favorites":
            self._stations = self._favorites.copy()
        elif category == "recent":
            self._stations = self._recent.copy()
        else:
            self._stations = fetch_category(category)
        self._by_url = {s["url"]: s for s in self._stations}
        self._category = category

    def _list_stations(self) -> None:
        if not self._stations:
            self._console.print("[yellow]No stations found[/yellow]")
            return
        t = Table(show_header=True, header_style="bold cyan")
        t.add_column("[cyan]#[/]",width=4,justify="right")
        t.add_column("[cyan]Station[/]",width=40)
        t.add_column("[cyan]Country[/]",width=12)
        t.add_column("[cyan]Quality[/]",width=8)
        for i, s in enumerate(self._stations[:40], 1):
            t.add_row(
                str(i),
                _truncate(s.get("name", "?"), 38),
                _truncate(s.get("country", ""), 12),
                _quality_badge(s.get("bitrate", 0)),
            )
        self._console.print(t)
        self._console.print(f"[dim]Showing {len(self._stations)} stations[/dim]")

    def _play_station(self, index: int | None = None) -> None:
        if index is None:
            if 0 <= self._current < len(self._stations):
                index = self._current
            else:
                return
        if not (0 <= index < len(self._stations)):
            return
        s = self._stations[index]
        if self._player.play(s["url"]):
            self._current = index
            self._history.append(index)
            self._history_pos = len(self._history)
            self._add_recent(s)
            self._start_time = time.time()
            self._sep()
            self._show_now_playing(s)
            self._sep()

    def _show_now_playing(self, s: dict | None = None) -> None:
        if s is None:
            if not (0 <= self._current < len(self._stations)):
                return
            s = self._stations[self._current]
        url = self._player.get_current_url()
        meta = self._player.get_current_metadata()
        title = meta.get("title", "")
        state = self._player.get_state_label()
        p = Panel(
            Text.assemble(
                f"[bold cyan]{_clean_name(s.get('name','?'))}[/bold cyan]\n",
                f"[dim]{s.get('country','')}[/dim]\n" if s.get("country") else "",
                f"[green]{title}[/green]\n" if title else "",
                f"[yellow]▮▮▮▮▯ {state}[/yellow]" if self._player.is_playing() else "[red]▮▮▮▮▮ stopped[/red]",
            ),
            title="Now Playing",
            border_style="cyan",
            box=box.ROUNDED,
        )
        self._console.print(p)

    def _add_recent(self, s: dict) -> None:
        self._recent = [x for x in self._recent if x.get("url") != s.get("url")]
        self._recent.insert(0, s)
        self._recent = self._recent[:20]
        save_recent(self._recent)

    # ── Commands ────────────────────────────────────────────────────────────

    def _cmd_loop(self) -> None:
        while True:
            try:
                line = self._console.input("[bold cyan]>[/bold cyan] ").strip()
                if not line:
                    continue
                if self._dispatch(line):
                    break
            except (KeyboardInterrupt, EOFError):
                break
        self._shutdown()

    def _dispatch(self, line: str) -> bool:
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("q", "quit", "exit"):
            return True

        if cmd in ("h", "help", "?"):
            self._show_help()
        elif cmd in ("ls", "list"):
            self._list_stations()
        elif cmd in ("now", "playing"):
            self._show_now_playing()
        elif cmd in ("vlcinfo", "vlc"):
            self._show_vlc_info()
        elif cmd in ("datadir", "dir"):
            self._console.print(f"[cyan]{get_data_dir()}[/cyan]")
        elif cmd in ("log",):
            self._show_log(args)
        elif cmd in ("clean", "cls", "clear"):
            self._console.clear()
        elif cmd in ("preload_status",):
            self._show_preload_status()
        elif cmd in ("refresh",):
            self._console.print("[cyan]Refreshing...[/cyan]")
            refresh_categories()
            self._load_category(self._category)
            self._list_stations()
        elif cmd in ("info",):
            self._show_station_info()
        elif cmd == "p" and args:
            self._cmd_play(args)
        elif cmd in ("p", "play"):
            self._cmd_play(args)
        elif cmd in ("n", "next"):
            self._cmd_next()
        elif cmd in ("b", "prev"):
            self._cmd_prev()
        elif cmd in ("r", "rand", "random"):
            self._cmd_rand()
        elif cmd == "s" and args:
            self._cmd_search(args)
        elif cmd == "cat" and args:
            self._cmd_category(args)
        elif cmd == "sort" and args:
            self._cmd_sort(args)
        elif cmd == "v" and args:
            self._cmd_volume(args)
        elif cmd == "m":
            self._cmd_mute()
        elif cmd == "f" and args:
            self._cmd_fav(args)
        elif cmd == "f":
            self._toggle_fav()
        elif cmd == "eq" and args:
            self._cmd_eq(args)
        elif cmd == "eq":
            self._show_eq()
        elif cmd == "record" and args:
            self._cmd_record(args)
        elif cmd == "record":
            self._cmd_record([])
        elif cmd in ("stoprec", "stoprec"):
            self._cmd_stop_rec()
        elif cmd == "sleep" and args:
            self._cmd_sleep(args)
        elif cmd.isdigit():
            self._cmd_play([cmd])
        else:
            self._console.print(f"[red]Unknown command: {cmd}[/red]")

        self._sep()
        return False

    def _cmd_play(self, args: list[str]) -> None:
        if args:
            try:
                idx = int(args[0]) - 1
            except ValueError:
                self._console.print("[red]Invalid number[/red]")
                return
        else:
            idx = self._current
        self._play_station(idx)

    def _cmd_next(self) -> None:
        if self._stations:
            self._play_station((self._current + 1) % len(self._stations))

    def _cmd_prev(self) -> None:
        if self._stations:
            self._play_station((self._current - 1) % len(self._stations))

    def _cmd_rand(self) -> None:
        if self._stations:
            self._play_station(_random.randint(0, len(self._stations) - 1))

    def _cmd_search(self, args: list[str]) -> None:
        query = " ".join(args)
        self._console.print(f"[cyan]Searching for '{query}'...[/cyan]")
        results = fetch_stations(query, limit=30)
        if results:
            self._stations = results
            self._by_url = {s["url"]: s for s in self._stations}
            self._category = "search"
            self._list_stations()
        else:
            self._console.print("[yellow]No results[/yellow]")

    def _cmd_category(self, args: list[str]) -> None:
        cat = args[0].lower()
        self._console.print(f"[cyan]Loading {cat}...[/cyan]")
        self._load_category(cat)
        self._list_stations()

    def _cmd_sort(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red>sort key (name|bitrate|votes|country)[/red]")
            return
        key = args[0].lower()
        if key == "name":
            self._stations.sort(key=lambda s: s.get("name", ""))
        elif key == "bitrate":
            self._stations.sort(key=lambda s: s.get("bitrate", 0), reverse=True)
        elif key == "votes":
            self._stations.sort(key=lambda s: s.get("votes", 0), reverse=True)
        elif key == "country":
            self._stations.sort(key=lambda s: s.get("country", ""))
        else:
            self._console.print(f"[red]Unknown sort key: {key}[/red]")
            return
        self._list_stations()

    def _cmd_volume(self, args: list[str]) -> None:
        try:
            vol = int(args[0])
            self._player.set_volume(vol)
            self._console.print(f"[green]Volume: {vol}[/green]")
        except (ValueError, IndexError):
            self._console.print("[red]Usage: v <0-100>[/red]")

    def _cmd_mute(self) -> None:
        muted = self._player.toggle_mute()
        self._console.print(f"[{'red' if muted else green}]Mute: {'ON' if muted else 'OFF'}[/]")

    def _cmd_fav(self, args: list[str]) -> None:
        try:
            idx = int(args[0]) - 1
            if 0 <= idx < len(self._stations):
                s = self._stations[idx]
                self._add_fav(s)
            else:
                self._console.print("[red]Invalid station number[/red]")
        except ValueError:
            self._console.print("[red]Invalid number[/red]")

    def _toggle_fav(self) -> None:
        if 0 <= self._current < len(self._stations):
            s = self._stations[self._current]
            self._add_fav(s)

    def _add_fav(self, s: dict) -> None:
        url = s.get("url")
        self._favorites = [x for x in self._favorites if x.get("url") != url]
        self._favorites.insert(0, s)
        save_favorites(self._favorites)
        self._console.print(f"[green]Added to favorites: {s.get('name')}[/green]")

    def _show_eq(self) -> None:
        eq = self._player.equalizer
        self._console.print(f"[cyan]Preset: {eq.current_preset}[/cyan]")
        self._console.print(f"[cyan]Bands: {eq.get_summary()}[/cyan]")

    def _cmd_eq(self, args: list[str]) -> None:
        if not args:
            self._show_eq()
            return
        preset = args[0].lower()
        if preset == "custom" and len(args) > 1:
            try:
                bands = [float(x) for x in args[1:]]
                if len(bands) == 10:
                    self._player.equalizer.set_custom_bands(bands)
                    self._console.print("[green]Custom EQ set[/green]")
                else:
                    self._console.print("[red]Need exactly 10 band values[/red]")
            except ValueError:
                self._console.print("[red]Invalid band values[/red]")
        else:
            self._player.set_equalizer_preset(preset)
            self._console.print(f"[green]EQ: {preset}[/green]")

    def _cmd_record(self, args: list[str]) -> None:
        if self._recording:
            self._console.print("[yellow]Already recording[/yellow]")
            return
        url = self._player.get_current_url()
        if not url:
            self._console.print("[red]Nothing playing[/red]")
            return
        os.makedirs(_AUDIO_DIR, exist_ok=True)
        name = " ".join(args) if args else datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_AUDIO_DIR, f"{name}.mp3")
        if self._player.record(url, path):
            self._recording = True
            self._recording_path = path
            self._console.print(f"[green]Recording → {path}[/green]")
        else:
            self._console.print("[red]Recording failed[/red]")

    def _cmd_stop_rec(self) -> None:
        if not self._recording:
            self._console.print("[yellow]Not recording[/yellow]")
            return
        path = self._player.stop_recording()
        self._recording = False
        self._recording_path = None
        self._console.print(f"[green]Saved: {path}[/green]")

    def _cmd_sleep(self, args: list[str]) -> None:
        try:
            mins = int(args[0])
            self._sleep_cancel.clear()
            self._sleep_timer = mins
            def _sleep_task():
                for i in range(mins * 60, 0, -60):
                    if self._sleep_cancel.is_set():
                        return
                    time.sleep(60)
                self._player.stop()
                self._console.print("[cyan]Sleep timer: playback stopped[/cyan]")
            self._sleep_thread = threading.Thread(target=_sleep_task, daemon=True)
            self._sleep_thread.start()
            self._console.print(f"[green]Sleep in {mins} min[/green]")
        except (ValueError, IndexError):
            self._console.print("[red]Usage: sleep <minutes>[/red]")

    def _show_help(self) -> None:
        self._console.print("[bold cyan]Commands[/bold cyan]")
        self._console.print("[dim]Playback:[/dim] p <n> = play station | stop = stop")
        self._console.print("[dim]          n/next | b/prev | r/rand[/dim]")
        self._console.print("[dim]Browse:[/dim]  s <query> = search | cat <name> = category")
        self._console.print("[dim]          ls = list | sort <key>[/dim]")
        self._console.print("[dim]Audio:[/dim]   v <0-100> = volume | m = mute")
        self._console.print("[dim]          f <n> = favorite | eq = equalizer[/dim]")
        self._console.print("[dim]Record:[/dim]  record = start | stoprec = stop[/dim]")
        self._console.print("[dim]Other:[/dim]   q = quit | h = help | log = logs[/dim]")

    def _show_vlc_info(self) -> None:
        import vlc
        ver = vlc.libvlc_get_version()
        if isinstance(ver, bytes):
            ver = ver.decode("utf-8")
        self._console.print(f"[green]VLC: {ver}[/green]")

    def _show_station_info(self) -> None:
        if 0 <= self._current < len(self._stations):
            s = self._stations[self._current]
            self._console.print(f"[cyan]Name:[/cyan] {s.get('name')}")
            self._console.print(f"[cyan]URL:[/cyan] {s.get('url')}")
            self._console.print(f"[cyan]Country:[/cyan] {s.get('country')}")
            self._console.print(f"[cyan]Tags:[/cyan] {s.get('tags')}")
            self._console.print(f"[cyan]Bitrate:[/cyan] {s.get('bitrate')}")
            self._console.print(f"[cyan]Codec:[/cyan] {s.get('codec')}")
            self._console.print(f"[cyan]Votes:[/cyan] {s.get('votes')}")

    def _show_log(self, args: list[str]) -> None:
        try:
            n = int(args[0]) if args else 30
        except ValueError:
            n = 30
        path = get_log_path()
        if not os.path.exists(path):
            self._console.print("[yellow]No log file[/yellow]")
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-n:]:
            self._console.print(line.rstrip())

    def _show_preload_status(self) -> None:
        status = get_preload_status()
        for cat, done in status.items():
            self._console.print(f"[{'green' if done else 'yellow'}]  {cat}: {'done' if done else 'pending'}[/]")

    def _sep(self) -> None:
        self._console.print()

    def _on_permanent_failure(self, url: str) -> None:
        self._console.print(f"[red]Failed permanently: {url}[/red]")

    def _shutdown(self) -> None:
        stop_refresh_timer()
        if self._sleep_cancel:
            self._sleep_cancel.set()
        if self._player:
            vol = 70
            s = None
            if 0 <= self._current < len(self._stations):
                s = self._stations[self._current]
            save_session(vol, s)
            self._player.shutdown()
        self._console.print("[cyan]Goodbye![/cyan]")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--category", default=None)
    args = parser.parse_args()
    RadioCLI().run(args.category)