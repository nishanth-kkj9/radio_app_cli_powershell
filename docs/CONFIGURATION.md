# Configuration reference

Most runtime tuning lives in `src/radio_ps/core/config.py`. User-facing configuration is intentionally small.

## Environment variables

### `RADIO_PS_DATA_DIR`

Overrides the default persistent data directory.

Default:

```text
%APPDATA%\PowerShellRadioPro
```

Example:

```powershell
$env:RADIO_PS_DATA_DIR = "D:\RadioData"
radio
```

Use this for portable setups, testing, or keeping recordings/cache away from the system profile.

### `RADIO_PS_ART`

Selects artwork rendering mode.

| Value | Behavior |
|---|---|
| `sextant` | Unicode sextant renderer; high-density terminal art |
| `sixel` | Sixel bitmap renderer when supported |
| `half` | Half-block compatibility renderer |
| anything else | Falls back to compatibility behavior |

Windows Terminal is recommended for the Unicode/truecolor experience. The launcher explicitly configures UTF-8 input and output.

## Network settings

Current source defaults:

| Setting | Value | Purpose |
|---|---:|---|
| `API_TIMEOUT` | 8 s | Per Radio Browser host request timeout |
| `ALIVE_TIMEOUT` | `(8, 5)` | Connect/read timeout for station liveness checks |
| `MAX_RESULTS` | 30 | Maximum stations requested per query |
| `MAX_WORKERS` | 10 | Concurrent station liveness/preload workers |
| `CACHE_TTL` | 600 s | In-memory category cache freshness |
| `REFRESH_INTERVAL` | 600 s | Normal periodic refresh interval |

The service backs off after repeated refreshes with zero total live stations, up to one hour.

## Stream URL policy

The player does not accept arbitrary URL schemes. `ALLOWED_STREAM_SCHEMES` currently contains:

```text
http https rtsp rtp mms rtmp
```

This allowlist is applied before playback. Changing it is a security-sensitive source change and should be accompanied by tests and a clear rationale.

## VLC options

The application creates libVLC with:

```text
--no-video
--quiet
--network-caching=3000
--live-caching=3000
--file-caching=3000
--http-reconnect
--sout-mux-caching=3000
```

Per-media playback additionally applies network caching and HTTP reconnect options. These values are implementation settings, not command-line user preferences.

## Categories

The configured remote categories and query expansions are maintained in `config.py`:

```text
top       → top hits, india
hindi     → hindi, bollywood
kannada   → kannada, karnataka
pop       → pop, pop hits
rock      → rock, classic rock
jazz      → jazz, smooth jazz
classical → classical, orchestra
news      → news, bbc news
```

Favorites and recent are local views and do not require API queries.

## Data layout

```text
%APPDATA%\PowerShellRadioPro\
├── favorites.json
├── recent.json
├── session.json
├── radio_log.txt
├── recordings\
└── cache\
    ├── stations.json
    └── logos\
```

The logger rotates `radio_log.txt` at 2 MB and keeps three backups. Recent stations are capped at 20.

## Configuration precedence

1. Explicit environment variables.
2. Windows `%APPDATA%` when `RADIO_PS_DATA_DIR` is not set.
3. Source-level constants in `core/config.py` for network, cache, category, and VLC behavior.

There is currently no separate user configuration file. Avoid inventing one in documentation unless the implementation is added first.
