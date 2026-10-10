import mmap
import struct

import numpy as np
import pytest

from soundboard.audio.decode import ENGINE_RATE, DecodeCache, decode_file, resample, to_stereo
from soundboard.audio.mixer import Mixer
from soundboard.audio.outputs import RING_HEADER, RING_HEADER_SIZE, RING_MAGIC, RING_VERSION, MicRing


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


def _make_ring(name: str, capacity: int) -> mmap.mmap:
    buf = mmap.mmap(-1, RING_HEADER_SIZE + capacity * 8, tagname=name)
    RING_HEADER.pack_into(buf, 0, RING_MAGIC, RING_VERSION, ENGINE_RATE, 2, capacity, 0, 0, 0)
    return buf


def test_mic_ring_wraps_and_respects_free_space():
    name = "Local\\SoundboardTestRing1"
    plugin_side = _make_ring(name, capacity=8)
    ring = MicRing.open(name)
    try:
        frames = np.arange(6, dtype=np.float32).repeat(2).reshape(6, 2)
        assert ring.write(frames) == 6
        assert ring.write(frames) == 2  # only 2 free
        # plugin consumes 5 frames
        struct.pack_into("<Q", plugin_side, 32, 5)
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
