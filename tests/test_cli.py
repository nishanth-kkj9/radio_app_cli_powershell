"""CLI dispatch regression tests (run on the fake vlc module from conftest)."""


def test_cli_helpers():
    from radio_ps.ui.cli_ui import _clean_name, _fmt_elapsed, _quality_badge, _truncate

    assert _clean_name("") == "Unknown Station"
    assert _truncate("abcdef", 4) == "abc…"
    assert _quality_badge(320).startswith("[bold green]")
    assert _fmt_elapsed(3661) == "1h 01m 01s"


def test_mute_does_not_crash(cli):
    # Regression BUG-01: bare `green` identifier used to raise NameError.
    cli._dispatch("m")
    cli._dispatch("m")


def test_sort_no_args_does_not_crash(cli):
    # Regression BUG-02: malformed `[red>` markup used to raise MarkupError.
    cli._dispatch("sort")


def test_stop_command(cli):
    cli._stations = [{"name": "X", "url": "http://example.com/s"}]
    cli._dispatch("p 1")
    cli._dispatch("stop")
    assert cli._player.is_playing() is False


def test_volume_persisted_on_shutdown(cli):
    # Regression BUG-08: shutdown used to save hardcoded volume 70.
    from radio_ps.utils.storage import load_session

    cli._dispatch("v 45")
    cli._shutdown()
    assert load_session()["volume"] == 45


def test_eq_wiring_enables_equalizer(cli):
    # Regression BUG-04: the EQ could never be enabled before this fix.
    cli._dispatch("eq jazz")
    assert cli._player.equalizer.enabled is True
    assert cli._player.equalizer.current_preset == "Jazz"
    cli._dispatch("eq NONE")
    assert cli._player.equalizer.enabled is False


def test_unknown_eq_preset_is_error_not_crash(cli):
    cli._dispatch("eq doesnotexist")  # must print an error, not raise


def test_pause_resumes_playback(cli):
    cli._stations = [{"name": "X", "url": "http://example.com/s"}]
    cli._dispatch("p 1")
    cli._dispatch("pause")
    assert cli._player.is_paused() is True
    cli._dispatch("pause")
    assert cli._player.is_paused() is False


def test_pause_without_stream_is_safe(cli):
    cli._player._current_url = None
    cli._dispatch("pause")            # must print an error, not raise
    assert cli._player.toggle_pause() is None


def test_record_transcodes_to_mp3(cli):
    # Recording must produce valid MP3 for ANY source codec (OGG included),
    # so the sout chain has to carry a transcode step.
    ok = cli._player.record("http://example.com/stream.ogg", "rec.mp3")
    assert ok is True
    opts = cli._player._rec_player.media.options
    assert any("acodec=mp3" in str(o) for o in opts)
    cli._player.stop_recording()


def test_eq_partial_preset_matches(cli):
    # 'bass' should uniquely resolve to Bass Boost and enable it.
    cli._dispatch("eq bass")
    assert cli._player.equalizer.current_preset == "Bass Boost"
    assert cli._player.equalizer.enabled is True


def test_eq_list_shows_panel(cli):
    cli._dispatch("eq ls")
    cli._dispatch("eq list")


def test_cat_numeric_category(cli):
    cli._dispatch("cat 6")  # 6th category = jazz
    assert cli._category == "jazz"


def test_record_sanitizes_filename(cli):
    # Regression SEC-01: traversal/punctuation must not survive into the path.
    captured = {}

    def fake_record(url, path):
        captured["path"] = path
        return True

    cli._player.record = fake_record
    cli._player._current_url = "http://example.com/s"
    cli._cmd_record(["..\\..\\evil,name}.mp3"])
    p = captured["path"]
    assert ".." not in p and "," not in p and "}" not in p
    assert "evilnamemp3" in p or "evilname" in p


def test_dispatch_smoke_all_documented_commands(cli):
    """Every README-documented command routes without raising (stubbed network)."""
    commands = [
        "h", "ls", "now", "vlcinfo", "datadir", "log", "clean",
        "preload_status", "info", "m", "sort name", "sort bitrate",
        "sort votes", "sort country", "stop", "f", "eq", "n", "b", "r",
        "p", "s foo", "cat top", "v 50", "sleep 1", "sleep 2",
        "eq custom 1 2 3 4 5 6 7 8 9 10", "eq bass boost", "bogus_cmd",
    ]
    for cmd in commands:
        cli._dispatch(cmd)
