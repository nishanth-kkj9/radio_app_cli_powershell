"""ui/art.py - station artwork as terminal pixel art.

Fetches the station favicon (already sanitized by core.api) and renders it
as Unicode block art with truecolor ANSI styles via Rich Text.

Renderer: sextant blocks (U+1FB00 block, 2x3 sub-pixels per character cell)
by default, giving a 72x72 effective pixel grid. Set RADIO_PS_ART=half to
fall back to half-block rendering (older terminals without Unicode 13
glyphs). Falls back to a colored monogram badge when there is no logo, no
Pillow, or the download fails - the UI must never crash or stall on artwork.
"""

from __future__ import annotations

import hashlib
import io
import os
import zlib

import requests
from rich.text import Text

from radio_ps.utils.logger import log
from radio_ps.utils.paths import get_app_data_dir

_LOGO_DIR = os.path.join(get_app_data_dir(), "cache", "logos")
_MAX_LOGO_BYTES = 512 * 1024
_TIMEOUT = 4
_ART_COLS = 24          # character columns (sextant mode)
_ART_ROWS = 16          # text rows; cols*2 == rows*3 keeps output square
_PX_W = _ART_COLS * 2   # effective pixel grid: 48x48
_PX_H = _ART_ROWS * 3
_BG = (26, 26, 34)      # letterbox background (slightly lighter than terminal)
_FRAME = (86, 86, 100)  # subtle frame color baked around the art
_PALETTE = ["cyan", "magenta", "blue", "green", "yellow", "red"]
_PALETTE_DARK = {
    "cyan": "dark_cyan",
    "magenta": "dark_magenta",
    "blue": "dark_blue",
    "green": "dark_green",
    "yellow": "dark_yellow",
    "red": "dark_red",
}


def _cache_path(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_LOGO_DIR, digest + ".img")


def _load_cached(url: str) -> bytes | None:
    path = _cache_path(url)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None
    return None


def _save_cache(url: str, data: bytes) -> None:
    try:
        os.makedirs(_LOGO_DIR, exist_ok=True)
        tmp = _cache_path(url) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, _cache_path(url))
    except OSError:
        pass


def fetch_logo(url: str) -> bytes | None:
    """Download (with disk cache) a station logo image. Fail-soft."""
    if not url:
        return None
    cached = _load_cached(url)
    if cached:
        return cached
    try:
        r = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={"User-Agent": "PowerShellRadioPro/2.0"},
            stream=True,
        )
        ctype = r.headers.get("Content-Type", "")
        if not (200 <= r.status_code < 300 and ctype.startswith("image/")):
            return None
        data = next(r.iter_content(chunk_size=_MAX_LOGO_BYTES + 1), b"")
        r.close()
        if not data or len(data) > _MAX_LOGO_BYTES:
            return None
        _save_cache(url, data)
        return data
    except Exception as e:
        log(f"Logo fetch failed ({url}): {e}", "debug")
        return None


def _badge_color(name: str) -> str:
    """Pick a palette color deterministically from the station name.

    Uses CRC-32 because Python's built-in str hash() is salted per process
    (PYTHONHASHSEED) — hash()-based colors would change on every app restart.
    """
    return _PALETTE[zlib.crc32((name or "").encode("utf-8")) % len(_PALETTE)]


def _monogram(name: str) -> Text:
    """Two-tone album-card badge at the same footprint as the pixel art
    (_ART_COLS x _ART_ROWS), so stations without a logo sit at the same size
    and vertical alignment as stations with artwork.
    """
    words = [w for w in (name or "").split() if w]
    initials = "".join(w[0] for w in words[:2]).upper() or "?"
    if len(initials) > 5:
        initials = initials[:5]
    color = _badge_color(name)
    dark = _PALETTE_DARK[color]

    inner_w = _ART_COLS - 2        # fill area between the two border columns
    body_rows = _ART_ROWS - 2      # fill rows between the top/bottom ring

    def center(s: str) -> str:
        s = s[:inner_w]
        pad = inner_w - len(s)
        left = pad // 2
        return " " * left + s + " " * (pad - left)

    RING = f"bold white on {dark}"
    BODY = f"on {color}"
    LIGHT = f"bold white on {color}"

    t = Text()
    # Top ring
    t.append("╭", style=RING)
    t.append("─" * inner_w, style=RING)
    t.append("╮", style=RING)
    t.append("\n")

    # Special rows: initials centered, decorated with music notes above/below.
    mid = body_rows // 2
    designs = {
        mid: initials,
        max(0, mid - 3): "♪  ♪  ♪",
        min(body_rows - 1, mid + 3): "♪  ♪  ♪",
    }

    for i in range(body_rows):
        t.append("│", style=RING)
        if i in designs:
            t.append(center(designs[i]), style=LIGHT)
        else:
            t.append(" " * inner_w, style=BODY)
        t.append("│", style=RING)
        t.append("\n")

    # Bottom ring
    t.append("╰", style=RING)
    t.append("─" * inner_w, style=RING)
    t.append("╯", style=RING)
    return t


_SIXEL_SIZE = 140       # pixel size for sixel (true bitmap) mode


