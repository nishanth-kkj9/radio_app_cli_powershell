# Contributing to PowerShell Radio Pro

Thank you for contributing. The project is Windows-focused, so changes should preserve a good PowerShell/Windows Terminal experience while keeping the core code testable without a native VLC installation.

## Before you start

Read:

- [`README.md`](README.md) for user-facing behavior.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for module boundaries and runtime flow.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for local setup and validation.
- [`SECURITY.md`](SECURITY.md) before changing URL handling, downloads, recording paths, or process/environment behavior.

## Development setup

```powershell
git clone https://github.com/nishanth-kkj9/radio_app_cli_powershell.git
cd radio_app_cli_powershell
python -m pip install -e .[dev]
```

## Coding standards

- Use **Ruff**, not Black.
- Keep the configured line length at 100 characters.
- Preserve the existing `src/radio_ps` package boundaries.
- Add type hints where they improve clarity.
- Prefer small, focused functions and fail-soft behavior for optional artwork/network operations.
- Do not write runtime state into the repository.
- Do not add dependencies when the standard library or existing dependency set is sufficient.
- Treat station URLs, artwork URLs, filenames, and API data as untrusted input.

The project intentionally ignores Ruff E701/E702. Do not perform broad formatting churn solely to remove those established one-line constructs.

## Tests

Run:

```powershell
ruff check src tests scripts
pytest
python scripts/selfcheck.py
```

Tests use a fake VLC module and an isolated `RADIO_PS_DATA_DIR`, so tests should not depend on a developer's real VLC installation, personal data, or live Radio Browser responses.

For changes to the native VLC surface, update the fake VLC implementation in `tests/conftest.py` as necessary and add a regression test.

## Making changes

1. Create a focused branch from `main`.
2. Make the smallest coherent implementation change.
3. Add or update tests for behavior that changed.
4. Run Ruff and pytest.
5. Run `scripts/selfcheck.py` for cross-module or runtime changes.
6. Manually verify Windows/VLC behavior when the change affects playback, recording, artwork, launcher behavior, or terminal rendering.
7. Update documentation when user-visible behavior changes.
8. Update `CHANGELOG.md` for notable user-visible changes.

## Pull requests

A useful pull request should include:

- **Problem:** what was wrong or what capability is being added.
- **Implementation:** what changed and which modules are involved.
- **Validation:** exact checks/tests run.
- **Manual verification:** Windows/VLC/terminal details when relevant.
- **Documentation:** links to updated docs when behavior changed.

Keep unrelated refactors out of feature or bug-fix pull requests.

## Security-sensitive changes

Do not commit secrets, credentials, private station URLs, or personal runtime data. Changes involving URL validation, downloads, path construction, subprocess/environment behavior, or dependency upgrades should receive extra review and include regression coverage.

See [`SECURITY.md`](SECURITY.md) for reporting vulnerabilities.
