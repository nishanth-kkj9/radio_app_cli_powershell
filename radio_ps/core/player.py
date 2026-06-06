"""
core/player.py — Windows-native VLC radio player via python-vlc (libvlc).

Advantages over the old cvlc+RC-socket approach:
  • Direct libvlc API — no subprocess, no socket I/O, no banner-draining hacks
  • Native event system: MediaPlayerPlaying / Error / EndReached
  • Native volume control via audio_set_volume()
  • Native 10-band EQ via vlc.AudioEqualizer API
  • ICY/stream metadata via media.get_meta(vlc.Meta.NowPlaying)
  • Reliable state detection: player.get_state() returns vlc.State enum
  • Works everywhere VLC is installed on Windows — no port conflicts
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Optional

from core.api import is_safe_url
from core.config import (
    VLC_INSTANCE_ARGS,
    HEALTH_INTERVAL,
    MAX_RECONNECT,
    RECONNECT_DELAYS,
)
from core.equalizer import Equalizer
from utils.logger import log


# ── VLC import with friendly error ────────────────────────────────────────────

def _ensure_vlc_path() -> None:
    """Add VLC's install directory to PATH/DLL search so python-vlc can find libvlc.dll."""
    if sys.platform != "win32":
        return
    candidates = [
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\VideoLAN\VLC"),
    ]
    for path in candidates:
        if os.path.isfile(os.path.join(path, "libvlc.dll")):
            if path not in os.environ.get("PATH", ""):
                os.environ["PATH"] = path + ";" + os.environ.get("PATH", "")
            # Also needed for Python 3.8+ DLL loading on Windows
            try:
                os.add_dll_directory(path)
            except (AttributeError, OSError):
                pass
            log(f"VLC found at: {path}", "debug")
            return
    log("VLC not found in common paths; hoping it is on PATH", "warning")


_ensure_vlc_path()

try:
    import vlc  # python-vlc
except ImportError as _e:
    raise ImportError(
        "\n\n  python-vlc is not installed.\n"
        "  Run:  pip install python-vlc\n"
        "  Also ensure VLC is installed from https://www.videolan.org/vlc/\n"
    ) from _e
except Exception as _e:
    raise RuntimeError(
        f"\n\n  Could not load libvlc: {_e}\n"
        "  Make sure VLC (64-bit) is installed and matches your Python bitness.\n"
        "  Download: https://www.videolan.org/vlc/\n"
    ) from _e


# ── VLC state sets ─────────────────────────────────────────────────────────────

_ACTIVE_STATES = frozenset({
    vlc.State.Opening,
    vlc.State.Buffering,
    vlc.State.Playing,
    vlc.State.Paused,
})

_ERROR_STATES = frozenset({
    vlc.State.Error,
    vlc.State.Ended,
})

_STATE_LABELS = {
    vlc.State.NothingSpecial: "idle",
    vlc.State.Opening:        "opening",
    vlc.State.Buffering:      "buffering",
    vlc.State.Playing:        "playing",
    vlc.State.Paused:         "paused",
    vlc.State.Stopped:        "stopped",
    vlc.State.Ended:          "ended",
    vlc.State.Error:          "error",
}


# ── RadioPlayer ────────────────────────────────────────────────────────────────

