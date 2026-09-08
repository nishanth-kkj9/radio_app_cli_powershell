# Architecture

PowerShell Radio Pro is a layered Windows CLI application. The UI owns user interaction; services own station discovery and caching; core modules own playback, networking policy, and audio processing; utilities own persistence and logging.

## Runtime layers

```text
┌──────────────────────────────────────────────────────────────┐
│ PowerShell / Windows Terminal                               │
│  Start-Radio.ps1  →  python -m radio_ps / radio             │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ ui/cli_ui.py — RadioCLI                                     │
│ Rich rendering · REPL · command dispatch · timers           │
└───────────────┬───────────────────────┬──────────────────────┘
                │                       │
                ▼                       ▼
┌─────────────────────────┐   ┌────────────────────────────────┐
│ services/station_service│   │ utils/                          │
│ fetch/cache/preload     │   │ storage · paths · logger        │
│ liveness/refresh        │   └────────────────────────────────┘
└────────────┬────────────┘
             ▼
┌──────────────────────────────────────────────────────────────┐
│ core/api.py                                                  │
│ Radio Browser mirrors · retries · station mapping · URL gate │
└────────────┬─────────────────────────────────────────────────┘
             │
             ▼
      Radio Browser API

┌──────────────────────────────────────────────────────────────┐
│ core/player.py                                               │
│ RadioPlayer · VLC events · health monitor · reconnect       │
│ volume/mute · metadata · EQ · recording                     │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
                         python-vlc / libVLC
                               │
                               ▼
                        Internet radio stream
```

## Entry points

There are three practical entry paths:

1. `Start-Radio.ps1` — Windows-friendly launcher that checks Python/VLC, installs the editable package when needed, sets UTF-8 console encodings, and invokes the module.
2. `python -m radio_ps` — direct Python module entry point.
3. `radio` — console script declared in `pyproject.toml` and mapped to `radio_ps.main:main`.

`radio_ps.main` parses `--category`, `--check`, and `--version`, then constructs `RadioCLI`.

## Station discovery flow

1. `RadioCLI` asks `station_service.fetch_category()` for the selected category.
2. The service loads the persisted station cache lazily.
3. A fresh cache entry is returned when it is younger than the configured TTL.
4. Otherwise the service expands a category into its configured search queries.
5. `core.api.fetch_stations()` calls Radio Browser mirrors through a shared `requests.Session`.
6. `_map_station()` rejects records without a safe stream URL and normalizes the station fields.
7. The service de-duplicates stations by URL.
8. Optional liveness checks run concurrently with a bounded thread pool.
9. Non-empty results replace the cache and are persisted atomically.
10. Empty refreshes preserve an existing cache instead of destroying usable data.

## Network behavior

`core/api.py` keeps three Radio Browser API hosts and retries selected HTTP failures (`429`, `500`, `502`, `503`, `504`) with urllib3 backoff. Each host attempt has a connect/read timeout. TLS certificate verification remains enabled.

Station stream URLs are passed through `is_safe_url()` before playback. The current allowlist is `http`, `https`, `rtsp`, `rtp`, `mms`, and `rtmp`.

## Playback lifecycle

`RadioPlayer` owns one libVLC instance and one primary media player.

### Start

- Validate the stream URL.
- Stop the previous media intentionally so old VLC callbacks cannot trigger recovery.
- Create media and apply network/live caching options plus HTTP reconnect.
- Start playback.
- Restore the current volume and equalizer.

### Runtime

VLC callbacks observe `Playing`, `Buffering`, `EncounteredError`, and `EndReached`. A daemon health thread also samples player state at a fixed interval. Both event-driven and periodic detection can trigger recovery, but a lock prevents overlapping reconnect workers.

### Recovery

Recovery is bounded by `MAX_RECONNECT` and uses `[2, 4, 8, 16, 30]` second delays. A successful `Playing` event resets the reconnect counter. When the limit is exhausted, the player stops and invokes the permanent-failure callback supplied by the UI.

### Shutdown

The UI stops its refresh timer, saves session state, stops the player, and releases VLC resources. Background health monitoring is signalled through an event.

## Persistence model

The application data directory is resolved by `utils.paths.get_app_data_dir()`:

- `RADIO_PS_DATA_DIR` when explicitly set.
- Otherwise `%APPDATA%\PowerShellRadioPro`.

`storage.py` persists favorites, recent stations (maximum 20), and session state. Writes use a temporary file followed by `os.replace()`.

The station service separately persists `cache\stations.json`. Artwork uses `cache\logos\`, keyed by a SHA-1 digest of the favicon URL. The logger writes a rotating `radio_log.txt` file with a 2 MB limit and three backups.

## Concurrency

The application deliberately uses daemon threads for work that must not block the REPL:

- VLC health monitor
- reconnect worker
- background category preload
- periodic refresh
- sleep timer

Station liveness checks use `ThreadPoolExecutor` with at most `MAX_WORKERS` concurrent checks. Cache and preload state have explicit locks. The player uses a re-entrant VLC lock plus a separate reconnect lock.

## Equalizer

`core/equalizer.py` is a state model independent of VLC. It maintains ten band gains, named presets, custom gains, and a change callback. `RadioPlayer._apply_eq()` translates those values into `vlc.AudioEqualizer` amplitudes and keeps the VLC object alive to avoid garbage collection while libVLC references it.

## Artwork pipeline

`ui/art.py` performs:

1. URL-based disk-cache lookup.
2. Bounded image download requiring an `image/*` content type.
3. Square letterboxing and RGB normalization.
4. Resize to the renderer grid.
5. Contrast/color/sharpening processing and Floyd–Steinberg dithering.
6. Rendering as sextant or half-block Rich text, or as a Sixel escape sequence when requested.
7. Monogram fallback if download, Pillow decoding, or rendering fails.

`ui/sixel.py` is a pure-Python encoder; no external Sixel command is spawned.

## Recording

Recording uses a second VLC media player/instance. The stream is sent through a `sout` chain that transcodes audio to MP3 before writing the output file. This is important because a raw stream can use OGG, Opus, FLAC, or another codec while the requested output extension is `.mp3`.

The CLI sanitizes user-provided recording names before constructing the output path.

## Design authority

The repository contains historical design records under `docs/superpowers/specs/`. One artwork design record describes a 72×72 sextant target, while the current renderer constants are 24 columns × 16 rows (48×48 effective pixels). The implementation and tests are authoritative for the current behavior; historical design records should not be read as a guarantee of the current renderer dimensions.
