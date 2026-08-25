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
import re
import time
import threading
import random as _random
import datetime

try:
    # Availability probe: importing readline enables line editing on POSIX.
    import readline  # noqa: F401
except ImportError:
    pass

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.text    import Text
from rich.rule    import Rule
from rich         import box

from radio_ps import __version__
from radio_ps.core.config   import CATEGORIES
from radio_ps.core.player   import RadioPlayer
from radio_ps.core.api      import fetch_stations
from radio_ps.services.station_service import (
    fetch_category,
    preload_categories,
    get_preload_status,
    start_refresh_timer,
    stop_refresh_timer,
    refresh_categories,
)
from radio_ps.utils.storage import (
    load_favorites, save_favorites,
    load_recent,    save_recent,
    load_session,   save_session,
    get_data_dir,
)
from radio_ps.utils.logger import log, get_log_path
from radio_ps.utils import paths
from radio_ps.ui.art import render_logo, render_sixel, volume_bar, art_mode


# ── Constants ──────────────────────────────────────────────────────────────────

_SPINNER     = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
_MAX_MARQUEE = 60
_APP_NAME    = "PowerShell Radio Pro"
_APP_VER     = __version__   # single source of truth: radio_ps.__init__

# ── Startup logo ───────────────────────────────────────────────────────────────

_LOGO_ART = [
    "  ____  ____     ____          _ _ ",
    " |  _ \\/ ___|   |  _ \\ __ _ __| (_) ___",
    " | |_) \\___ \\   | |_) / _` / _` | |/ _ \\",
    " |  __/ ___) |  |  _ < (_| | (_| | | (_) |",
    " |_|   |____/   |_|\\_\\__,_|\\__,_|_|\\___/",
]

_GRAD_FROM = (56, 224, 255)   # bright cyan
_GRAD_TO   = (255, 94, 190)   # hot pink


def _gradient_logo() -> Text:
    """Render the startup ASCII logo with a horizontal cyan→pink gradient."""
    t = Text()
    for line in _LOGO_ART:
        n = max(1, len(line) - 1)
        for i, ch in enumerate(line):
            f = i / n
            r = int(_GRAD_FROM[0] + (_GRAD_TO[0] - _GRAD_FROM[0]) * f)
            g = int(_GRAD_FROM[1] + (_GRAD_TO[1] - _GRAD_FROM[1]) * f)
            b = int(_GRAD_FROM[2] + (_GRAD_TO[2] - _GRAD_FROM[2]) * f)
            t.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
        t.append("\n")
    return t

# state label -> (display, style)
_STATE_UI = {
    "playing":      ("▶ Playing",       "bold green"),
    "paused":       ("⏸ Paused",        "yellow"),
    "opening":      ("◌ Connecting…",   "yellow"),
    "buffering":    ("◌ Buffering…",    "yellow"),
    "reconnecting": ("↻ Reconnecting…", "yellow"),
    "stopped":      ("■ Stopped",       "red"),
    "ended":        ("■ Ended",         "red"),
    "error":        ("✖ Error",         "bold red"),
}


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


_COUNTRY_ALIASES = {
    "united states of america": "USA",
    "united states":            "USA",
    "usa":                      "USA",
    "united kingdom of great britain and northern ireland": "UK",
    "united kingdom":           "UK",
    "russian federation":       "Russia",
    "netherlands (kingdom of the)": "Netherlands",
    "kingdom of the netherlands":   "Netherlands",
}


def _short_country(name: str, max_len: int = 14) -> str:
    """Compact a country name for the table: drop 'The', alias long names."""
    if not name:
        return ""
    n = name.strip()
    n = re.sub(r"^the\s+", "", n, flags=re.IGNORECASE)
    n = n.split(",")[0].split("(")[0].strip()
    n = _COUNTRY_ALIASES.get(n.lower(), n)
    return _truncate(n, max_len)


