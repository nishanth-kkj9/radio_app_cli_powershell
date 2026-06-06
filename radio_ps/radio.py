"""
radio.py — PowerShell Radio Pro — Entry Point
Python-based internet radio for Windows PowerShell.
Uses python-vlc (libvlc) — no WSL2, no cava, no subprocess hacks.

Usage:
  python radio.py                        # start with Top Charts
  python radio.py -c jazz                # start on Jazz category
  python radio.py -c hindi               # start on Hindi
  python radio.py --check                # verify VLC + dependencies
"""

from __future__ import annotations

import os
import sys
import argparse

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _check_dependencies() -> bool:
    """Verify all required packages and VLC are available."""
    ok = True
    print("\nDependency Check")
    print("─" * 40)

    # Check Python version
    pv = sys.version_info
    status = "✓" if pv >= (3, 9) else "✗"
    print(f"  {status} Python {pv.major}.{pv.minor}.{pv.micro}")
    if pv < (3, 9):
        print("    ↳ Requires Python 3.9+")
        ok = False

    # Check required packages
    packages = [
        ("vlc",       "python-vlc",  "VLC Python bindings"),
        ("rich",      "rich",        "Rich terminal UI"),
        ("requests",  "requests",    "HTTP client"),
        ("urllib3",   "urllib3",     "HTTP library"),
    ]
    for module, pip_name, desc in packages:
        try:
            __import__(module)
            print(f"  ✓ {pip_name:<20} {desc}")
        except ImportError:
            print(f"  ✗ {pip_name:<20} {desc}  ← MISSING")
            print(f"    ↳ pip install {pip_name}")
            ok = False

    # Check VLC installation
    print()
    try:
        import vlc
        ver = vlc.libvlc_get_version()
        if isinstance(ver, bytes):
            ver = ver.decode("utf-8")
        print(f"  ✓ VLC {ver} (libvlc loaded successfully)")
    except ImportError:
        print("  ✗ python-vlc not installed  (pip install python-vlc)")
        ok = False
    except Exception as e:
        print(f"  ✗ libvlc not found: {e}")
        print("    ↳ Install VLC from https://www.videolan.org/vlc/")
        print("    ↳ Use 64-bit VLC if running 64-bit Python")
        ok = False

    print()
    if ok:
        print("  ✓ All dependencies satisfied. Ready to run!\n")
    else:
        print("  ✗ Fix the issues above, then run again.\n")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="radio",
        description=f"PowerShell Radio Pro — Internet radio for Windows PowerShell",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Categories:
  top, hindi, kannada, pop, rock, jazz, classical, news, favorites, recent

Examples:
  python radio.py
  python radio.py -c jazz
  python radio.py --check
        """,
    )
    parser.add_argument(
        "-c", "--category",
        default=None,
        metavar="CAT",
        help="Start with a specific category (default: top)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check dependencies and VLC installation, then exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="PowerShell Radio Pro 2.0",
    )
    args = parser.parse_args()

    # Dependency check mode
    if args.check:
        sys.exit(0 if _check_dependencies() else 1)

    # Normal startup
    try:
        from ui.cli_ui import RadioCLI
    except ImportError as e:
        print(f"\nImport error: {e}")
        print("Run:  python radio.py --check  to diagnose\n")
        sys.exit(1)

    app = RadioCLI()
    app.run(start_category=args.category)


if __name__ == "__main__":
    main()
