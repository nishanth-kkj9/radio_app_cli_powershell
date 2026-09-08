# Troubleshooting

## `python-vlc` is missing

Run:

```powershell
python -m pip install -e .
```

or:

```powershell
python -m pip install python-vlc
```

Then verify:

```powershell
python -m radio_ps --check
```

## `libvlc.dll` cannot be loaded

The Python binding can be installed while the native VLC runtime is missing. Install a compatible VLC build and make sure Python and VLC use the same architecture (normally 64-bit + 64-bit).

The application checks common VLC locations under `C:\Program Files\VideoLAN\VLC`, `C:\Program Files (x86)\VideoLAN\VLC`, and the per-user VideoLAN location. It also attempts to use VLC from `PATH`.

Run the dependency diagnostic:

```powershell
.\Start-Radio.ps1 -Check
```

## PowerShell refuses to run `Start-Radio.ps1`

If the execution policy blocks local scripts:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then start the launcher again.

## Artwork shows boxes or broken glyphs

Windows Terminal is recommended. For a legacy console, use the half-block renderer:

```powershell
$env:RADIO_PS_ART = "half"
.\Start-Radio.ps1
```

For Sixel-capable terminals:

```powershell
$env:RADIO_PS_ART = "sixel"
```

The launcher sets UTF-8 input/output encodings, but terminal font and graphics-protocol support still matters.

## Station list is empty

Radio Browser is an external service, so a temporary API/network failure can occur. Try:

```text
refresh
```

and inspect:

```text
log 100
```

The station service deliberately preserves an existing non-empty cache when a refresh produces zero results. If the cache is also empty, check network connectivity and the Radio Browser service.

## A station appears but playback fails

Use:

```text
info
now
```

Then inspect the log:

```text
log 100
```

Some public radio streams can be broken, rate-limited, geo-restricted, or temporarily unavailable. The player performs bounded reconnect attempts; it cannot make an unavailable third-party stream healthy.

## Playback repeatedly reconnects

The player has both VLC event callbacks and an eight-second health monitor. Recovery is limited to five attempts with increasing delays. Repeated failures usually indicate the station endpoint rather than the UI.

Try another station. If several independent stations fail, run `--check`, verify network access, and inspect the log.

## Favorites/history/session seem lost

Check the active data directory:

```text
datadir
```

The default is `%APPDATA%\PowerShellRadioPro`. If `RADIO_PS_DATA_DIR` is set, the application uses that location instead.

The application also performs a one-time migration from its legacy in-package JSON location when applicable.

## Recordings are missing or invalid

Recordings are stored under:

```text
%APPDATA%\PowerShellRadioPro\recordings\
```

Use `datadir` to confirm the actual location.

The recorder transcodes the input stream to MP3. If recording fails, inspect `log 100` and verify that the destination is writable and that VLC can open the source stream.

## Tests fail on a machine without VLC

That should normally not be necessary. The test fixture installs a fake `vlc` module before importing the player.

Run:

```powershell
pytest
```

If a new test or feature directly requires a native VLC API, update the fake implementation in `tests/conftest.py` or clearly mark the test as requiring a real VLC environment.

## Ruff reports formatting/style issues

The project uses Ruff, not Black:

```powershell
ruff check src tests scripts
```

The configured line length is 100. E701/E702 are intentionally ignored because the repository uses compact table-driven statements in established areas.

## Need a clean diagnostic bundle

Run:

```powershell
python -m radio_ps --check
```

then:

```text
vlcinfo
datadir
log 100
preload_status
```

When opening an issue, include the output of these commands, your Python version, VLC version, Windows version, terminal application, and the exact command that reproduces the problem. Never include credentials, private URLs, or other sensitive information.
