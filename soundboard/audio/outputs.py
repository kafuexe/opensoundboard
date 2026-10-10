"""Audio outputs. Each owns a Mixer and pulls from it on its own clock.

- DeviceOutput: a speaker/headphone/virtual-cable device via sounddevice (WASAPI).
- PluginMicOutput: the shared-memory ring read by the Soundboard mic plugin (see docs/mic-bridge.md).
"""
from __future__ import annotations

import mmap
import struct
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

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
# Layout of the shared-memory ring (little endian). The plugin creates it; the app writes into it.
RING_NAME = "Global\\SoundboardMicRing"
RING_MAGIC = 0x524D4253  # "SBMR"
RING_VERSION = 1
RING_HEADER = struct.Struct("<IIIIIIQQ")  # magic, version, rate, channels, capacity, reserved, write, read
RING_HEADER_SIZE = 64
WRITE_POS_OFFSET = 24
READ_POS_OFFSET = 32


class MicRing:
    """Producer side of the ring. Positions are total frames written/read since the ring was created."""

    def __init__(self, buf: mmap.mmap):
        self.buf = buf
        magic, version, rate, channels, capacity, _r, _w, _rd = RING_HEADER.unpack_from(buf, 0)
        if magic != RING_MAGIC or version != RING_VERSION:
            raise ConnectionError("the mic plugin isn't running")
        if channels != 2 or rate != ENGINE_RATE:
            raise ConnectionError(f"unsupported ring format {rate} Hz x{channels}")
        self.capacity = capacity

    @classmethod
    def open(cls, name: str = RING_NAME) -> "MicRing":
        size = RING_HEADER_SIZE + 4  # just enough to read the header and learn the capacity
        try:
            probe = mmap.mmap(-1, size, tagname=name, access=mmap.ACCESS_READ)
        except OSError as exc:
            raise ConnectionError("the mic plugin isn't running") from exc
        try:
            capacity = RING_HEADER.unpack_from(probe, 0)[4]
        finally:
            probe.close()
        if capacity == 0:
            raise ConnectionError("the mic plugin isn't running")
        return cls(mmap.mmap(-1, RING_HEADER_SIZE + capacity * 8, tagname=name))

    def _pos(self, offset: int) -> int:
        return struct.unpack_from("<Q", self.buf, offset)[0]

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
            at = RING_HEADER_SIZE + frame_offset * 8
            self.buf[at : at + data.nbytes] = data.tobytes()

    def close(self) -> None:
        self.buf.close()


class PluginMicOutput:
    """Feeds the mic plugin's ring, keeping ~20 ms queued while something plays."""

    TARGET_FILL = ENGINE_RATE // 50
    TICK = 0.005

    def __init__(self, mixer: Mixer, ring_name: str = RING_NAME):
        self.mixer = mixer
        self.ring_name = ring_name
        self.error = ""
        self._ring: MicRing | None = None
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

    def _run(self) -> None:
        next_connect = 0.0
        while not self._stop.is_set():
            if self._ring is None:
                if time.monotonic() >= next_connect:
                    try:
                        self._ring = MicRing.open(self.ring_name)
                        self.error = ""
                    except ConnectionError as exc:
                        self.error = str(exc)
                        next_connect = time.monotonic() + 2.0
                if self._ring is None:
                    # Nobody is listening; drain so sounds don't pile up and play late once connected.
                    self.mixer.render(int(ENGINE_RATE * self.TICK))
                    time.sleep(self.TICK)
                    continue
            try:
                if self.mixer.active_keys():
                    need = self.TARGET_FILL - self._ring.fill()
                    if need > 0:
                        self._ring.write(self.mixer.render(need))
            except (ValueError, OSError):
                self._ring.close()
                self._ring = None
                continue
            time.sleep(self.TICK)
