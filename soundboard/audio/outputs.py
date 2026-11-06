"""Audio outputs. Each owns a Mixer and pulls from it on its own clock.

- DeviceOutput: a speaker/headphone/virtual-cable device via sounddevice (WASAPI).
- PluginMicOutput: the shared-memory ring read by the Soundboard mic plugin (see docs/mic-bridge.md).
"""
from __future__ import annotations

import ctypes
import math
import struct
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from ..micplugin import ring_name as ring_name_for
from ..micplugin.fx import has_plugin
from ..micplugin.mics import read_fx
from .decode import ENGINE_RATE
from .mixer import Mixer


@dataclass(frozen=True)
class OutputDevice:
    index: int
    name: str


def list_output_devices() -> list[OutputDevice]:
    """WASAPI output devices (one entry per real endpoint, with readable names)."""
    try:
        wasapi = next(i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api["name"])
    except StopIteration:
        wasapi = None
    devices = []
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0 and (wasapi is None or dev["hostapi"] == wasapi):
            devices.append(OutputDevice(index, dev["name"]))
    return devices


def find_device(name: str) -> int | None:
    if not name:
        return None
    return next((d.index for d in list_output_devices() if d.name == name), None)


class DeviceOutput:
    """Plays its mixer to one output device. device_name "" means the system default."""

    def __init__(self, mixer: Mixer):
        self.mixer = mixer
        self.device_name = ""
        self.error = ""
        self._stream: sd.OutputStream | None = None

    def open(self, device_name: str) -> None:
        self.close()
        self.device_name = device_name
        self.error = ""
        index = find_device(device_name)
        if device_name and index is None:
            self.error = f"{device_name} isn't connected"
            return
        if index is None:
            index = _default_wasapi_output()
        try:
            extra = sd.WasapiSettings(auto_convert=True) if _is_wasapi(index) else None
            self._stream = sd.OutputStream(
                device=index, samplerate=ENGINE_RATE, channels=2, dtype="float32",
                latency="low", callback=self._callback, extra_settings=extra,
            )
            self._stream.start()
        except Exception as exc:  # device busy, unplugged, unsupported format...
            self._stream = None
            self.error = f"Can't open {device_name or 'the default output'}: {exc}"

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def _callback(self, outdata, frames, _time, _status) -> None:
        outdata[:] = self.mixer.render(frames)


def _is_wasapi(index: int | None) -> bool:
    if index is None:
        return False
    return "WASAPI" in sd.query_hostapis(sd.query_devices(index)["hostapi"])["name"]


def _default_wasapi_output() -> int | None:
    for api in sd.query_hostapis():
        if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
            return api["default_output_device"]
    return None


# --- Mic plugin bridge ---------------------------------------------------------------------
# Layout of the shared-memory ring (little endian). The plugin on each mic creates that mic's ring
# (micplugin.ring_name); the app writes into the one for the mic the user picked.
RING_MAGIC = 0x524D4253  # "SBMR"
RING_VERSION = 2
RING_CHANNELS = 2
# magic, version, rate, channels, capacity, consumer, write, read, heartbeat
RING_HEADER = struct.Struct("<IIIIIIQQQ")
RING_HEADER_SIZE = 64
RATE_OFFSET = 8
WRITE_POS_OFFSET = 24
READ_POS_OFFSET = 32
HEARTBEAT_OFFSET = 40
NOT_RUNNING = "the mic plugin isn't running"
NOT_INSTALLED = "the mic plugin isn't on this mic: add it in Settings"
# The plugin stamps the heartbeat every audio period (~10 ms). Older than this means nobody is
# recording from the mic, so audiodg isn't calling the plugin.
HEARTBEAT_TIMEOUT_MS = 250

_FILE_MAP_WRITE = 0x0002
_FILE_MAP_READ = 0x0004
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenFileMappingW.restype = ctypes.c_void_p
_kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
_kernel32.MapViewOfFile.restype = ctypes.c_void_p
_kernel32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
_kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_kernel32.GetTickCount64.restype = ctypes.c_uint64


