# PowerShell Radio Pro v2.0

Internet radio player for **Windows PowerShell** — fully native, no WSL2, no Linux tools.
Built on **python-vlc** (libvlc bindings) for rock-solid audio with zero subprocess hacks.

---

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.9+ | [python.org](https://www.python.org/downloads/) — check "Add to PATH" |
| VLC | 3.x 64-bit | [videolan.org/vlc](https://www.videolan.org/vlc/) — must match Python bitness |
| Windows Terminal | any | Recommended for best Unicode/color rendering |

---

## Quick Start

```powershell
# 1. Open PowerShell in the radio_ps folder
# 2. Allow running scripts (one-time, if blocked):
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 3. Run
.\Start-Radio.ps1

# Start on a specific category
.\Start-Radio.ps1 -Category jazz
.\Start-Radio.ps1 -Category hindi

# Check all dependencies
.\Start-Radio.ps1 -Check
```

### Manual run (if you prefer):
```powershell
pip install -e .
python -m radio_ps
python -m radio_ps -c jazz
python -m radio_ps --check
```

---

## Commands

### Playback
| Command | Description |
|---|---|
| `<number>` or `p <n>` | Play station by list number |
| `stop` | Stop playback |
| `n` / `next` | Next station |
| `b` / `prev` | Previous station |
| `r` / `rand` | Random station |
| `now` | Show current station + track + VLC state |
| `info` | Full station details, codec, ICY metadata |

### Browse
| Command | Description |
|---|---|
| `s <query>` | Search Radio Browser (alive check included) |
| `cat <name\|#>` | Switch category |
| `ls` | Redraw station list |
| `sort <key>` | Sort by: `name` `bitrate` `votes` `country` |

**Categories:** `top` `hindi` `kannada` `pop` `rock` `jazz` `classical` `news` `favorites` `recent`

### Audio
| Command | Description |
|---|---|
| `v <0-100>` | Set volume |
| `m` | Toggle mute |
| `f <n>` | Toggle station as favorite |
| `eq` | Show EQ presets |
| `eq <name\|#>` | Apply preset (Bass Boost, Rock, Jazz, etc.) |
| `eq custom` | Show current 10-band values |
| `eq custom <b0…b9>` | Set all 10 bands manually (−20 to +20 dB) |
| `sleep <minutes>` | Sleep timer (run again to cancel) |

### Recording *(New in v2.0)*
| Command | Description |
|---|---|
| `record` | Record current stream to MP3 (auto filename) |
| `record <filename>` | Record with specific filename |
| `stoprec` | Stop recording and show saved file path |

Recordings are saved to `%APPDATA%\PowerShellRadioPro\` by default.

### System
| Command | Description |
|---|---|
| `vlcinfo` | Show libvlc version |
| `datadir` | Show config/data directory |
| `log [N]` | Print last N log lines (default 30) |
| `preload_status` | Show background preload progress |
| `refresh` | Force-refresh all category caches |
| `clean` / `cls` | Clear terminal and redraw |
| `h` | Full help |
| `q` | Quit and save session |

---

## EQ Presets

| Preset | Description |
|---|---|
| None | Flat — bypass EQ |
| Bass Boost | Powerful low-end boost (60Hz +15, 170Hz +12, 310Hz +10) |
| Treble Boost | Crisp highs (12kHz +10, 14kHz +12, 16kHz +10) |
| Rock | Strong low-end + bright highs |
| Pop | Vocal-forward with moderate bass |
| Jazz | Warm mids, gentle highs |
| Classical | Subtle lift (310Hz, 3kHz) |
| Dance | Heavy bass + bright treble |
| Vocal Boost | Boosted 600Hz–3kHz for clear speech/vocals |
| Custom | Set via `eq custom <b0…b9>` |

---

## Data Files

All data is stored in `%APPDATA%\PowerShellRadioPro\`:

| File | Contents |
|---|---|
| `favorites.json` | Saved favorite stations |
| `recent.json` | Recently played (up to 20) |
| `session.json` | Last station + volume (restored on next launch) |
| `radio_log.txt` | Rotating log (1MB × 2 files) |

---

## Architecture

```
radio_ps/
├── pyproject.toml              # Package config (src layout, deps, scripts)
├── README.md
├── Start-Radio.ps1            # PowerShell launcher
├── src/radio_ps/
│   ├── __init__.py           # __version__ = "2.0"
│   ├── main.py              # Entry point
│   ├── core/              # 5 modules (player, config, api, equalizer)
│   ├── services/          # station_service (with cache/preload)
│   ├── ui/               # cli_ui (Rich terminal UI + command REPL)
│   └── utils/            # logger, storage (atomic JSON writes)
└── tests/               # Test directory
```

### Why python-vlc instead of cvlc+RC socket?

The original `cli_v3` used a `cvlc` subprocess with a TCP RC interface:
- Had to drain VLC's welcome banner before sending commands
- Socket I/O on every health check (connect → read banner → send → read)
- Port conflicts if multiple instances run
- No native event system — polled `status` command to detect errors
- No native metadata — parsed RC text output

`python-vlc` (libvlc bindings) used in v2.0:
- Direct C API calls — no subprocess, no sockets, no port 4212
- Native event callbacks: `MediaPlayerPlaying`, `MediaPlayerEncounteredError`, `EndReached`
- `player.get_state()` returns typed `vlc.State` enum — no string parsing
- ICY metadata via `media.get_meta(vlc.Meta.NowPlaying)` — automatic
- `vlc.AudioEqualizer` API — 10-band EQ applied natively to the audio pipeline
- VLC recording via sout — parallel recording without affecting playback
- Single VLC instance shared across all operations

---

## Troubleshooting

**`libvlc not found`**
- Make sure VLC 64-bit is installed from https://www.videolan.org/vlc/
- Check that your Python is also 64-bit: `python -c "import struct; print(struct.calcsize('P')*8)"`
- Add VLC to PATH: `$env:PATH += ";C:\Program Files\VideoLAN\VLC"`

**`python-vlc is not installed`**
```powershell
pip install python-vlc
```

**Rich renders boxes as `?` or garbled characters**
- Use Windows Terminal (not legacy cmd.exe or old PowerShell host)
- The launcher sets UTF-8 encoding automatically

**`Set-ExecutionPolicy` error**
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