def _match_preset(token: str, presets: dict) -> str | None:
    """
    Resolve user input to an EQ preset key.
    Exact (case-insensitive) → unique prefix → unique substring → None.
    """
    lowered = token.strip().lower()
    keys = list(presets.keys())
    for k in keys:
        if k.lower() == lowered:
            return k
    starts = [k for k in keys if k.lower().startswith(lowered)]
    if len(starts) == 1:
        return starts[0]
    contains = [k for k in keys if lowered in k.lower()]
    if len(contains) == 1:
        return contains[0]
    return None


# ── RadioCLI ───────────────────────────────────────────────────────────────────

class RadioCLI:
    def __init__(self):
        self._console = Console(force_terminal=True, color_system="truecolor")
        self._player = None
        self._stations: list[dict] = []
        self._by_url: dict[str, dict] = {}
        self._current = 0
        self._category = "top"
        self._favorites: list[dict] = []
        self._recent: list[dict] = []
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
        self._console.print(_gradient_logo())
        title = Text()
        title.append("♪ ", style="bold magenta")
        title.append(_APP_NAME, style="bold cyan")
        title.append(f" v{_APP_VER}", style="dim")
        title.append("  ·  ", style="dim")
        title.append("Internet radio for Windows PowerShell", style="italic dim")
        self._console.print(Text(" " * 4) + title)
        hints = Text("    ")
        for keys, desc in (("p/n/b/r", "play"), ("v/m", "vol"), ("s", "search"),
                           ("eq", "EQ"), ("record", "rec"), ("h", "help"), ("q", "quit")):
            hints.append(f"{keys}", style="bold cyan")
            hints.append(f" {desc}   ", style="dim")
        self._console.print(hints)
        self._console.print(Rule(style="dim cyan"))

    def _fetch_initial(self, category: str) -> None:
        try:
            with self._console.status(f"[cyan]Loading {category}…[/cyan]", spinner="dots"):
                self._load_category(category)
        except Exception as e:
            self._console.print(f"[red]Could not load '{category}': {e}[/red]")
        self._list_stations()
        threading.Thread(target=preload_categories, daemon=True, name="preload").start()
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
        total = len(self._stations)
        current_url = self._player.get_current_url() if self._player else None
        fav_urls = {f.get("url") for f in self._favorites}

        t = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.ROUNDED,
            border_style="dim cyan",
            row_styles=["", "dim"],
            caption=(
                f"[dim]Showing first 40 of {total} stations[/dim]"
                if total > 40 else f"[dim]{total} station{'s' if total != 1 else ''}"
                f"  ·  [cyan]{self._category}[/cyan][/dim]"
            ),
        )
        t.add_column("#", width=4, justify="right")
        t.add_column("Station", width=42)
        t.add_column("Country", width=14, style="dim")
        t.add_column("Quality", width=8, justify="center")
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, s in enumerate(self._stations[:40], 1):
            is_current = (
                i == self._current + 1 and s.get("url") == current_url
            )
            rank = medals.get(i, str(i))
            name = s.get("name", "?")
            if s.get("url") in fav_urls:
                name += " ★"
            if is_current:
                name = f"▶ {name}"
                style = "bold green"
            else:
                style = ""
            t.add_row(
                Text(rank, style="bold yellow" if i <= 3 else "cyan"),
                Text(_truncate(name, 41), style=style or None),
                _short_country(s.get("country", "")),
                _quality_badge(s.get("bitrate", 0)),
            )
        self._console.print(t)

    def _clear_screen(self) -> None:
        """Reliably clear the terminal.

        Rich's Console.clear() only emits ANSI ``\\x1b[2J``, which classic
        conhost under Windows PowerShell 5.1 mishandles - leaving the old
        screen content visible. Using the native clear command (``cls`` on
        Windows / ``clear`` elsewhere) guarantees a fully blank screen in the
        terminal the app is attached to. Skipped when stdout is not a real
        terminal (tests, scripts, pipes).
        """
        if not getattr(self._console, "is_terminal", False):
            return
        try:
            if os.name == "nt":
                os.system("cls")
            else:
                os.system("clear")
        except Exception:
            pass

    def _redraw(self) -> None:
        """Clear the terminal and redraw the current view.

        Used by the `clean`/`cls`/`clear` command so the screen is actually
        reset to a fresh, useful state (welcome header + playback status +
        station list) instead of going blank.
        """
        self._clear_screen()
        self._console.print(_gradient_logo())
        title = Text("  ")
        title.append("♪ ", style="bold magenta")
        title.append(f"{_APP_NAME} v{_APP_VER}", style="bold cyan")
        title.append("  ·  ", style="dim")
        title.append(self._category or "", style="bold cyan")
        title.append("  ·  ", style="dim")
        title.append("type h for help", style="italic dim")
        self._console.print(title)
        self._console.print()
        if self._player and self._player.is_playing():
            self._show_now_playing()
            self._sep()
        self._list_stations()

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
        meta = self._player.get_current_metadata()
        raw_title = (meta.get("title") or "").strip()
        url = self._player.get_current_url() or ""
        # VLC reports the URL filename as Title when a stream has no ICY
        # metadata - hide those fragments instead of showing garbage.
        basename = os.path.basename(url.split("?")[0])
        title = "" if (
            not raw_title
            or raw_title == basename
            or "?" in raw_title
            or raw_title.lower().endswith((".m3u8", ".mp3", ".aac", ".pls"))
        ) else raw_title
        state = self._player.get_state_label()
        playing = self._player.is_playing()

        # Sixel mode: true bitmap above a borderless info block. Rich mangles
        # ESC sequences, so the sixel payload goes straight to stdout.
        if art_mode() == "sixel":
            sixel_art = render_sixel(s.get("logo", ""))
            if sixel_art:
                content = Text()
                content.append(_clean_name(s.get("name", "?")), style="bold cyan")
                if s.get("country"):
                    content.append(f"\n{s['country']}", style="dim")
                if title:
                    content.append(f"\n♪ {title}", style="green")
                label, style = _STATE_UI.get(state, ("• " + state, "cyan"))
                line = f"{label}"
                if state == "playing" and self._start_time:
                    line += f"  ·  {_fmt_elapsed(int(time.time() - self._start_time))}"
                content.append("\n" + line, style=style)
                content.append("\nvol ", style="dim")
                content.append_text(volume_bar(self._player.get_volume()))
                self._console.file.write(sixel_art + "\n")
                self._console.print(content)
                return

        content = Text()
        content.append(_clean_name(s.get("name", "?")), style="bold cyan")
        if s.get("country"):
            content.append(f"\n{s['country']}", style="dim")
        if title:
            content.append(f"\n♪ {title}", style="green")
        label, style = _STATE_UI.get(state, ("• " + state, "cyan"))
        line = f"{label}"
        if state == "playing" and self._start_time:
            line += f"  ·  {_fmt_elapsed(int(time.time() - self._start_time))}"
        content.append("\n" + line, style=style)

        # Status row: volume gauge + EQ preset
        content.append("\n")
        status = Text()
        status.append("vol ", style="dim")
        status.append(volume_bar(self._player.get_volume()))
        eq = self._player.equalizer
        if eq.enabled and eq.current_preset != "None":
            status.append("   eq ", style="dim")
            status.append(eq.current_preset, style="bold magenta")
            status.append(" on", style="dim")
        content.append_text(status)

        grid = Table.grid(padding=(0, 2))
        grid.add_column(vertical="middle")
        grid.add_column(vertical="middle")
        art = render_logo(s.get("logo", ""), s.get("name", "?"))
        grid.add_row(art, content)

        if state == "playing":
            border = "green"
        elif state in ("opening", "buffering", "reconnecting"):
            border = "yellow"
        else:
            border = "red" if state in ("stopped", "ended", "error") else "cyan"
        p = Panel(
            grid,
            title="♪ Now Playing",
            title_align="left",
            border_style=border,
            box=box.HEAVY if playing else box.ROUNDED,
            padding=(0, 2),
            width=max(52, min(self._console.width or 64, 84)),
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
                line = self._console.input("[bold cyan]❯[/bold cyan] ").strip()
                if not line:
                    continue
                if self._dispatch(line):
                    break
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                self._console.print(f"[red]Error: {e}[/red]")
                log(f"Command error: {e}", "error")
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
            self._redraw()
        elif cmd in ("preload_status",):
            self._show_preload_status()
        elif cmd in ("refresh",):
            with self._console.status("[cyan]Refreshing all categories…[/cyan]", spinner="dots"):
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
        elif cmd == "s":
            self._console.print("[red]Usage: s <query>[/red]")
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
        elif cmd in ("stop", "stopplay"):
            self._player.stop()
            self._start_time = None
            self._console.print("[yellow]Stopped[/yellow]")
        elif cmd in ("pause", "pp"):
            self._cmd_pause()
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
        try:
            with self._console.status(f"[cyan]Searching for '{query}'…[/cyan]", spinner="dots"):
                results = fetch_stations(query, limit=30)
        except Exception:
            results = []
        if results:
            self._stations = results
            self._by_url = {s["url"]: s for s in self._stations}
            self._category = "search"
            self._list_stations()
        else:
            self._console.print(f"[yellow]No results for '{query}'[/yellow]")

    def _cmd_category(self, args: list[str]) -> None:
        cat = args[0].lower()
        if cat.isdigit():
            idx = int(cat) - 1
            if not (0 <= idx < len(CATEGORIES)):
                self._console.print(
                    f"[red]Invalid category number.[/red] [dim]1-{len(CATEGORIES)}: "
                    + ", ".join(f"{i+1}={key}" for i, (_, key) in enumerate(CATEGORIES))
                    + "[/dim]"
                )
                return
            cat = CATEGORIES[idx][1]
        try:
            with self._console.status(f"[cyan]Loading {cat}…[/cyan]", spinner="dots"):
                self._load_category(cat)
        except Exception as e:
            self._console.print(f"[red]Could not load '{cat}': {e}[/red]")
            return
        self._list_stations()

    def _cmd_sort(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage: sort <name|bitrate|votes|country>[/red]")
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
        except (ValueError, IndexError):
            self._console.print("[red]Usage: v <0-100>[/red]")
            return
        vol = max(0, min(100, vol))
        self._player.set_volume(vol)
        self._console.print(Text.assemble(("VOL ", "dim"), volume_bar(vol)))

    def _cmd_mute(self) -> None:
        muted = self._player.toggle_mute()
        icon = "🔇" if muted else "🔊"
        color = "red" if muted else "green"
        self._console.print(f"[{color}]{icon} Mute: {'ON' if muted else 'OFF'}[/]")

    def _cmd_pause(self) -> None:
        if not self._player.get_current_url():
            self._console.print("[red]Nothing playing[/red]")
            return
        result = self._player.toggle_pause()
        if result is None:
            self._console.print("[yellow]Nothing to pause right now[/yellow]")
        elif result:
            self._console.print("[yellow]⏸ Paused — 'pause' to resume[/yellow]")
        else:
            self._console.print("[green]▶ Resumed[/green]")

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
        state = "on" if eq.enabled else "off"

        def _meter(gain: float) -> Text:
            half = 10
            filled = int(round(abs(gain) / 20 * half))
            if gain and filled == 0:
                filled = 1  # ±1 dB still deserves a visible notch
            t = Text()
            if gain < 0:
                t.append("█" * filled, style="bold red")
                t.append("·" * (half - filled), style="dim")
                t.append("┼", style="bold white")
                t.append("·" * half, style="dim")
            else:
                t.append("·" * half, style="dim")
                t.append("┼", style="bold white")
                t.append("█" * filled, style="bold green")
                t.append("·" * (half - filled), style="dim")
            return t

        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="right", min_width=6)
        grid.add_column()
        grid.add_column(justify="right", width=7)
        for i, label in enumerate(eq.BAND_LABELS):
            gain = eq.get_bands()[i]
            grid.add_row(
                Text(label, style="cyan"),
                _meter(gain),
                Text(f"{gain:+.0f} dB", style="dim"),
            )
        self._console.print(Panel(
            grid,
            title=f"🎚 EQ · {eq.current_preset} ({state})",
            title_align="left",
            border_style="magenta",
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    def _show_eq_presets(self) -> None:
        """List all available EQ presets, marking the active one."""
        eq = self._player.equalizer
        labels = eq.BAND_LABELS
        t = Table(
            show_header=False,
            box=box.ROUNDED,
            border_style="dim magenta",
            padding=(0, 2),
            title="🎚 Available EQ Presets",
            title_justify="left",
        )
        t.add_column(width=2)       # current marker
        t.add_column(min_width=14)  # preset name
        t.add_column()              # band summary
        for name, bands in eq.PRESETS.items():
            current = name == eq.current_preset
            if name == "None":
                summary = "EQ off (bypass)"
            elif name == "Flat":
                summary = "all bands 0 dB"
            elif name == "Custom":
                summary = "set via: eq custom <b0…b9>"
            else:
                summary = "  ".join(f"{labels[i]} {g:+.0f}" for i, g in bands)
            t.add_row(
                Text("►" if current else "", style="bold green"),
                Text(name, style="bold magenta" if current else "white"),
                Text(summary, style="dim"),
            )
        self._console.print(t)
        self._console.print(
            "[dim]eq <preset>  apply (partial names ok: eq bass, eq jazz)  ·  "
            "eq custom <b0…b9>  set all 10 bands (-20…+20 dB)[/dim]"
        )

    def _cmd_eq(self, args: list[str]) -> None:

        if not args:
            self._show_eq()
            return
        if args[0].lower() in ("h", "help", "?", "ls", "list", "presets"):
            self._show_eq_presets()
            return
        if args[0].lower() == "custom" and len(args) > 1:
            try:
                bands = [float(x) for x in args[1:]]
            except ValueError:
                self._console.print("[red]Invalid band values[/red]")
                return
            if len(bands) != 10:
                self._console.print("[red]Need exactly 10 band values[/red]")
                return
            self._player.toggle_equalizer(True)
            self._player.equalizer.set_custom_bands(bands)
            self._console.print("[green]Custom EQ set[/green]")
            return
        preset = _match_preset(args[0], self._player.equalizer.PRESETS)
        if preset is None:
            options = ", ".join(self._player.equalizer.PRESETS)
            self._console.print(f"[red]Unknown preset '{args[0]}'.[/red]")
            self._console.print(f"[dim]Options: {options}[/dim]")
            self._console.print("[dim]Partial names work (e.g. 'eq bass')[/dim]")
            return
        self._player.toggle_equalizer(preset != "None")
        self._player.set_equalizer_preset(preset)
        self._console.print(f"[green]EQ: {preset}{' (off)' if preset == 'None' else ''}[/green]")

    def _cmd_record(self, args: list[str]) -> None:
        if self._recording:
            self._console.print("[yellow]Already recording[/yellow]")
            return
        url = self._player.get_current_url()
        if not url:
            self._console.print("[red]Nothing playing[/red]")
            return
        audio_dir = paths.get_recordings_dir()
        try:
            os.makedirs(audio_dir, exist_ok=True)
        except OSError as e:
            self._console.print(f"[red]Cannot create recording directory {audio_dir}: {e}[/red]")
            return
        name = " ".join(args) if args else datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = os.path.basename(name.strip())
        name = re.sub(r"[^A-Za-z0-9_ \-]", "", name)[:80].strip()
        if not name:
            self._console.print("[red]Invalid recording name[/red]")
            return
        path = os.path.join(audio_dir, f"{name}.mp3")
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
        except (ValueError, IndexError):
            self._console.print("[red]Usage: sleep <minutes>[/red]")
            return
        if self._sleep_thread and self._sleep_thread.is_alive():
            self._sleep_cancel.set()
            self._console.print("[yellow]Previous sleep timer cancelled[/yellow]")
        self._sleep_cancel = threading.Event()
        self._sleep_timer = mins

        def _sleep_task():
            for i in range(mins * 60, 0, -60):
                if self._sleep_cancel.is_set():
                    return
                time.sleep(60)
            if self._sleep_cancel.is_set():
                return
            self._player.stop()
            self._console.print("[cyan]Sleep timer: playback stopped[/cyan]")

        self._sleep_thread = threading.Thread(target=_sleep_task, daemon=True)
        self._sleep_thread.start()
        self._console.print(f"[green]Sleep in {mins} min[/green]")

    def _show_help(self) -> None:
        groups = [
            ("▶  Playback", "bold green", [
                ("<n> / p <n>", "Play station by list number"),
                ("stop",         "Stop playback"),
                ("pause",        "Pause / resume"),
                ("n / next",     "Next station"),
                ("b / prev",     "Previous station"),
                ("r / rand",     "Random station"),
                ("now",          "Current station + track + VLC state"),
                ("info",         "Full station details & codec"),
            ]),
            ("🔎  Browse", "bold cyan", [
                ("s <query>",    "Search Radio Browser"),
                ("cat <name|#>", "Switch category"),
                ("ls",           "Redraw station list"),
                ("sort <key>",   "Sort: name · bitrate · votes · country"),
            ]),
            ("🎚  Audio", "bold magenta", [
                ("v <0-100>",    "Set volume"),
                ("m",            "Toggle mute"),
                ("f <n>",        "Toggle station as favorite"),
                ("eq [preset]",  "Show / apply EQ preset (partial ok)"),
                ("eq custom …",  "Set all 10 bands (-20…+20 dB)"),
                ("sleep <min>",  "Sleep timer (re-run to cancel)"),
            ]),
            ("⏺  Record", "bold red", [
                ("record [name]", "Record current stream to MP3"),
                ("stoprec",       "Stop recording, show saved file"),
            ]),
            ("⚙  System", "bold yellow", [
                ("vlcinfo",      "Show libvlc version"),
                ("datadir",      "Show config/data directory"),
                ("log [N]",      "Print last N log lines"),
                ("preload_status", "Background preload progress"),
                ("refresh",      "Force-refresh all category caches"),
                ("clean / cls",  "Clear terminal and redraw"),
                ("h / q",        "Help · Quit and save session"),
            ]),
        ]
        grid = Table.grid(padding=(0, 3))
        grid.add_column(justify="right", min_width=16)
        grid.add_column()
        for title, style, rows in groups:
            grid.add_row(Text(), Text())  # spacer
            grid.add_row(Text(title, style=style), Text())
            for cmd, desc in rows:
                grid.add_row(
                    Text(cmd, style="bold white"),
                    Text(desc, style="dim"),
                )
        self._console.print(Panel(
            grid,
            title="Commands",
            title_align="left",
            border_style="dim cyan",
            box=box.ROUNDED,
            padding=(0, 2),
        ))

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
            state = "done" if done else "pending"
            color = "green" if done else "yellow"
            self._console.print(f"[{color}]  {cat}: {state}[/]")

    def _sep(self) -> None:
        self._console.print()

    def _on_permanent_failure(self, url: str) -> None:
        self._console.print(f"[red]Failed permanently: {url}[/red]")

    def _shutdown(self) -> None:
        stop_refresh_timer()
        if self._sleep_cancel:
            self._sleep_cancel.set()
        if self._player:
            s = None
            if 0 <= self._current < len(self._stations):
                s = self._stations[self._current]
            save_session(self._player.get_volume(), s)
            self._player.shutdown()
        self._console.print(Rule(style="dim cyan"))
        bye = Text("  ")
        bye.append("♪ ", style="bold magenta")
        bye.append("Thanks for listening", style="bold cyan")
        bye.append(" — session saved", style="dim")
        self._console.print(bye)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--category", default=None)
    args = parser.parse_args()
    RadioCLI().run(args.category)
