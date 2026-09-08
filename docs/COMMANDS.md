# Command reference

This page expands the quick reference in `README.md`. The command dispatcher in `ui/cli_ui.py` remains the source of truth.

## Playback

| Command | Behavior |
|---|---|
| `<number>` | Play that station from the current list |
| `p <number>` | Explicit form of station playback |
| `stop` | Stop the current stream |
| `pause`, `pp` | Toggle pause/resume |
| `n`, `next` | Advance to the next station, wrapping around |
| `b`, `prev` | Move to the previous station |
| `r`, `rand` | Choose a random station |
| `now` | Display the Now Playing panel, including ICY metadata when available |
| `info` | Display detailed station information such as URL, country, tags, bitrate, codec, and votes |

## Browse and search

| Command | Behavior |
|---|---|
| `s <query>` | Search Radio Browser by station name/query |
| `cat <name>` | Select a category by key |
| `cat <number>` | Select a category by displayed position |
| `cat favorites` | Show saved favorites |
| `cat recent` | Show recent stations |
| `ls` | Redraw the current station table |
| `sort name` | Alphabetical station sort |
| `sort bitrate` | Sort by bitrate |
| `sort votes` | Sort by vote count |
| `sort country` | Sort by country |

Configured remote categories are `top`, `hindi`, `kannada`, `pop`, `rock`, `jazz`, `classical`, and `news`. Favorites and recent are local collections.

## Favorites and audio

`f <n>` toggles the selected station in the favorites collection and persists the result to `favorites.json`.

`v <0-100>` clamps the requested value to the player range and updates libVLC volume.

`m` toggles mute while retaining the configured volume for unmute.

## Equalizer

```text
eq                  # open/show the EQ panel
eq list             # list presets
eq jazz             # exact preset
eq bass             # unique partial match → Bass Boost
eq custom 1 2 3 4 5 6 7 8 9 10
eq none             # disable EQ
```

Custom mode requires exactly ten numeric gains. Each band is clamped to `-20..+20 dB`.

Presets:

- None
- Bass Boost
- Treble Boost
- Rock
- Pop
- Jazz
- Classical
- Dance
- Vocal Boost
- Flat
- Custom

## Recording

```text
record
record my_station
stoprec
```

Recordings are written under `%APPDATA%\PowerShellRadioPro\recordings\` by default. The implementation sanitizes the requested filename and uses a VLC transcoding chain to produce MP3 output.

## Sleep timer

```text
sleep 30
```

Running the command again replaces the current timer. The timer is cancelled when the application shuts down.

## Cache and diagnostics

| Command | Purpose |
|---|---|
| `preload_status` | Show background preload state for configured categories |
| `refresh` | Force a category refresh instead of waiting for the periodic timer |
| `vlcinfo` | Print the loaded libVLC version |
| `datadir` | Print the resolved persistent-data directory |
| `log` | Show recent application log entries |
| `log 100` | Show a larger number of recent log lines |
| `clean`, `cls` | Clear the terminal and redraw the UI |
| `h` | Show the complete interactive help |
| `q` | Save session state and quit |

## Startup options

The Python entry point supports:

```powershell
python -m radio_ps
python -m radio_ps --category jazz
python -m radio_ps -c hindi
python -m radio_ps --check
python -m radio_ps --version
```

The launcher adds equivalent convenience options:

```powershell
.\Start-Radio.ps1 -Help
.\Start-Radio.ps1 -Check
.\Start-Radio.ps1 -Category jazz
```
