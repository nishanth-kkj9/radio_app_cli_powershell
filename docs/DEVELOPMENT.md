# Development guide

## Prerequisites

- Windows
- Python 3.9 or newer
- Git
- VLC for manual playback work
- A PowerShell environment; Windows Terminal is recommended

The automated test suite supplies a fake VLC module, so you do not need VLC merely to run the unit/CLI tests.

## Setup

```powershell
git clone https://github.com/nishanth-kkj9/radio_app_cli_powershell.git
cd radio_app_cli_powershell
python -m pip install -e .[dev]
```

Run the application directly:

```powershell
python -m radio_ps
```

Or use the launcher:

```powershell
.\Start-Radio.ps1
```

## Quality gates

### Ruff

The repository uses Ruff rather than Black. The configured line length is 100 characters; E701/E702 are intentionally ignored.

```powershell
ruff check src tests scripts
```

Do not introduce a large formatting-only change to convert the existing compact table-driven style.

### Pytest

```powershell
pytest
```

The test configuration discovers `tests/test_*.py` and runs with verbose output and short tracebacks.

The fixtures install a fake `vlc` module before application imports and isolate persistent data through `RADIO_PS_DATA_DIR`. CLI network operations are stubbed so tests remain deterministic.

The suite covers, among other areas:

- EQ presets and clamping
- URL and favicon sanitization
- JSON persistence and migration behavior
- station-cache preservation
- artwork renderers and deterministic badges
- Sixel encoding
- player state, volume, mute, and recording
- CLI command dispatch and regression cases

### Headless self-check

```powershell
python scripts/selfcheck.py
```

The self-check exercises a broader cross-section of the application using fake VLC, temporary application data, and stubbed station/network data. It is useful after changes that cross module boundaries.

## CI

GitHub Actions runs on `windows-latest` with Python 3.11. The workflow:

1. checks out the repository,
2. installs the package with development dependencies,
3. runs Ruff,
4. runs pytest,
5. verifies `radio_ps.main` imports successfully.

The workflow does not install a desktop VLC application; tests therefore must remain compatible with the fake VLC fixture unless a future CI job explicitly adds VLC.

## Recommended change workflow

```text
issue / idea
    ↓
small focused branch
    ↓
implementation + tests
    ↓
ruff check
    ↓
pytest
    ↓
selfcheck when relevant
    ↓
manual Windows/VLC verification when relevant
    ↓
pull request
```

For player, recording, terminal-art, or launcher changes, include the manual environment used for verification in the pull request description.

## Source layout

Use the existing package boundaries:

- `core/` — playback, API policy, EQ, configuration
- `services/` — station fetching, liveness, caching, preload, refresh
- `ui/` — Rich terminal UI and artwork
- `utils/` — persistence, paths, logging
- `tests/` — deterministic tests and fixtures
- `scripts/` — headless/manual verification helpers

Avoid placing application runtime data inside the repository. The runtime data directory is controlled by `RADIO_PS_DATA_DIR` or `%APPDATA%\PowerShellRadioPro`.

## Versioning

The version is defined once in `src/radio_ps/__init__.py` as `radio_ps.__version__`. `pyproject.toml` reads it dynamically. Update that value rather than adding a second version constant.

## Commit and pull request guidance

Keep commits focused and descriptive. A good change should explain what changed and why without embedding generated files or local runtime state.

Pull requests should include:

- a concise problem statement,
- implementation summary,
- tests/checks run,
- manual verification details for Windows/VLC-specific behavior,
- screenshots or terminal output when the Rich UI changes.
