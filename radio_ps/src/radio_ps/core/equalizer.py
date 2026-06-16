"""
core/equalizer.py — 10-band software EQ, VLC AudioEqualizer compatible.

Bands map to standard ISO centre frequencies (VLC libvlc):
  0=60Hz  1=170Hz  2=310Hz  3=600Hz  4=1kHz
  5=3kHz  6=6kHz   7=12kHz  8=14kHz  9=16kHz
Gain range: -20 to +20 dB per band.
"""

from __future__ import annotations
from radio_ps.utils.logger import log


class Equalizer:
    PRESETS: dict[str, list[tuple[int, float]]] = {
        "None":         [],
        "Bass Boost":   [(0, 15), (1, 12), (2, 10)],
        "Treble Boost": [(7, 10), (8, 12), (9, 10)],
        "Rock":         [(0, 8),  (1, 6),  (4, -2), (7, 7), (9, 8)],
        "Pop":          [(0, 4),  (2, 5),  (3, 4),  (5, -1), (7, 6)],
        "Jazz":         [(1, 5),  (3, 3),  (6, 4)],
        "Classical":    [(2, 4),  (5, 3)],
        "Dance":        [(0, 10), (3, -3), (6, 6),  (9, 8)],
        "Vocal Boost":  [(3, 6),  (4, 8),  (5, 6)],
        "Flat":         [(i, 0.0) for i in range(10)],
        "Custom":       [],
    }

    # VLC band names for display
    BAND_LABELS = [
        "60Hz", "170Hz", "310Hz", "600Hz", "1kHz",
        "3kHz", "6kHz",  "12kHz", "14kHz", "16kHz",
    ]

    def __init__(self):
        self.enabled          = False
        self.current_preset   = "None"
        self._bands: list[float]        = [0.0] * 10
        self._custom_bands: list[float] = [0.0] * 10
        self._on_change_callback        = None

    def set_on_change_callback(self, cb):
        self._on_change_callback = cb

    def set_preset(self, name: str):
        """Load a named preset into band array."""
        self._bands = [0.0] * 10
        if name == "Custom":
            self._bands = self._custom_bands.copy()
        else:
            for idx, amp in self.PRESETS.get(name, []):
                if 0 <= idx < 10:
                    self._bands[idx] = float(amp)
        self.current_preset = name
        self._notify()

    def set_custom_bands(self, gains: list[float]):
        """Set 10 custom band gains (-20 to +20 dB each)."""
        if len(gains) != 10:
            log(f"Custom EQ: need 10 values, got {len(gains)}", "warning")
            return
        self._custom_bands = [max(-20.0, min(20.0, g)) for g in gains]
        self.set_preset("Custom")

    def toggle(self, enabled: bool):
        if self.enabled != enabled:
            self.enabled = enabled
            self._notify()

    def get_bands(self) -> list[float]:
        return self._bands.copy()

    def get_summary(self) -> str:
        """Return short human-readable band summary."""
        non_zero = [
            f"{self.BAND_LABELS[i]}={v:+.0f}"
            for i, v in enumerate(self._bands)
            if abs(v) > 0.1
        ]
        return "  ".join(non_zero) if non_zero else "(flat)"

    def _notify(self):
        if self._on_change_callback:
            try:
                self._on_change_callback()
            except Exception:
                pass