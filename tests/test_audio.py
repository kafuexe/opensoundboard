import mmap
import struct

import numpy as np
import pytest

from soundboard.audio.decode import ENGINE_RATE, DecodeCache, decode_file, resample, to_stereo
from soundboard.audio.mixer import Mixer
from soundboard.audio.outputs import (
    HEARTBEAT_OFFSET, NOT_INSTALLED, NOT_RUNNING, RATE_OFFSET, READ_POS_OFFSET, RING_HEADER, RING_HEADER_SIZE, RING_MAGIC, RING_VERSION,
    WRITE_POS_OFFSET, MicRing, PluginMicOutput, StreamResampler, tick_ms,
)


def test_to_stereo_duplicates_mono():
    out = to_stereo(np.array([[0.1], [0.2]], dtype=np.float32))
    assert out.shape == (2, 2) and np.allclose(out[:, 0], out[:, 1])


def test_resample_length():
    data = np.zeros((44100, 2), dtype=np.float32)
    assert len(resample(data, 44100, 48000)) == 48000


def test_decode_file_to_engine_rate(wav_file):
    data = decode_file(wav_file(seconds=0.5, rate=22050))
    assert data.shape == (ENGINE_RATE // 2, 2)
    assert data.dtype == np.float32


def test_cache_returns_same_array(wav_file):
    cache = DecodeCache()
    path = wav_file()
    assert cache.get(path) is cache.get(path)


def test_mixer_sums_and_finishes():
    m = Mixer(gain=1.0)
    m.add("a", np.full((4, 2), 0.25, dtype=np.float32))
    m.add("b", np.full((2, 2), 0.25, dtype=np.float32), gain=2.0)
    out = m.render(3)
    assert np.allclose(out[:2], 0.75) and np.allclose(out[2], 0.25)
    assert m.active_keys() == {"a"}
    m.render(10)
    assert m.active_keys() == set()


def test_mixer_master_gain_and_clip():
    m = Mixer(gain=0.5)
    m.add("a", np.full((2, 2), 4.0, dtype=np.float32))
    assert np.allclose(m.render(2), 1.0)


def test_mixer_stop_one():
    m = Mixer()
    m.add("a", np.ones((10, 2), dtype=np.float32))
    m.add("b", np.ones((10, 2), dtype=np.float32))
    m.stop("a")
    assert m.active_keys() == {"b"}
    assert m.progress("b") == 0.0


def _make_ring(name: str, capacity: int, rate: int = 0) -> mmap.mmap:
    """What the plugin does when it creates the ring (and, with rate, starts processing)."""
    buf = mmap.mmap(-1, RING_HEADER_SIZE + capacity * 8, tagname=name)
    RING_HEADER.pack_into(buf, 0, RING_MAGIC, RING_VERSION, rate, 2, capacity, 0, 0, 0, tick_ms())
    return buf


def test_ring_header_matches_the_plugin():
    # apo/src/ring.h static_asserts the same offsets.
    assert RING_HEADER.size <= RING_HEADER_SIZE == 64
    assert (RATE_OFFSET, WRITE_POS_OFFSET, READ_POS_OFFSET, HEARTBEAT_OFFSET) == (8, 24, 32, 40)
    assert RING_VERSION == 2


def test_mic_ring_wraps_and_respects_free_space():
    name = "Local\\SoundboardTestRing1"
    plugin_side = _make_ring(name, capacity=8)
    ring = MicRing.open(name)
    try:
        frames = np.arange(6, dtype=np.float32).repeat(2).reshape(6, 2)
        assert ring.write(frames) == 6
        assert ring.write(frames) == 2  # only 2 free
        # plugin consumes 5 frames
        struct.pack_into("<Q", plugin_side, READ_POS_OFFSET, 5)
        assert ring.fill() == 3
        assert ring.write(np.full((4, 2), 9, dtype=np.float32)) == 4  # wraps around the end
        data = np.frombuffer(plugin_side[RING_HEADER_SIZE : RING_HEADER_SIZE + 64], dtype=np.float32).reshape(8, 2)
        assert data[:4, 0].tolist() == [9, 9, 9, 9]  # wrapped writes landed at the start
        assert data[4:, 0].tolist() == [4, 5, 0, 1]  # unread frames untouched
    finally:
        ring.close()
        plugin_side.close()


def test_mic_ring_rejects_uninitialized_memory():
    name = "Local\\SoundboardTestRing2"
    blank = mmap.mmap(-1, 4096, tagname=name)
    try:
        with pytest.raises(ConnectionError):
            MicRing.open(name)
    finally:
        blank.close()


def test_mic_ring_rejects_old_version():
    name = "Local\\SoundboardTestRing3"
    buf = mmap.mmap(-1, RING_HEADER_SIZE + 64, tagname=name)
    RING_HEADER.pack_into(buf, 0, RING_MAGIC, 1, ENGINE_RATE, 2, 8, 0, 0, 0, 0)
    try:
        with pytest.raises(ConnectionError):
            MicRing.open(name)
    finally:
        buf.close()


def test_opening_never_creates_the_ring():
    with pytest.raises(ConnectionError):
        MicRing.open("Local\\SoundboardTestRingThatDoesNotExist")


def test_mic_running_needs_rate_and_fresh_heartbeat():
    name = "Local\\SoundboardTestRing4"
    plugin_side = _make_ring(name, capacity=8)
    ring = MicRing.open(name)
    try:
        assert not ring.mic_running()  # rate 0: the plugin isn't processing
        struct.pack_into("<I", plugin_side, RATE_OFFSET, 44100)
        now = tick_ms()
        struct.pack_into("<Q", plugin_side, HEARTBEAT_OFFSET, now)
        assert ring.mic_running(now + 10)
        assert not ring.mic_running(now + 1000)  # nobody recording: audiodg stopped calling the plugin
    finally:
        ring.close()
        plugin_side.close()


@pytest.mark.parametrize("dst", [44100, 48000, 96000, 16000])
def test_stream_resampler_keeps_pitch_and_is_seamless(dst):
    t = np.arange(ENGINE_RATE) / ENGINE_RATE
    tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    src = np.stack([tone, tone], axis=1)
    r = StreamResampler(ENGINE_RATE, dst)
    out = np.concatenate([r.process(src[i : i + 333]) for i in range(0, len(src), 333)])  # odd block size
    assert abs(len(out) - dst) <= 1
    # Resampling interpolates from the frame before each block, so it runs one source frame late
    # and the first frames blend in from silence.
    delay = 0 if dst == ENGINE_RATE else 1 / ENGINE_RATE
    expected = np.sin(2 * np.pi * 440 * (np.arange(len(out)) / dst - delay))
    assert np.max(np.abs(out[2:, 0] - expected[2:])) < 0.02  # same tone, no glitches at block edges


def test_stream_resampler_source_frames_for():
    r = StreamResampler(48000, 44100)
    total = 0
    for _ in range(50):
        total += len(r.process(np.zeros((r.source_frames_for(441), 2), dtype=np.float32)))
    assert abs(total - 50 * 441) <= 50  # asks for about the right amount every time


def test_plugin_output_feeds_at_the_mic_rate(monkeypatch):
    name = "Local\\SoundboardTestRing5"
    plugin_side = _make_ring(name, capacity=4096, rate=44100)
    mixer = Mixer()
    mixer.add("beep", np.full((48000, 2), 0.5, dtype=np.float32))
    out = PluginMicOutput(mixer, ring_name=name)
    out._ring = MicRing.open(name)
    try:
        struct.pack_into("<Q", plugin_side, HEARTBEAT_OFFSET, tick_ms())
        out.feed_once()
        fill = out._ring.fill()
        assert abs(fill - 44100 // 50) <= 2  # ~20 ms at the mic's rate
        data = np.frombuffer(plugin_side[RING_HEADER_SIZE : RING_HEADER_SIZE + fill * 8], dtype=np.float32)
        assert np.allclose(data[2:], 0.5, atol=1e-3)  # first frame blends from silence

        struct.pack_into("<Q", plugin_side, HEARTBEAT_OFFSET, 0)  # mic went idle
        before = mixer.progress("beep")
        out.feed_once()
        assert out._ring.fill() == fill  # nothing written...
        assert mixer.progress("beep") > before  # ...but the sound kept moving so it won't play late
    finally:
        out._ring.close()
        out._ring = None
        plugin_side.close()


@pytest.mark.parametrize("has_plugin, error, waiting, shown", [
    (True, NOT_RUNNING, True, ""),                    # plugin on this mic, no app has the mic open
    (False, NOT_RUNNING, False, NOT_INSTALLED),       # this mic doesn't have the plugin
    (True, "unsupported ring format", False, "unsupported ring format"),  # a real problem
])
def test_plugin_connect_failure_explains_itself(monkeypatch, has_plugin, error, waiting, shown):
    from soundboard.audio import outputs
    monkeypatch.setattr(outputs, "has_plugin", lambda values: has_plugin)
    monkeypatch.setattr(outputs, "read_fx", lambda mic_id: {})
    out = PluginMicOutput(Mixer(), "{yeti}")
    assert out.ring_name == "Global\\SoundboardMicRing.{yeti}"
    out._connect_failed(error)
    assert out.waiting_for_mic is waiting and out.error == shown


def test_cache_holds_short_sounds_as_16_bit_and_respects_its_size_cap(wav_file):
    cache = DecodeCache(max_bytes=200_000)
    paths = [wav_file(f"s{i}.wav", seconds=0.5) for i in range(3)]  # 24000 frames x 4 bytes = 96 KB each
    first = cache.get(paths[0])
    assert first.dtype == np.int16 and first.shape == (24000, 2)
    cache.get(paths[1])
    cache.get(paths[2])  # 288 KB > 200 KB: the oldest goes
    assert cache.size_bytes <= 200_000
    assert cache.get(paths[2]) is cache.get(paths[2])
    assert cache.get(paths[0]) is not first  # was evicted, decoded again


def test_cache_doesnt_keep_long_sounds(wav_file):
    cache = DecodeCache(max_cached_seconds=1.0)
    long_sound = wav_file("song.wav", seconds=2)
    data = cache.get(long_sound)
    assert len(data) == 2 * ENGINE_RATE  # still playable
    assert cache.size_bytes == 0 and cache.get(long_sound) is not data


def test_16_bit_voices_mix_like_float_ones():
    as_float = np.full((480, 2), 0.5, dtype=np.float32)
    as_int16 = (as_float * 32767).astype(np.int16)
    a, b = Mixer(), Mixer()
    a.add("x", as_float, gain=0.8)
    b.add("x", as_int16, gain=0.8)
    assert np.allclose(a.render(480), b.render(480), atol=1e-4)


def test_numpy_math_library_is_limited_to_one_thread():
    import os
    import soundboard  # noqa: F401  (sets it on import)
    assert os.environ["OPENBLAS_NUM_THREADS"] == "1"
