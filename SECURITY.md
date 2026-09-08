# Security policy

## Scope

PowerShell Radio Pro is a desktop internet-radio client. It consumes third-party station metadata, opens third-party stream URLs through VLC, downloads station artwork, and writes recordings and application state to the local filesystem.

The project applies several defensive controls, including stream URL scheme validation, HTTPS verification for API requests, bounded network timeouts, retry limits, artwork size/content-type checks, filename sanitization for recordings, and isolated application data paths.

These controls reduce common failure and injection risks, but they do not turn the application into a security sandbox. VLC, Python, Windows, and third-party station endpoints remain part of the trust boundary.

## Reporting a vulnerability

Please do **not** disclose an unpatched security vulnerability in a public issue.

Use GitHub's private vulnerability reporting / Security Advisories for this repository when that feature is available. If private reporting is not enabled, contact the repository maintainer through a private GitHub channel and provide:

- affected version or commit,
- affected file/function,
- reproduction steps or proof of concept,
- security impact,
- any suggested mitigation.

Allow reasonable time for investigation and remediation before public disclosure.

## Security-sensitive areas

Changes to these areas deserve additional review:

- `core/api.py` URL validation and remote API handling
- `core/player.py` stream opening and VLC options
- `ui/art.py` and `ui/sixel.py` remote image handling
- `utils/storage.py` and recording path construction
- `Start-Radio.ps1` environment, package installation, and command execution
- dependency changes in `pyproject.toml`

## Dependency and repository hygiene

Keep Python and VLC installations current. Never commit API keys, tokens, passwords, private stream URLs, local application data, recordings, or generated caches.

The repository's `.gitignore` is intended to catch common Python, test, editor, and runtime artifacts, but contributors must still review staged files before committing.