def _base_prep(img):
    """Alpha-composite onto the letterbox color and letterbox to a square."""
    from PIL import Image

    if img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    ):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, _BG + (255,))
        bg.paste(img, mask=img.split()[3])
        img = bg
    img = img.convert("RGB")

    side = max(img.size)
    canvas = Image.new("RGB", (side, side), _BG)
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def _prep_image(img):
    """Normalize any logo image to an enhanced RGB square ready for rendering."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageOps

    canvas = _base_prep(img)

    # Downscale to the exact output grid with a high-quality filter.
    canvas = canvas.resize((_PX_W, _PX_H), Image.LANCZOS)

    # Percentile-based contrast stretch: maps the 2nd-98th luminance range to
    # full black-white, which fixes both washed-out and crushed logos without
    # fixed thresholds.
    canvas = ImageOps.autocontrast(canvas, cutoff=(2, 2))

    # Keep the dark-logo lift / near-white tame behavior on top of the stretch.
    # (getdata() is deprecated since Pillow 10 — read raw RGB bytes instead.)
    raw = canvas.tobytes()
    n = max(1, len(raw) // 3)
    lum = sum(
        0.299 * raw[i] + 0.587 * raw[i + 1] + 0.114 * raw[i + 2]
        for i in range(0, len(raw), 3)
    ) / n
    if lum < 60:
        canvas = ImageEnhance.Brightness(canvas).enhance(1.45)
        canvas = ImageEnhance.Contrast(canvas).enhance(1.15)
    elif lum > 200:
        canvas = ImageEnhance.Brightness(canvas).enhance(0.88)
    canvas = ImageEnhance.Color(canvas).enhance(1.18)

    # Mild sharpening so logo edges survive the downscale.
    from PIL import ImageFilter

    canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1, percent=60, threshold=2))

    # Floyd-Steinberg error diffusion onto a 6x6x6 color cube. The renderer
    # averages sub-pixels back into two colors per cell, so diffused pixels
    # let those means land between cube steps instead of banding.
    _fs_dither(canvas)

    # Subtle baked-in frame (drawn, not expanded, to keep the exact grid size).
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, _PX_W - 1, _PX_H - 1], outline=_FRAME, width=1)
    return canvas


def _fs_dither(img) -> None:
    """In-place Floyd-Steinberg dithering onto a 216-color cube (step 51)."""
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            old = px[x, y]
            new = tuple(min(255, max(0, round(c / 51) * 51)) for c in old)
            px[x, y] = new
            er, eg, eb = (old[0] - new[0], old[1] - new[1], old[2] - new[2])
            for dx, dy, weight in (
                (1, 0, 7 / 16),
                (-1, 1, 3 / 16),
                (0, 1, 5 / 16),
                (1, 1, 1 / 16),
            ):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and ny < h:
                    o = px[nx, ny]
                    px[nx, ny] = (
                        max(0, min(255, int(o[0] + er * weight))),
                        max(0, min(255, int(o[1] + eg * weight))),
                        max(0, min(255, int(o[2] + eb * weight))),
                    )


# ── Sextant tables ────────────────────────────────────────────────────────────
#
# A sextant character fills a 2x3 sub-grid. Unicode enumerates 60 of the 64
# six-bit patterns in U+1FB00-U+1FB3B; four live elsewhere:
#   000000 -> space, 111111 -> U+2588 FULL, 010101 -> U+258C LEFT HALF,
#   101010 -> U+2590 RIGHT HALF.
# Mask bit i (0-5) = sub-position i+1, numbered UL, UR, ML, MR, LL, LR
# (per the Unicode BLOCK SEXTANT-N names).

_SEX_FULL = 0b111111
_SEX_LEFT = 0b010101
_SEX_RIGHT = 0b101010

_SEX_CHAR: dict[int, str] = {
    0b000000: " ",
    _SEX_FULL: "█",
    _SEX_LEFT: "▌",
    _SEX_RIGHT: "▐",
}
for _i, _m in enumerate(
    m for m in range(1, 63) if m not in (_SEX_LEFT, _SEX_RIGHT)
):
    _SEX_CHAR[_m] = chr(0x1FB00 + _i)

# Per-mask lit flags ordered (row, col) for sub-pixel sampling.
_SEX_BITS: dict[int, list[bool]] = {
    m: [(m >> (row * 2 + col)) & 1 == 1 for row in range(3) for col in range(2)]
    for m in range(64)
}


def _hex(c: tuple[int, int, int]) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def _render_sextant(canvas) -> Text:
    """Render an RGB canvas as sextant block art with per-cell fg/bg colors."""
    px = canvas.load()
    w, h = canvas.size
    art = Text()
    for cy in range(h // 3):
        if cy:
            art.append("\n")
        for cx in range(w // 2):
            # Sample the 6 sub-pixels once.
            samples = [
                px[cx * 2 + col, cy * 3 + row] for row in range(3) for col in range(2)
            ]
            total = [0.0, 0.0, 0.0]
            sq = 0.0
            for s in samples:
                total[0] += s[0]; total[1] += s[1]; total[2] += s[2]
                sq += s[0] ** 2 + s[1] ** 2 + s[2] ** 2

            best_mask, best_err, best_nlit = 0, float("inf"), -1
            best_fg = best_bg = samples[0]
            for mask in range(64):
                bits = _SEX_BITS[mask]
                n_lit = sum(bits)
                n_unlit = 6 - n_lit
                if n_lit == 0 or n_unlit == 0:
                    mean = (
                        int(total[0] / 6), int(total[1] / 6), int(total[2] / 6)
                    )
                    fg = bg = mean
                    err = sq - 6 * (
                        mean[0] ** 2 + mean[1] ** 2 + mean[2] ** 2
                    )
                else:
                    lit = [0.0, 0.0, 0.0]
                    for s, on in zip(samples, bits):
                        if on:
                            lit[0] += s[0]; lit[1] += s[1]; lit[2] += s[2]
                    fg = (int(lit[0] / n_lit), int(lit[1] / n_lit), int(lit[2] / n_lit))
                    bg = (
                        int((total[0] - lit[0]) / n_unlit),
                        int((total[1] - lit[1]) / n_unlit),
                        int((total[2] - lit[2]) / n_unlit),
                    )
                    # SSE = sum|p|^2 - n_lit*|fg|^2 - n_unlit*|bg|^2
                    err = sq - n_lit * (fg[0] ** 2 + fg[1] ** 2 + fg[2] ** 2) \
                        - n_unlit * (bg[0] ** 2 + bg[1] ** 2 + bg[2] ** 2)
                # Prefer denser glyphs on error ties (solid areas render solid).
                if err < best_err - 1e-9 or (
                    abs(err - best_err) <= 1e-9 and n_lit > best_nlit
                ):
                    best_err, best_mask, best_fg, best_bg = err, mask, fg, bg
                    best_nlit = n_lit

            art.append(
                _SEX_CHAR[best_mask],
                style=f"{_hex(best_fg)} on {_hex(best_bg)}",
            )
    return art


def _render_half(canvas) -> Text:
    """Legacy half-block renderer (RADIO_PS_ART=half) for older terminals."""
    px = canvas.load()
    w, h = canvas.size
    art = Text()
    for y in range(0, h - 1, 2):
        for x in range(w):
            top, bottom = px[x, y], px[x, y + 1]
            art.append("▀", style=f"{_hex(top)} on {_hex(bottom)}")
        if y + 2 < h:
            art.append("\n")
    return art


def render_logo(logo_url: str, name: str):
    """Return a Rich Text renderable: pixel art if possible, else monogram."""
    data = fetch_logo(logo_url) if logo_url else None
    if not data:
        return _monogram(name)
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        canvas = _prep_image(img)
        if art_mode() == "half":
            # Half blocks carry 1x2 pixels per char: shrink to the same
            # character footprint as sextant mode (cols x rows).
            from PIL import Image as _Image

            canvas = canvas.resize((_ART_COLS, _ART_ROWS * 2), _Image.LANCZOS)
            return _render_half(canvas)
        return _render_sextant(canvas)
    except Exception as e:
        log(f"Artwork render failed: {e}", "debug")
        return _monogram(name)


def render_sixel(logo_url: str) -> str | None:
    """Return a sixel escape sequence for the logo, or None on any failure."""
    data = fetch_logo(logo_url) if logo_url else None
    if not data:
        return None
    try:
        from PIL import Image, ImageOps

        from radio_ps.ui import sixel

        img = Image.open(io.BytesIO(data))
        canvas = _base_prep(img).resize((_SIXEL_SIZE, _SIXEL_SIZE), Image.LANCZOS)
        canvas = ImageOps.autocontrast(canvas, cutoff=(2, 2))
        return sixel.encode(canvas)
    except Exception as e:
        log(f"Sixel render failed: {e}", "debug")
        return None


def art_mode() -> str:
    """
    Effective artwork mode. RADIO_PS_ART (sextant|half|sixel) explicitly
    overrides the default. Otherwise:

      • Windows Terminal (WT_SESSION set) → 'sextant'
        U+1FB00 block glyphs are well supported there; sixel is NOT auto-used
        because WT only added true sixel rendering in 1.22+ and older builds
        silently drop the payload, leaving a blank, borderless panel.
      • every other terminal               → 'half'
        Legacy conhost fonts often lack the U+1FB00 glyphs, so fall back to
        the universal half-block renderer.

    Sixel remains available as an explicit opt-in via RADIO_PS_ART=sixel for
    terminals with confirmed sixel support.
    """
    mode = os.environ.get("RADIO_PS_ART", "").strip().lower()
    if mode in ("sextant", "half", "sixel"):
        return mode
    return "sextant" if os.environ.get("WT_SESSION") else "half"


def volume_bar(volume: int) -> Text:
    """10-segment volume gauge, green/yellow/red by level."""
    filled = max(0, min(10, round(volume / 10)))
    color = "green" if volume >= 60 else "yellow" if volume >= 25 else "red"
    t = Text()
    t.append("▮" * filled, style=f"bold {color}")
    t.append("▯" * (10 - filled), style="dim")
    t.append(f" {volume}%", style="bold")
    return t
