# PowerShell Radio Pro

[![CI](https://github.com/nishanth-kkj9/radio_app_cli_powershell/actions/workflows/ci.yml/badge.svg)](https://github.com/nishanth-kkj9/radio_app_cli_powershell/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white)
![VLC](https://img.shields.io/badge/audio-libVLC-FF8800?logo=vlc&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

A Windows-native internet radio player designed for PowerShell and Windows Terminal. It combines **Radio Browser** station discovery, **libVLC** playback through `python-vlc`, a Rich terminal interface, station artwork, a 10-band equalizer, favorites/history, background caching, reconnect logic, and MP3 recording.

> **Status:** Beta (`2.0`). The project is Windows-focused and expects a local 64-bit VLC installation when using 64-bit Python.

## Highlights

- 📻 Radio Browser discovery through multiple API mirrors
- ▶️ Direct `python-vlc` / libVLC playback — no `cvlc` subprocess or RC socket
- 🔁 Event-driven recovery plus periodic health checks and bounded reconnects
- 🎚 10-band EQ with presets and custom `-20..+20 dB` gains
- 🎨 Unicode sextant artwork, Sixel bitmap output, and half-block fallback
- ⭐ Favorites, recent stations, and session restore
- 💾 Persistent station/category cache with atomic writes
- ⏱ Sleep timer and live ICY metadata
- 🎙 Stream recording with MP3 transcoding
- 🧪 Pytest suite with a fake VLC implementation, so most tests do not need VLC
- 🪟 PowerShell launcher with dependency diagnostics and UTF-8 terminal setup

## Requirements

| Requirement | Supported | Notes |
|---|---|---|
| Windows | Supported platform | The project is intentionally Windows-focused |
| Python | 3.9+ | 64-bit Python is recommended when using 64-bit VLC |
| VLC | 3.x | `libvlc.dll` must be available to `python-vlc` |
| Windows Terminal | Recommended | Best support for Unicode artwork and truecolor |

Python dependencies are declared in `pyproject.toml`; development dependencies add `pytest`, `pytest-cov`, and `ruff`.

## Installation

### Recommended: PowerShell launcher

From the repository root:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\Start-Radio.ps1
```

The launcher locates Python, checks for VLC, installs the editable package if required, configures UTF-8 console I/O, and starts the application.

Useful launcher options:

```powershell
.\Start-Radio.ps1 -Help
.\Start-Radio.ps1 -Check
.\Start-Radio.ps1 -Category jazz
```

### Development installation

```powershell
python -m pip install -e .[dev]
python -m radio_ps
```

The package also exposes the `radio` console entry point:

```powershell
radio
radio --version
radio --check
radio --category jazz
```

## Categories

Built-in browsing categories are:

`top` · `hindi` · `kannada` · `pop` · `rock` · `jazz` · `classical` · `news` · `favorites` · `recent`

The first eight are fetched from Radio Browser. `favorites` and `recent` are local views maintained by the application.

## Command reference

### Playback

| Command | Action |
|---|---|
| `<number>` / `p <n>` | Play a station by list number |
| `stop` | Stop playback |
| `pause` / `pp` | Pause or resume |
| `n` / `next` | Next station |
| `b` / `prev` | Previous station |
| `r` / `rand` | Play a random station |
| `now` | Show current station, metadata, and player state |
| `info` | Show detailed station information |

### Browse

| Command | Action |
|---|---|
| `s <query>` | Search Radio Browser |
| `cat <name\|#>` | Switch category by name or number |
| `ls` | Redraw the station list |
| `sort <key>` | Sort by `name`, `bitrate`, `votes`, or `country` |

### Audio and favorites

| Command | Action |
|---|---|
| `v <0-100>` | Set volume |
| `m` | Toggle mute |
| `f <n>` | Add/remove a station from favorites |
| `eq` | Show equalizer panel |
| `eq <preset>` | Apply an EQ preset; unique partial names work |
| `eq custom <b0...b9>` | Set ten custom bands, clamped to ±20 dB |
| `sleep <minutes>` | Start/restart the sleep timer |

### Recording and system

| Command | Action |
|---|---|
| `record [name]` | Record the current stream to MP3 |
| `stoprec` | Stop recording and show the saved path |
| `vlcinfo` | Show the loaded libVLC version |
| `datadir` | Show the application data directory |
| `log [N]` | Print recent log lines |
| `preload_status` | Show background category preload status |
| `refresh` | Refresh station caches |
| `clean` / `cls` | Clear and redraw the terminal |
| `h` | Show full in-app help |
| `q` | Quit and save session state |

For the authoritative command behavior, see [`docs/COMMANDS.md`](docs/COMMANDS.md).

## Equalizer

The player exposes ten ISO-style centre frequencies:

`60Hz`, `170Hz`, `310Hz`, `600Hz`, `1kHz`, `3kHz`, `6kHz`, `12kHz`, `14kHz`, `16kHz`.

Built-in presets include `None`, `Bass Boost`, `Treble Boost`, `Rock`, `Pop`, `Jazz`, `Classical`, `Dance`, `Vocal Boost`, `Flat`, and `Custom`.

## Artwork

Artwork is downloaded from station favicon URLs, cached locally, and rendered without external image subprocesses. The renderer can use:

- **Sextant** — Unicode 2×3 cells for high-density terminal artwork
- **Sixel** — true bitmap output when the terminal supports Sixel
- **Half-block** — compatibility fallback for older terminals
- **Monogram** — deterministic fallback when no usable artwork exists

Set the renderer with:

```powershell
$env:RADIO_PS_ART = "sextant"
$env:RADIO_PS_ART = "sixel"
$env:RADIO_PS_ART = "half"
```

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for terminal behavior and environment-variable details.

## Data and persistence

By default, application data is stored under:

```text
%APPDATA%\PowerShellRadioPro\
```

Important files/directories include:

```text
favorites.json              # favorite stations
recent.json                 # up to 20 recent stations
session.json                # volume + last station
cache\stations.json         # persisted station/category cache
cache\logos\               # downloaded artwork cache
recordings\                # MP3 recordings
radio_log.txt               # rotating application log
```

Set `RADIO_PS_DATA_DIR` to use another location. Writes use temporary files plus `os.replace()` where appropriate to reduce corruption risk.

## Architecture

```text
PowerShell / Windows Terminal
          │
          ▼
   Start-Radio.ps1 / radio_ps.main
          │
          ▼
      RadioCLI
       │   │
       │   ├── storage / logger / artwork
       │   │
       ▼   ▼
 StationService ──────► Radio Browser API
       │
       ▼
   RadioPlayer ───────► python-vlc ─────► libVLC ─────► Internet stream
       │
       ├── reconnect / health monitor
       ├── metadata
       ├── equalizer
       └── recording
```

The code follows a `src/radio_ps` package layout. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for component responsibilities, lifecycle, concurrency, and data flow.

## Why libVLC?

The current player uses `python-vlc` directly instead of controlling a `cvlc` subprocess over a remote-control socket. This gives the application typed VLC state, native media-player events, direct volume/EQ APIs, ICY metadata access, and recording through one VLC instance without port management or socket parsing.

## Security considerations

The Radio Browser client sanitizes station URLs before they reach the player and only accepts schemes configured in `ALLOWED_STREAM_SCHEMES`. Network requests use TLS verification, bounded timeouts, retries for selected HTTP failures, and explicit user-agent strings. Artwork downloads are size-limited and require an image content type.

This is an internet-streaming desktop application, not a sandbox. Treat third-party station URLs and downloaded media as untrusted input and keep VLC and Python dependencies updated.

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting guidance.

## Development and testing

Install development dependencies:

```powershell
python -m pip install -e .[dev]
```

Run the same checks used by CI:

```powershell
ruff check src tests scripts
pytest
python -c "from radio_ps.main import main; print('OK')"
```

For a broader headless feature sweep:

```powershell
python scripts/selfcheck.py
```

The test suite installs a fake `vlc` module before importing the player, allowing unit and CLI tests to run without a local VLC installation. Network calls are stubbed in the CLI fixture.

CI runs on `windows-latest` with Python 3.11 and performs linting, pytest, and an import smoke test.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, data flow, concurrency, and lifecycle |
| [`docs/COMMANDS.md`](docs/COMMANDS.md) | Detailed CLI command reference |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | Environment variables, paths, and runtime settings |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Development workflow, tests, linting, and CI |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Common installation/runtime problems |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution workflow and coding standards |
| [`SECURITY.md`](SECURITY.md) | Security model and vulnerability reporting |
| [`SUPPORT.md`](SUPPORT.md) | Getting help and reporting problems |
| [`CHANGELOG.md`](CHANGELOG.md) | User-visible project history |

## License

Released under the [MIT License](LICENSE).
