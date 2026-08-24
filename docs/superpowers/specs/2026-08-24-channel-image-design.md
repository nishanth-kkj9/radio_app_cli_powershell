# Channel Image Upgrade — Design

Date: 2026-08-24
Status: Approved (user, 2026-08-24)

## Problem

Station artwork in the Now Playing panel renders at low fidelity: 24×12
half-block cells (~24×48 effective pixels), fixed-threshold enhancement,
banding on gradient logos, and a plain fallback badge when a station has no
logo.

## Goals

1. Higher resolution artwork in the same panel footprint class.
2. Visibly better reproduction of real station logos (less mud, less banding).
3. Prettier fallback when no logo exists.
4. No new dependencies; UI must never crash or stall on artwork (unchanged rule).

## Non-Goals

- Kitty/sixel/iTerm graphics protocols (poor PowerShell support).
- Changes to logo download/caching logic (`fetch_logo`, disk cache stay as-is).
- Station table thumbnails (panel-only change).

## Design

### 1. Sextant rendering

Replace half-block `▀` output with Unicode sextant blocks U+1FB00–1FB3B
("Symbols for Legacy Computing", rendered by Windows Terminal). Each character
cell encodes a 2×3 pixel sub-grid.

- Art size: `_ART_COLS=36`, `_ART_ROWS=24`. Cell is 2px wide × 3px tall, so
  this yields a square 72×72 effective pixel grid (3× the pixel count of the
  current 24×24 half-block render). Squareness matters because the pipeline
  letterboxes logos onto a square canvas; a non-square target would distort.
- Cell matching: for each 2×3 cell compute mean color of lit vs unlit pixels;
  choose the sextant glyph minimizing error between predicted and actual cell.
  fg style = lit-pixel mean, bg style = unlit-pixel mean (truecolor).
- Terminal compatibility: default `sextant`; `RADIO_PS_ART=half` env var falls
  back to the current half-block renderer for legacy conhost. Unknown values
  fall back to `half`.

### 2. Floyd–Steinberg dithering

Apply FS error diffusion on the supersampled RGB image before cell matching so
gradients quantize with spread error instead of hard banding. Pure-Python loop
over the final-resolution grid (small: ≤ 72×72) — no performance concern.

### 3. Image processing upgrades (`_prep_image`)

- Replace fixed luminance thresholds with percentile-based contrast stretch
  (2nd–98th percentile mapped to full range), keeping the dark-logo lift and
  bright-logo tame behavior as outcomes of the stretch.
- Add mild unsharp mask after downscale for crisp edges.
- Keep: alpha compositing onto letterbox bg, square letterboxing, LANCZOS
  resampling, baked frame border, saturation boost.

### 4. Monogram fallback

Two-tone badge via Rich Text only:
- Outer ring in darker shade of the deterministic palette color, inner fill in
  the palette color, bold white double-initial centered.
- Same deterministic color selection (hash of name). Slightly larger than
  current to balance the bigger art block.

### 5. Panel fit

`ui/cli_ui.py` Now Playing panel: width cap 72 → 84 (still clamped to console
width) so 36-col art + text grid fits without squeezing text. Art grows from
12 to 24 text rows — taller panel, acceptable in a full-height terminal.

## Files Changed

| File | Change |
|---|---|
| `src/radio_ps/ui/art.py` | Sextant renderer, FS dithering, percentile stretch, unsharp, monogram redesign |
| `src/radio_ps/ui/cli_ui.py` | Panel width cap 72→84 |
| `tests/test_unit.py` | Cell-matcher correctness, monogram determinism, env override parsing |
| `scripts/selfcheck.py` | Update art checks for new renderer |

## Error Handling

Unchanged fail-soft contract: any Pillow/render failure → monogram; fetch
failure → monogram; oversized/binary-junk payload → monogram.

## Testing

- Unit: sextant glyph table completeness (64 patterns bijective), cell matcher
  picks expected glyph for solid-color cells, dither preserves dimensions,
  monogram stable across runs, env override respected.
- Selfcheck: existing art checks updated, all must pass.
- Manual: run app against a real category, eyeball panel.