class RadioPlayer:
    """
    Thread-safe internet radio player backed by libvlc via python-vlc.

    Public interface (matches cli_ui.py expectations):
      play(url)          → bool
      stop()
      is_playing()       → bool
      set_volume(0-100)
      toggle_mute()      → bool
      get_current_metadata() → {"title": str, "artist": str}
      get_current_url()  → str | None
      set_equalizer_preset(name)
      toggle_equalizer(bool)
      get_state_label()  → str
      record(url, path)  → start recording to file
      stop_recording()
      shutdown()
    """

    def __init__(self, on_permanent_failure: Optional[Callable[[str], None]] = None):
        self._on_failure  = on_permanent_failure
        self._volume      = 70
        self._muted       = False
        self.equalizer    = Equalizer()
        self._eq_obj      = None   # Keep VLC EQ object alive (prevent GC)

        self._current_url: str | None = None
        self._intentional_stop        = False
        self.reconnecting             = False
        self._reconnect_count         = 0
        self._play_start              = 0.0

        self._vlc_lock       = threading.RLock()
        self._reconnect_lock = threading.Lock()
        self._monitor_gen    = 0

        # Recording
        self._rec_player: vlc.MediaPlayer | None = None
        self._rec_instance: vlc.Instance | None  = None
        self._rec_path: str | None               = None

        # Create VLC instance + player
        self._instance: vlc.Instance     = vlc.Instance(*VLC_INSTANCE_ARGS)
        self._player:   vlc.MediaPlayer  = self._instance.media_player_new()
        self._media:    vlc.Media | None = None

        # Attach VLC event callbacks
        em = self._player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                        self._on_vlc_error)
        em.event_attach(vlc.EventType.MediaPlayerEndReached,
                        self._on_vlc_end)
        em.event_attach(vlc.EventType.MediaPlayerPlaying,
                        self._on_vlc_playing)
        em.event_attach(vlc.EventType.MediaPlayerBuffering,
                        self._on_vlc_buffering)

        # EQ change → re-apply automatically
        self.equalizer.set_on_change_callback(self._apply_eq)

        # Health monitor
        self._health_stop   = threading.Event()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="vlc-health"
        )
        self._health_thread.start()

        log("VLC player ready (python-vlc / libvlc)", "info")

    # ── VLC events ────────────────────────────────────────────────────────────

    def _on_vlc_error(self, event):
        if not self._intentional_stop and self._current_url:
            log("VLC error event received", "warning")
            threading.Thread(
                target=self._recover_playback,
                args=("VLC reported error",),
                daemon=True,
                name="recover",
            ).start()

    def _on_vlc_end(self, event):
        if not self._intentional_stop and self._current_url:
            log("VLC stream ended unexpectedly", "warning")
            threading.Thread(
                target=self._recover_playback,
                args=("Stream ended",),
                daemon=True,
                name="recover",
            ).start()

    def _on_vlc_playing(self, event):
        log("VLC: now playing", "debug")
        # Reset reconnect counter on confirmed playback
        if self._reconnect_count > 0:
            log(f"Stream recovered after {self._reconnect_count} attempt(s)", "info")
        self._reconnect_count = 0
        self.reconnecting     = False

    def _on_vlc_buffering(self, event):
        log("VLC: buffering…", "debug")

    # ── Play ──────────────────────────────────────────────────────────────────

    def play(self, url: str) -> bool:
        if not is_safe_url(url):
            log(f"Blocked unsafe URL: {url!r}", "warning")
            return False

        with self._vlc_lock:
            # Signal intentional so existing event handlers don't kick in
            self._intentional_stop = True
            self._player.stop()
            self._intentional_stop = False

            self._current_url     = url
            self._reconnect_count = 0
            self._play_start      = time.time()
            self._monitor_gen    += 1

            # Build media with per-item network options
            media = self._instance.media_new(url)
            media.add_option(":network-caching=3000")
            media.add_option(":live-caching=3000")
            media.add_option(":http-reconnect")
            self._player.set_media(media)
            self._media = media

            rc = self._player.play()
            if rc != 0:
                log(f"VLC play() returned {rc}", "error")
                self._current_url = None
                return False

            # Apply volume and EQ right after play()
            self._player.audio_set_volume(0 if self._muted else self._volume)
            self._apply_eq()

        log(f"Playing: {url}", "info")
        return True

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self):
        self._intentional_stop = True
        self.reconnecting      = False
        with self._vlc_lock:
            self._player.stop()
        self._current_url     = None
        self._reconnect_count = 0
        self._monitor_gen    += 1

    # ── Health monitor ────────────────────────────────────────────────────────

    def _health_loop(self):
        """Periodic state check; triggers recovery if stream silently stalls."""
        while not self._health_stop.is_set():
            time.sleep(HEALTH_INTERVAL)
            if self._intentional_stop or not self._current_url:
                continue
            state = self._player.get_state()
            if state in _ERROR_STATES and not self.reconnecting:
                self._recover_playback(f"Health check: state={_STATE_LABELS.get(state, state)}")

    # ── Recovery ──────────────────────────────────────────────────────────────

    def _recover_playback(self, reason: str) -> None:
        if self._intentional_stop or not self._current_url:
            return
        if not self._reconnect_lock.acquire(blocking=False):
            return   # Another recovery is already in progress
        try:
            self.reconnecting      = True
            self._reconnect_count += 1

            if self._reconnect_count > MAX_RECONNECT:
                log(f"{reason} — max reconnect attempts reached", "error")
                url = self._current_url
                self.stop()
                if self._on_failure and url:
                    self._on_failure(url)
                return

            delay = RECONNECT_DELAYS[
                min(self._reconnect_count - 1, len(RECONNECT_DELAYS) - 1)
            ]
            log(
                f"{reason} — reconnecting in {delay}s "
                f"(attempt {self._reconnect_count}/{MAX_RECONNECT})",
                "warning",
            )
            time.sleep(delay)

            if self._intentional_stop or not self._current_url:
                return

            url = self._current_url
            with self._vlc_lock:
                media = self._instance.media_new(url)
                media.add_option(":network-caching=3000")
                media.add_option(":http-reconnect")
                self._player.set_media(media)
                self._media = media
                self._player.play()
                self._player.audio_set_volume(0 if self._muted else self._volume)
                self._apply_eq()

        finally:
            # reconnecting flag is cleared by _on_vlc_playing or if we gave up
            if self._reconnect_count > MAX_RECONNECT:
                self.reconnecting = False
            self._reconnect_lock.release()

    # ── Volume / Mute ─────────────────────────────────────────────────────────

    def set_volume(self, vol: int):
        vol = max(0, min(100, int(vol)))
        self._volume = vol
        if not self._muted:
            self._player.audio_set_volume(vol)

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        self._player.audio_set_volume(0 if self._muted else self._volume)
        return self._muted

    # ── State ─────────────────────────────────────────────────────────────────

    def is_playing(self) -> bool:
        if self.reconnecting:
            return True   # Show as active while reconnecting
        if self._intentional_stop or not self._current_url:
            return False
        return self._player.get_state() in _ACTIVE_STATES

    def get_state_label(self) -> str:
        if self.reconnecting:
            return "reconnecting"
        return _STATE_LABELS.get(self._player.get_state(), "unknown")

    def get_current_url(self) -> str | None:
        return self._current_url

    # ── Metadata ──────────────────────────────────────────────────────────────

    def get_current_metadata(self) -> dict:
        """
        Return ICY metadata from the live stream.
        VLC updates Meta.NowPlaying automatically from ICY headers.
        No polling or parsing needed — just call get_meta().
        """
        if not self._media:
            return {"title": "", "artist": ""}
        now_playing = (self._media.get_meta(vlc.Meta.NowPlaying) or "").strip()
        title       = (self._media.get_meta(vlc.Meta.Title)      or "").strip()
        artist      = (self._media.get_meta(vlc.Meta.Artist)     or "").strip()
        # NowPlaying (ICY StreamTitle) is the most useful for radio
        return {"title": now_playing or title, "artist": artist}

    # ── Equalizer ─────────────────────────────────────────────────────────────

    def set_equalizer_preset(self, preset: str):
        self.equalizer.set_preset(preset)
        # _apply_eq is called by the on_change_callback

    def toggle_equalizer(self, enabled: bool):
        self.equalizer.toggle(enabled)
        # _apply_eq is called by the on_change_callback

    def _apply_eq(self):
        """Apply current equalizer state to the VLC player via libvlc AudioEqualizer."""
        if not self.equalizer.enabled or self.equalizer.current_preset == "None":
            self._player.set_equalizer(None)
            self._eq_obj = None
            return

        eq = vlc.AudioEqualizer()
        eq.set_preamp(0.0)
        bands = self.equalizer.get_bands()
        for i, gain in enumerate(bands):
            eq.set_amp_at_index(float(gain), i)

        self._player.set_equalizer(eq)
        self._eq_obj = eq   # Prevent GC — libvlc holds a raw pointer!
        log(f"EQ applied via libvlc: {self.equalizer.current_preset}", "debug")

    # ── Recording ─────────────────────────────────────────────────────────────

    def record(self, url: str, output_path: str) -> bool:
        """
        Start recording the stream to a file in parallel with live playback.
        Uses a separate VLC instance so recording doesn't affect playback.
        """
        if not is_safe_url(url):
            return False
        self.stop_recording()

        self._rec_instance = vlc.Instance("--no-video", "--quiet")
        self._rec_player   = self._rec_instance.media_player_new()

        sout = (
            f"#duplicate{{dst=std{{access=file,mux=raw,dst={output_path}}},"
            f"dst=nodisplay}}"
        )
        media = self._rec_instance.media_new(url, f"sout={sout}", "sout-keep")
        self._rec_player.set_media(media)
        result = self._rec_player.play()
        if result == 0:
            self._rec_path = output_path
            log(f"Recording started → {output_path}", "info")
            return True
        else:
            log(f"Recording failed (VLC returned {result})", "error")
            self.stop_recording()
            return False

    def stop_recording(self):
        """Stop any active recording."""
        if self._rec_player:
            try:
                self._rec_player.stop()
                self._rec_player.release()
            except Exception:
                pass
            self._rec_player = None
        if self._rec_instance:
            try:
                self._rec_instance.release()
            except Exception:
                pass
            self._rec_instance = None
        if self._rec_path:
            log(f"Recording stopped. File: {self._rec_path}", "info")
            saved = self._rec_path
            self._rec_path = None
            return saved
        return None

    def is_recording(self) -> bool:
        return (
            self._rec_player is not None
            and self._rec_player.get_state() in _ACTIVE_STATES
        )

    def get_recording_path(self) -> str | None:
        return self._rec_path

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self):
        """Release all VLC resources. Call on application exit."""
        self._health_stop.set()
        self.stop_recording()
        self.stop()
        try:
            self._player.release()
            self._instance.release()
        except Exception:
            pass
        log("VLC player shut down cleanly", "info")
