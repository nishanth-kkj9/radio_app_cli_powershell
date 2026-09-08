# Changelog

All notable user-facing changes are documented here. Implementation-only commits do not need an entry.

## [Unreleased]

### Documentation

- Rebuilt `README.md` from the current implementation and test suite.
- Added dedicated architecture, command, configuration, development, and troubleshooting guides.
- Updated contributor guidance to match the actual Ruff-based toolchain and fake-VLC test strategy.
- Added security, support, and code-of-conduct documentation.
- Clarified that the artwork design record under `docs/superpowers/` is historical and that current source/tests are authoritative.

### Repository maintenance

- Standardized issue/PR documentation around the repository's actual Windows/Python workflow.

## [2.0]

### Changed

- Converted to `src/` package layout with `pyproject.toml`.
- Updated imports to use the `radio_ps` package prefix.

## [1.0]

### Added

- Initial Radio Browser integration.
- VLC-based audio playback.
- Rich terminal UI.
- 10-band equalizer.
- Station favorites and recent history.
