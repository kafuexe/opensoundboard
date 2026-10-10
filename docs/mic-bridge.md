# Mic bridge: how the app hands audio to the mic plugin

The mic plugin is a Windows Audio Processing Object (APO) attached to a capture endpoint (the
user's real microphone) in the endpoint-effect slot.
It mixes whatever the app queues into the mic signal, so Discord and games hear the sounds with
no virtual cable.

The app and the plugin share one block of memory: a single-producer / single-consumer ring.

## Ownership

- **The plugin creates it**, because it runs in `audiodg.exe` as LocalService, which may create
  `Global\` objects. Name: `Global\SoundboardMicRing`. It must use a security descriptor that
  lets the interactive user open it for read/write.
- **The app opens it** (`soundboard/audio/outputs.py`, `MicRing.open`). If it isn't there, or the
  header is wrong, the app shows "The mic plugin isn't running" and retries every 2 seconds.

## Layout (little endian)

| Offset | Type   | Field          | Written by |
|-------:|--------|----------------|------------|
| 0      | u32    | magic `0x524D4253` ("SBMR") | plugin, once |
| 4      | u32    | version = 1    | plugin, once |
| 8      | u32    | sample rate = 48000 | plugin, once |
| 12     | u32    | channels = 2   | plugin, once |
| 16     | u32    | capacity, in frames | plugin, once |
| 20     | u32    | reserved       | |
| 24     | u64    | write position (total frames ever written) | app |
| 32     | u64    | read position (total frames ever read) | plugin |
| 40–63  |        | reserved       | |
| 64     | f32[capacity × 2] | interleaved stereo samples | app |

Frame `n` lives at index `n % capacity`. Fill = write − read; free = capacity − fill.

## Rules

- **App:** writes samples first, then publishes the new write position. It keeps about 20 ms
  queued while something plays and writes nothing when idle. It never writes past free space.
- **Plugin (in `APOProcess`):** reads `min(fill, frames needed)`, converts to the mic's channel count
  and sample rate, adds the samples to the mic buffer, then advances the read position. If the
  ring is empty it passes the mic through untouched. It must never block, allocate, or take locks
  on the audio thread.
- Positions are 64-bit and only grow, so they never wrap in practice.

## What the spike taught us (2026-10-10)

- Windows 11 25H2 loads an unsigned APO DLL into `audiodg.exe`.
- Admins only have *set value* + *read* on `MMDevices\...\FxProperties`; open the key with exactly
  those rights (`RegistryKeyPermissionCheck.ReadWriteSubTree` + `SetValue, ReadKey` in .NET).
- Endpoint effect slot: `{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7` = plugin CLSID (REG_SZ) and
  `{d3993a3f-99c2-4402-b5ec-a92a0367664b},7` = `{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}` (REG_MULTI_SZ,
  default processing mode).
- **The audio engine creates the APO through COM aggregation** (`CreateInstance` with an outer
  `IUnknown`, asking for `IID_IUnknown`). Refusing with `CLASS_E_NOAGGREGATION` silences the mic.
  The plugin must implement a non-delegating inner `IUnknown`. This is the next thing to fix.