def tick_ms() -> int:
    """Milliseconds since boot, the same clock the plugin stamps the heartbeat with."""
    return _kernel32.GetTickCount64()


class _SharedView:
    """A read/write view of an existing named file mapping. Unlike mmap(tagname=...) this never
    creates the mapping, so an app running as admin can't squat the plugin's name."""

    def __init__(self, name: str, size: int):
        self._handle = _kernel32.OpenFileMappingW(_FILE_MAP_READ | _FILE_MAP_WRITE, False, name)
        if not self._handle:
            raise ConnectionError(NOT_RUNNING)
        self._addr = _kernel32.MapViewOfFile(self._handle, _FILE_MAP_READ | _FILE_MAP_WRITE, 0, 0, size)
        if not self._addr:
            _kernel32.CloseHandle(self._handle)
            raise ConnectionError("the mic plugin's shared memory is too small")
        self.buf = (ctypes.c_char * size).from_address(self._addr)

    def close(self) -> None:
        if self._addr:
            self.buf = None
            _kernel32.UnmapViewOfFile(self._addr)
            _kernel32.CloseHandle(self._handle)
            self._addr = self._handle = None


class MicRing:
    """Producer side of the ring. Positions are total frames written/read since the ring was created."""

    def __init__(self, view: _SharedView):
        self._view = view
        self.buf = view.buf
        magic, version, _rate, channels, capacity, *_ = RING_HEADER.unpack_from(self.buf, 0)
        if magic != RING_MAGIC or version != RING_VERSION:
            raise ConnectionError("the mic plugin isn't running (or is a different version)")
        if channels != RING_CHANNELS or capacity == 0:
            raise ConnectionError(f"unsupported ring format: {channels} channels, {capacity} frames")
        self.capacity = capacity

    @classmethod
    def open(cls, name: str) -> "MicRing":
        probe = _SharedView(name, RING_HEADER_SIZE)  # just enough to read the header and learn the capacity
        try:
            capacity = RING_HEADER.unpack_from(probe.buf, 0)[4]
        finally:
            probe.close()
        if capacity == 0:
            raise ConnectionError(NOT_RUNNING)
        view = _SharedView(name, RING_HEADER_SIZE + capacity * RING_CHANNELS * 4)
        try:
            return cls(view)
        except ConnectionError:
            view.close()
            raise

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.buf, offset)[0]

    def _pos(self, offset: int) -> int:
        return struct.unpack_from("<Q", self.buf, offset)[0]

    def rate(self) -> int:
        """The mic's frame rate while the plugin is processing, 0 when it isn't."""
        return self._u32(RATE_OFFSET)

    def mic_running(self, now_ms: int | None = None) -> bool:
        if not self.rate():
            return False
        now_ms = tick_ms() if now_ms is None else now_ms
        return now_ms - self._pos(HEARTBEAT_OFFSET) < HEARTBEAT_TIMEOUT_MS

    def fill(self) -> int:
        return self._pos(WRITE_POS_OFFSET) - self._pos(READ_POS_OFFSET)

    def write(self, frames: np.ndarray) -> int:
        """Write as many frames as fit. Returns how many were written."""
        write_pos = self._pos(WRITE_POS_OFFSET)
        free = self.capacity - (write_pos - self._pos(READ_POS_OFFSET))
        count = max(0, min(len(frames), free))
        data = np.ascontiguousarray(frames[:count], dtype=np.float32)
        start = write_pos % self.capacity
        first = min(count, self.capacity - start)
        self._copy_in(start, data[:first])
        self._copy_in(0, data[first:])
        struct.pack_into("<Q", self.buf, WRITE_POS_OFFSET, write_pos + count)  # publish after data
        return count

    def _copy_in(self, frame_offset: int, data: np.ndarray) -> None:
        if len(data):
            at = RING_HEADER_SIZE + frame_offset * RING_CHANNELS * 4
            self.buf[at : at + data.nbytes] = data.tobytes()

    def close(self) -> None:
        self._view.close()


