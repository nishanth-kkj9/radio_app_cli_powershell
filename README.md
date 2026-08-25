# PowerShell Radio Pro

![Version](https://img.shields.io/badge/version-2.0-blue) ![Python](https://img.shields.io/badge/python-3.9%2B-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

Internet radio player for **Windows PowerShell** — fully native, no WSL2, no Linux tools.
Built on **python-vlc** (libvlc bindings) for rock-solid audio with zero subprocess hacks.

## Features

- 📡 **Live stations** from the Radio Browser network (multi-mirror, auto-retry)
- 🔁 **Self-healing playback** — event-driven reconnect with exponential backoff
- 🎨 **Sextant pixel art** — station logos rendered at 72×72 px in your terminal
- 🎚 **10-band equalizer** with presets and manual band control
- ⏺ **Stream recording** to MP3 in parallel with playback
- ⭐ **Favorites & history** with session restore (volume + last station)
- 💤 Sleep timer, live ICY track metadata, background category preloading

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| [Python](https://www.python.org/downloads/) | 3.9+ | Check "Add to PATH" during install |
| [VLC](https://www.videolan.org/vlc/) | 3.x 64-bit | Must match Python bitness |
| Windows Terminal | any | Recommended for Unicode/color/sextant glyphs |

## Quick Start

```powershell
# 1. Open PowerShell in the repository root

# 2. Allow running scripts (one-time, if blocked):
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 3. Run
.\Start-Radio.ps1

# Start on a specific category
.\Start-Radio.ps1 -Category jazz
.\Start-Radio.ps1 -Category hindi

# Check dependencies
.\Start-Radio.ps1 -Check
```

The launcher locates Python and VLC, installs missing packages, and starts the app.

### Manual install

```powershell
pip install -e .
python -m radio_ps            # Top Charts
python -m radio_ps -c jazz    # specific category
python -m radio_ps --check    # diagnose installation
```

## Commands

### Playback

| Command | Description |
|---|---|
| `<number>` or `p <n>` | Play station by list number |
| `stop` | Stop playback |
| `pause` | Pause / resume playback |
| `n` / `next` | Next station |
| `b` / `prev` | Previous station |
| `r` / `rand` | Random station |
| `now` | Current station + track + VLC state |
| `info` | Full station details, codec, votes |

### Browse

| Command | Description |
|---|---|
| `s <query>` | Search Radio Browser |
| `cat <name\|#>` | Switch category by name or number |
| `ls` | Redraw station list |
| `sort <key>` | Sort by `name` `bitrate` `votes` `country` |

**Categories:** `top` `hindi` `kannada` `pop` `rock` `jazz` `classical` `news` `favorites` `recent`

### Audio

| Command | Description |
|---|---|
| `v <0-100>` | Set volume |
| `m` | Toggle mute |
| `f <n>` | Add station to favorites |
| `eq` | Show 10-band EQ panel |
| `eq <name>` | Apply preset — partial names work (`eq bass`) |
| `eq custom <b0…b9>` | Set all 10 bands manually (−20…+20 dB) |
| `sleep <minutes>` | Sleep timer (run again to restart) |

### Recording

| Command | Description |
|---|---|
| `record [name]` | Record current stream to MP3 |
| `stoprec` | Stop recording, show saved path |

Recordings save to `%APPDATA%\PowerShellRadioPro\recordings\`.

### System

| Command | Description |
|---|---|
| `vlcinfo` | Show libvlc version |
| `datadir` | Show data directory |
| `log [N]` | Print last N log lines (default 30) |
| `preload_status` | Background preload progress |
| `refresh` | Force-refresh all category caches |
| `clean` / `cls` | Clear terminal and redraw |
| `h` | Full help |
| `q` | Quit and save session |

## EQ Presets

`None` · `Bass Boost` · `Treble Boost` · `Rock` · `Pop` · `Jazz` · `Classical` · `Dance` · `Vocal Boost` · `Flat` · `Custom`

Partial names match uniquely — `eq bass` applies Bass Boost. See in-app `eq` panel for per-band gains.

## Configuration

Environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `RADIO_PS_DATA_DIR` | `%APPDATA%\PowerShellRadioPro` | Data/cache directory override |
| `RADIO_PS_ART` | `sextant` | Artwork mode: `sixel` renders true bitmaps (Windows Terminal 1.22+), `half` for legacy terminals |

## Data Files

All data lives in `%APPDATA%\PowerShellRadioPro\`:

| File | Contents |
|---|---|
| `favorites.json` | Saved favorite stations |
| `recent.json` | Recently played (up to 20) |
| `session.json` | Last station + volume (restored on launch) |
| `recordings\` | Stream recordings |
| `cache\logos\` | Downloaded station logos |
| `radio_log.txt` | Rotating log (2MB × 3 files) |

## Development

```powershell
pip install -e .[dev]
pytest                    # unit + CLI tests (no VLC needed)
python scripts/selfcheck.py   # headless full-feature self-check
```

Tests inject a fake `vlc` module via `tests/conftest.py`, so they run on machines without VLC. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture

```
.
├── pyproject.toml          # Package config (src layout, deps)
├── Start-Radio.ps1         # PowerShell launcher
├── src/radio_ps/
│   ├── main.py             # Entry point, arg parsing
│   ├── core/               # player (libvlc), api, equalizer, config
│   ├── services/           # station_service (cache, preload, liveness)
│   ├── ui/                 # cli_ui (Rich REPL), art (sextant renderer)
│   └── utils/              # logger, storage (atomic JSON), paths
├── tests/                  # pytest suite (fake vlc)
└── scripts/selfcheck.py    # Headless feature self-check
```

### Why python-vlc instead of cvlc + RC socket?

The original design drove a `cvlc` subprocess over a TCP RC interface:
banner draining, socket I/O on every health check, port conflicts, string-parsed
status output. v2.0 uses libvlc bindings directly:

- Native event callbacks (`MediaPlayerPlaying`, `EncounteredError`, `EndReached`)
- Typed `vlc.State` enum — no parsing
- ICY metadata via `media.get_meta(vlc.Meta.NowPlaying)`
- `vlc.AudioEqualizer` — 10-band EQ in the audio pipeline
- `sout` recording parallel to playback, one shared VLC instance

## Troubleshooting

**`libvlc not found`**
- Install VLC 64-bit from [videolan.org](https://www.videolan.org/vlc/)
- Confirm Python bitness matches: `python -c "import struct; print(struct.calcsize('P')*8)"`
- Or add VLC to PATH: `$env:PATH += ";C:\Program Files\VideoLAN\VLC"`

**`python-vlc is not installed`**

```powershell
pip install python-vlc
```

**Garbled characters / boxes instead of art**
- Use Windows Terminal, not legacy conhost
- Launcher sets UTF-8 automatically; manually: `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`
- Legacy terminal without sextant glyphs: `$env:RADIO_PS_ART = 'half'`

**`Set-ExecutionPolicy` error**

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## License

[MIT](LICENSE)
