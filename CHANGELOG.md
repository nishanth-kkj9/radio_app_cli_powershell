# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- `pause` command (alias `pp`) to pause/resume the live stream.
- Category caches now persist to `%APPDATA%\PowerShellRadioPro\cache\stations.json`
  and survive app restarts (atomic write, fail-soft).
- Refresh timer backs off exponentially after repeated empty refreshes,
  capped at 1 hour.

### Fixed
- `record` now transcodes to MP3 while capturing, so recordings are valid
  `.mp3` files for every stream codec — raw passthrough previously produced
  broken files from OGG/Opus/FLAC sources.
- Station badge colors are now stable across app restarts — CRC-32 of the
  station name replaces the per-process-salted built-in `hash()`.
- Replaced deprecated Pillow `Image.getdata()` usage in `_prep_image`
  (scheduled for removal in Pillow 14).

### Changed
- CI now lints with ruff (`ruff>=0.6` added to dev dependencies).
- App version now has a single source of truth (`radio_ps.__version__`),
  wired into `pyproject.toml`, the CLI `--version` flag, and the UI header.
- Deduplicated station-record mapping in `core/api.py` into one
  `_map_station()` helper used by both fetchers.

## [2.0] - 2024-06-16

### Changed
- Converted to src/ package layout with pyproject.toml
- Updated all imports to use package prefix (radio_ps.X)

## [1.0] - 2024-04-10

### Added
- Initial release with radio browser API integration
- VLC-based audio playback
- Rich terminal UI
- 10-band equalizer
- Station favorites and recent history