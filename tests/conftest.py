"""Shared fixtures: fake vlc module + isolated data dir.

The fake vlc lets us import and drive the full UI/player stack without
libvlc installed (CI runners have no VLC). Only what player.py touches
at import/usage time is implemented.
"""

import sys
import types

import pytest


class _FakeState:
    NothingSpecial = "NothingSpecial"
    Opening = "Opening"
    Buffering = "Buffering"
    Playing = "Playing"
    Paused = "Paused"
    Stopped = "Stopped"
    Ended = "Ended"
    Error = "Error"


class _FakeMeta:
    NowPlaying = "NowPlaying"
    Title = "Title"
    Artist = "Artist"


class _FakeEventType:
    MediaPlayerEncounteredError = "err"
    MediaPlayerEndReached = "end"
    MediaPlayerPlaying = "playing"
    MediaPlayerBuffering = "buffering"


class _FakeEventManager:
    def event_attach(self, *args):
        pass


class _FakeMedia:
    def __init__(self, *args):
        self._meta = {}
        self.options = list(args)

    def add_option(self, opt):
        pass

    def get_meta(self, key):
        return self._meta.get(key)


class _FakeMediaPlayer:
    def __init__(self):
        self.media = None
        self.eq = None
        self.volume = -1
        self.state = _FakeState.NothingSpecial

    def event_manager(self):
        return _FakeEventManager()

    def set_media(self, media):
        self.media = media

    def play(self):
        self.state = _FakeState.Playing
        return 0

    def stop(self):
        self.state = _FakeState.Stopped

    def pause(self):
        # libvlc pause() toggles between playing and paused
        self.state = (
            _FakeState.Playing if self.state == _FakeState.Paused else _FakeState.Paused
        )

    def audio_set_volume(self, vol):
        self.volume = vol

    def get_state(self):
        return self.state

    def set_equalizer(self, eq):
        self.eq = eq

    def release(self):
        pass


class _FakeAudioEqualizer:
    def __init__(self):
        self.preamp = 0.0
        self.bands = {}

    def set_preamp(self, value):
        self.preamp = value

    def set_amp_at_index(self, gain, idx):
        self.bands[idx] = gain


class _FakeInstance:
    def __init__(self, *args):
        pass

    def media_player_new(self):
        return _FakeMediaPlayer()

    def media_new(self, *args):
        return _FakeMedia(*args)

    def release(self):
        pass


def _install_fake_vlc():
    if "vlc" in sys.modules and hasattr(sys.modules["vlc"], "_is_fake"):
        return
    fake = types.ModuleType("vlc")
    fake._is_fake = True
    fake.State = _FakeState
    fake.Meta = _FakeMeta
    fake.EventType = _FakeEventType
    fake.Instance = _FakeInstance
    fake.MediaPlayer = _FakeMediaPlayer
    fake.Media = _FakeMedia
    fake.AudioEqualizer = _FakeAudioEqualizer
    fake.libvlc_get_version = lambda: b"3.0.20 Vetinari"
    sys.modules["vlc"] = fake


_install_fake_vlc()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "appdata"
    monkeypatch.setenv("RADIO_PS_DATA_DIR", str(d))
    return d


@pytest.fixture()
def cli(data_dir, monkeypatch):
    """RadioCLI wired to a fake VLC player and stubbed network calls."""
    monkeypatch.setattr("radio_ps.ui.cli_ui.fetch_stations", lambda q, limit=30: [])
    monkeypatch.setattr("radio_ps.ui.cli_ui.fetch_category", lambda c, **kw: [])
    monkeypatch.setattr("radio_ps.ui.cli_ui.preload_categories", lambda: None)
    monkeypatch.setattr("radio_ps.ui.cli_ui.refresh_categories", lambda: None)
    monkeypatch.setattr("radio_ps.ui.cli_ui.start_refresh_timer", lambda: None)
    monkeypatch.setattr("radio_ps.ui.cli_ui.stop_refresh_timer", lambda: None)
    from radio_ps.ui.cli_ui import RadioCLI

    app = RadioCLI()
    app._init_player()
    return app
