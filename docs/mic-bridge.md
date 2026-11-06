# Mic bridge: how the app hands audio to the mic plugin

The mic plugin (`apo/`, built as `SoundboardApo.dll`) is a Windows Audio Processing Object (APO)
attached to a capture endpoint (the user's real microphone) in the endpoint-effect slot. It mixes whatever the app queues into the mic signal, so Discord
and games hear the sounds with no virtual cable.

The app and the plugin share one block of memory: a single-producer / single-consumer ring.
Protocol version 2. The ring is always stereo, at the **mic's** frame rate: the app resamples, and
the plugin only maps stereo to the mic's channel layout.

## Ownership

- **The plugin on each mic creates that mic's ring**, because it runs in `audiodg.exe` as
  LocalService, which may create `Global\` objects. Name: `Global\SoundboardMicRing.{endpoint guid}`,
  lowercase, e.g. `Global\SoundboardMicRing.{552c99d7-3a86-46fd-89ba-6e88c24fe4e8}`. The app writes
  into the ring of the mic picked in Settings, so switching mics needs no admin. Security: System, LocalService and admins
  full access; the interactive user read/write (`D:(A;;GA;;;SY)(A;;GA;;;LS)(A;;GA;;;BA)(A;;GRGW;;;IU)`).
- **The app opens it** (`soundboard/audio/outputs.py`, `MicRing.open`) with `OpenFileMappingW`,
  so it never creates it by accident. If it isn't there, or the header is wrong, the app shows
  "the mic plugin isn't running" and retries every 2 seconds.
- If the app keeps the ring open across an audiodg restart, the new plugin reuses it when the
  layout matches.

## Layout (little endian)

| Offset | Type   | Field          | Written by |
|-------:|--------|----------------|------------|
| 0      | u32    | magic `0x524D4253` ("SBMR"), written last at creation | plugin |
| 4      | u32    | version = 2    | plugin, once |
| 8      | u32    | the mic's frame rate while processing, **0 when the mic isn't running** | plugin |
| 12     | u32    | channels = 2   | plugin, once |
| 16     | u32    | capacity, in frames (96000) | plugin, once |
| 20     | u32    | consumer: pid of the audiodg reading the ring, 0 = nobody (informational) | plugin |
| 24     | u64    | write position (total frames ever written) | app |
| 32     | u64    | read position (total frames ever read) | plugin |
| 40     | u64    | heartbeat: `GetTickCount64()` at the last audio period | plugin |
| 48     | u64    | owner: `(pid << 32) \| instance` of the plugin instance reading, 0 = nobody | plugin |
| 56–63  |        | reserved       | |
| 64     | f32[capacity × 2] | interleaved stereo samples | app |

Frame `n` lives at index `n % capacity`. Fill = write − read; free = capacity − fill.

## Rules

- **App:** treats the mic as running only while `rate != 0` and the heartbeat is under 250 ms old.
  While it isn't, it plays sounds into nothing, so they don't pile up and burst out when Discord
  opens the mic. While it is, it resamples its 48 kHz mix to `rate` and keeps about 20 ms queued.
  It writes samples first, then publishes the new write position, and never writes past free space.
- **Plugin, when processing starts (`LockForProcess`):** claims `owner`, sets read = write
  (drops stale audio), publishes `rate`. **When it stops (`UnlockForProcess`):** `rate = 0`, frees the slot.
- **Plugin, each period (`APOProcess`):** stamps the heartbeat, reads `min(fill, frames)`, adds the
  samples to the mic buffer (mono mic: (L+R)/2; otherwise L and R into the first two channels),
  then advances the read position. A fill over 100 ms skips ahead to the newest 20 ms. An empty ring
  leaves the mic untouched. A write position that looks torn (behind the reader or more than
  capacity ahead) reads nothing that period. No locks, allocation or I/O on that thread.
- Only one plugin instance per mic reads (the `owner` compare-and-swap; an owner from another
  pid belongs to a dead audiodg and is taken over); other instances pass the mic through.
- Positions are 64-bit and only grow, so they never wrap in practice.

## Windows details the plugin relies on

- Windows 11 25H2 loads an unsigned APO DLL into `audiodg.exe`.
- Admins only have *set value* + *read* on `MMDevices\...\FxProperties`; open the key with exactly
  those rights (`RegistryKeyPermissionCheck.ReadWriteSubTree` + `SetValue, ReadKey` in .NET).
- Endpoint effect slot: `{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7` = plugin CLSID (REG_SZ) and
  `{d3993a3f-99c2-4402-b5ec-a92a0367664b},7` = `{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}` (REG_MULTI_SZ,
  default processing mode).
- **The audio engine creates the APO through COM aggregation** (`CreateInstance` with an outer
  `IUnknown`, asking for `IID_IUnknown`). Refusing with `CLASS_E_NOAGGREGATION` silences the mic.
  The plugin implements a non-delegating inner `IUnknown` (see dll-spec.md, section 1).
