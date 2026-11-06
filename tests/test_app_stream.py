import subprocess
from types import SimpleNamespace

import numpy as np

from soundboard.audio import app_stream
from soundboard.audio.mixer import LiveSource, Mixer


def chunk(frames, value=0.5):
    return np.full((frames, 2), value, dtype=np.float32)


def test_live_source_waits_for_a_cushion_then_plays_in_order():
    src = LiveSource(prebuffer=100)
    src.push(chunk(60, 0.1))
    assert not src.pull(10).any()  # under the 100-frame cushion: silence, nothing consumed
    src.push(chunk(60, 0.2))
    out = src.pull(80)
    assert np.allclose(out[:60], 0.1) and np.allclose(out[60:], 0.2)
    assert src.buffered == 40


def test_live_source_runs_dry_and_rebuilds_the_cushion():
    src = LiveSource(prebuffer=50)
    src.push(chunk(60))
    out = src.pull(100)  # 60 real frames, then silence
    assert np.allclose(out[:60], 0.5) and not out[60:].any()
    src.push(chunk(30))
    assert not src.pull(10).any()  # below the cushion again: waits
    src.push(chunk(30))
    assert src.pull(10).any()


def test_live_source_drops_the_oldest_audio_when_behind():
    src = LiveSource(prebuffer=0, max_frames=100)
    for value in (0.1, 0.2, 0.3):
        src.push(chunk(50, value))
    assert src.buffered == 100
    assert np.allclose(src.pull(50), 0.2)  # 0.1 was dropped


def test_mixer_streams_with_their_own_gain_and_stop_all_leaves_them():
    m = Mixer(gain=0.5)
    src = LiveSource(gain=0.4, prebuffer=0)
    m.add_stream("app", src)
    assert m.has_audio() and m.active_keys() == set()  # a stream isn't a "sound playing"
    src.push(chunk(100, 1.0))
    assert np.allclose(m.render(100), 0.2)  # 1.0 * stream 0.4 * mixer 0.5
    m.stop()  # Stop all sounds
    assert m.has_audio()
    m.remove_stream("app")
    assert not m.has_audio()


def test_list_apps_parses_the_helper_and_skips_us(monkeypatch, tmp_path):
    helper = tmp_path / "SoundboardCapture.exe"
    helper.write_bytes(b"")
    monkeypatch.setattr(app_stream, "helper_path", lambda: helper)
    monkeypatch.setattr(app_stream.os, "getpid", lambda: 999)
    out = "852\t0\tchrome.exe\tGoogle Chrome\n999\t1\tpython.exe\tPython\n7\t1\tSpotify.exe\tSpotify\nbad line\n"
    monkeypatch.setattr(app_stream.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out.encode()))
    apps = app_stream.list_apps()
    assert [(a.pid, a.name, a.playing) for a in apps] == [(7, "Spotify", True), (852, "Google Chrome", False)]


def test_stream_feeds_the_mic_mixer_and_reports_when_the_app_closes(monkeypatch, tmp_path):
    helper = tmp_path / "SoundboardCapture.exe"
    helper.write_bytes(b"")
    monkeypatch.setattr(app_stream, "helper_path", lambda: helper)
    audio = chunk(4800, 0.25).tobytes()

    class FakeProc:
        def __init__(self, *a, **k):
            self.stdout = SimpleNamespace(read1=self._read)
            self.stderr = SimpleNamespace(read=lambda: b"")
            self._parts = [audio[:1003], audio[1003:]]  # split mid-frame on purpose
        def _read(self, n):
            return self._parts.pop(0) if self._parts else b""
        def wait(self, timeout=None):
            return 3  # the app exited
        def kill(self):
            pass

    monkeypatch.setattr(app_stream.subprocess, "Popen", FakeProc)
    mixer = Mixer()
    stream = app_stream.AppStream(mixer, gain=1.0)
    ended = []
    stream.start(app_stream.AudioApp(7, "Spotify.exe", "Spotify", True), on_end=ended.append)
    import time
    for _ in range(50):
        if ended:
            break
        time.sleep(0.02)
    assert ended == ["Spotify closed"]
    assert stream.source.buffered == 4800  # every frame arrived, despite the split
    assert not stream.running and not mixer.has_audio()  # cleaned up after the app closed
