# AGENTS.md

## What this is

Windows-only internet radio CLI (`radio_ps`, Python 3.9+). Playback via **python-vlc** bindings — no subprocess hacks, that was the abandoned v1 design. Runs in PowerShell with UTF-8/sextant art.

## Commands

```powershell
pip install -e .[dev]          # setup
ruff check src tests scripts   # lint (CI gate 1)
pytest                         # unit + CLI tests (CI gate 2)
python scripts/selfcheck.py    # headless full-feature check
```

Run a single test: `pytest tests/test_cli.py -k name`. CI (windows-latest) also verifies `from radio_ps.main import main` imports cleanly.

## Testing quirks

- Tests run **without VLC installed**: `tests/conftest.py` injects a fake `vlc` module into `sys.modules` before any import. Only the surface `core/player.py` uses is faked — if you add libvlc API calls to player code, extend `_FakeMediaPlayer`/`_FakeInstance` or tests fail.
- `data_dir` fixture sets `RADIO_PS_DATA_DIR` to a tmp dir; `cli` fixture gives a wired `RadioCLI` with network calls stubbed out. Use them rather than hitting Radio Browser live.

## Conventions

- **Ruff, not Black** (CONTRIBUTING.md's "use Black" is stale). Line length 100. E701/E702 ignored deliberately — table-driven one-liners are an accepted style here; don't churn them into multiline.
- src layout: package lives in `src/radio_ps/`. Entry points: `python -m radio_ps [-c category] [--check]` and console script `radio`.
- Version is **dynamic**, read from `radio_ps.__version__` — bump it there, never in `pyproject.toml`.

## Gotchas

- VLC must match Python bitness (64-bit both); missing libvlc fails at runtime, not import — hence CI's explicit import check plus `selfcheck.py`.
- User data lives in `%APPDATA%\PowerShellRadioPro\` (favorites/recent/session JSON, recordings, logo cache, rotating log). Never write repo-local state files.
- Env vars: `RADIO_PS_DATA_DIR` (data dir override), `RADIO_PS_ART` (`sextant` | `sixel` | `half` renderer mode).
- Terminal output must be UTF-8 safe (launcher sets `[Console]::OutputEncoding`; legacy conhost needs `RADIO_PS_ART=half`). Avoid non-Windows-terminal assumptions in UI code.