class StreamResampler:
    """Linear-interpolation resampler for a continuous stereo stream. It keeps its position between
    blocks so block edges don't click. Good enough for sound effects into a voice chat."""

    def __init__(self, src_rate: int, dst_rate: int):
        self.src_rate, self.dst_rate = src_rate, dst_rate
        self.step = src_rate / dst_rate  # source frames per output frame
        self._phase = 0.0                # position of the next output frame, relative to _prev
        self._prev = np.zeros((1, RING_CHANNELS), dtype=np.float32)

    def source_frames_for(self, out_frames: int) -> int:
        """How many source frames to feed process() to get about `out_frames` back."""
        return max(0, math.ceil(out_frames * self.step - self._phase))

    def process(self, block: np.ndarray) -> np.ndarray:
        if self.src_rate == self.dst_rate or not len(block):
            return block
        x = np.concatenate([self._prev, block.astype(np.float32, copy=False)])
        n = len(block)
        count = max(0, math.ceil((n - self._phase) / self.step))
        pos = self._phase + self.step * np.arange(count)
        i = pos.astype(np.int64)
        frac = (pos - i)[:, None].astype(np.float32)
        out = x[i] * (1 - frac) + x[i + 1] * frac
        self._phase += self.step * count - n
        self._prev = x[-1:].copy()
        return out.astype(np.float32, copy=False)


class PluginMicOutput:
    """Feeds the mic plugin's ring at the mic's own rate, keeping ~20 ms queued while something plays."""

    TICK = 0.005

    def __init__(self, mixer: Mixer, mic_id: str = "", ring_name: str | None = None):
        self.mixer = mixer
        self.mic_id = mic_id
        self.ring_name = ring_name or ring_name_for(mic_id)
        self.error = ""
        self._ring: MicRing | None = None
        self._resampler: StreamResampler | None = None
        self.mic_running = False  # an app is recording from the mic, so sounds are heard
        # Installed, but Windows only runs the plugin (and its ring) while some app has the mic open.
        self.waiting_for_mic = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._ring is not None

    def open(self) -> None:
        self.close()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mic-plugin-feed", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        if self._ring is not None:
            self._ring.close()
            self._ring = None
        self.mic_running = False

    def _drain(self) -> None:
        """Nobody is listening; play sounds into nothing so they don't pile up and play late."""
        self.mixer.render(int(ENGINE_RATE * self.TICK))

    def _run(self) -> None:
        next_connect = 0.0
        while not self._stop.is_set():
            if self._ring is None:
                if time.monotonic() >= next_connect:
                    try:
                        self._ring = MicRing.open(self.ring_name)
                        self.error = ""
                        self.waiting_for_mic = False
                    except ConnectionError as exc:
                        self._connect_failed(str(exc))
                        next_connect = time.monotonic() + 2.0
                if self._ring is None:
                    self._drain()
                    time.sleep(self.TICK)
                    continue
            try:
                self.feed_once()
            except (ValueError, OSError):
                self._ring.close()
                self._ring = None
                continue
            time.sleep(self.TICK)

    def _connect_failed(self, error: str) -> None:
        if error == NOT_RUNNING:
            installed = bool(self.mic_id) and has_plugin(read_fx(self.mic_id))
            self.waiting_for_mic = installed
            self.error = "" if installed else NOT_INSTALLED
        else:
            self.waiting_for_mic = False
            self.error = error

    def feed_once(self) -> None:
        ring = self._ring
        self.mic_running = ring.mic_running()
        if not self.mic_running:  # no app is recording from the mic right now
            self._resampler = None
            self._drain()
            return
        rate = ring.rate()
        if self._resampler is None or self._resampler.dst_rate != rate:
            self._resampler = StreamResampler(ENGINE_RATE, rate)
        if not self.mixer.active_keys():
            return
        need = rate // 50 - ring.fill()
        if need > 0:
            ring.write(self._resampler.process(self.mixer.render(self._resampler.source_frames_for(need))))
