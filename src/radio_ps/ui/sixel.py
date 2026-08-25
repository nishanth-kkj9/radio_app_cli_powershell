"""ui/sixel.py - minimal pure-Python DECSIXEL encoder.

Encodes a PIL RGB(A) image into a sixel graphics escape sequence so terminals
with sixel support (Windows Terminal 1.22+) can show a true bitmap instead of
Unicode block art. No subprocesses, no external tools.
"""

from __future__ import annotations

_INTRO = "\x1bPq"
_OUTRO = "\x1b\\"


def encode(img) -> str:
    """Encode a PIL image as a sixel sequence with an embedded palette."""
    from PIL import Image

    img = img.convert("RGB")
    # Raster attribute: aspect 1:1 with explicit canvas size.
    header = f'{_INTRO}"1;1;{img.width};{img.height}'

    pal_img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    palette = pal_img.getpalette() or []
    n_colors = max(1, len(palette) // 3)
    parts = [header]
    for i in range(n_colors):
        r, g, b = palette[i * 3 : i * 3 + 3]
        parts.append(f"#{i};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}")

    px = pal_img.load()
    w, h = img.size
    for y0 in range(0, h, 6):
        # Per-column bitmask of which of the 6 band rows carry each color.
        columns: list[dict[int, int]] = []
        used: set[int] = set()
        for x in range(w):
            masks: dict[int, int] = {}
            for row in range(6):
                y = y0 + row
                if y >= h:
                    break
                c = px[x, y]
                masks[c] = masks.get(c, 0) | (1 << row)
            columns.append(masks)
            used.update(masks)

        for color in sorted(used):
            parts.append(f"#{color}")
            for masks in columns:
                m = masks.get(color, 0)
                # Space keeps column alignment when this color skips a column.
                parts.append(" " if m == 0 else chr(63 + m))
        # '-' advances to the next 6-row band ('$' would re-draw the SAME
        # rows, stacking every band on top of the first).
        parts.append("-" if y0 + 6 < h else "")
    parts.append(_OUTRO)
    return "".join(parts)
