# The mic plugin (SoundboardApo.dll)

How the app's sounds get into your real microphone the way Soundpad does it, with no virtual
cable. The DLL lives in `apo/`; the app side is `soundboard/audio/outputs.py` (audio) and
`soundboard/micplugin/` (installing it); the shared-memory protocol between them is
[mic-bridge.md](mic-bridge.md).

The plugin goes on **every mic once**, and each mic gets its own ring. Picking the mic your sounds
go into is just an app setting: the app writes into that mic's ring. No admin, no audio restart.

```
 Soundboard app (python, your user)               audiodg.exe (LocalService)
 ┌──────────────────────────────────────┐        ┌──────────────────────────────────────────┐
 │ mixer 48k ─► resample to mic rate ───┼─write─►│ Global\SoundboardMicRing.{mic id}         │
 └──────────────────────────────────────┘        │          │ read                           │
                                                 │          ▼                                │
 real mic (Yeti) ─► driver ─► [vendor effects] ──► SoundboardApo::APOProcess: mic + sounds ──┼─► Discord, games
                                                 └──────────────────────────────────────────┘
```

## Quick start

```
apo\build.ps1                               # builds apo\build\SoundboardApo.dll, runs the native tests
soundboard --admin install [MIC_ID ...]     # as admin: register it and put it on these mics (default: all)
soundboard --admin add MIC_ID               # as admin: one more mic
soundboard --admin uninstall                # as admin: every mic back exactly as it was
```

(From source, `soundboard` is `.venv\Scripts\python -m soundboard`.) The installer runs
`install` and its uninstaller runs `uninstall`. In the app, Settings → Into my mic → Mic plugin →
**Microphone** switches mics instantly; for a mic without the plugin (plugged in later) **Add the
plugin to this mic** runs `add` elevated: one Windows prompt, and audio cuts out for a second while
Windows Audio restarts. **Remove the plugin from every mic** runs `uninstall`.

Then open Discord's mic test and play a sound.
The plugin logs to `C:\ProgramData\Soundboard\apo.log` (also visible in Sysinternals DebugView).

## What's in apo/

| File | What it does |
|------|--------------|
| `src/apo.cpp` | The COM object, its class factory, and the DLL exports and registration |
| `src/ring.h` | Ring layout, the owner claim, the real-time reader and the stereo-to-mic mix. Free of Windows APIs so it's unit-tested |
| `src/log.h` | File + debugger logging (never used on the audio thread) |
| `tests/ring_test.cpp` | Ring reader, wrap-around, backlog skip, torn positions, owner claim, channel mixing |
| `tests/com_test.cpp` | Drives the object like audiodg does: aggregated creation, Initialize, LockForProcess with a real media type, APOProcess, Unlock, refcounts back to zero |
| `build.ps1` | MSVC build (Build Tools 2022 + Windows SDK, no ATL needed), then both tests |

## 1. COM object, and the aggregation bug fixed

The spike silenced the mic because audiodg creates the APO **aggregated**
(`CreateInstance(pUnkOuter, IID_IUnknown)`) and the spike refused with `CLASS_E_NOAGGREGATION`.
`SoundboardApo` has a nested non-delegating `Inner` IUnknown that owns the reference count and
answers `QueryInterface`. Every other interface's `IUnknown` methods forward to the outer object
(or to `Inner` when not aggregated). The factory follows the COM rule: when aggregated, only
`IID_IUnknown` may be requested.

Interfaces: `IAudioProcessingObject`, `IAudioProcessingObjectRT`,
`IAudioProcessingObjectConfiguration` (from the SDK's `CBaseAudioProcessingObject`, which also
validates formats: 32-bit float, any rate, any channel count), `IAudioSystemEffects` and
`IAudioSystemEffects2` (an empty effects list). Registered with `APO_FLAG_DEFAULT | APO_FLAG_INPLACE`
for the default processing mode.

## 2. Lifecycle

| Call | What happens |
|------|--------------|
| `Initialize` | Reads `APOInitSystemEffects2/3`. If `InitializeForDiscoveryOnly`, does nothing else. Otherwise reads the mic's endpoint GUID (`PKEY_AudioEndpoint_GUID` from the endpoint property store) and creates (or reopens) that mic's ring. Any failure means pass-through, never an error. |
| `LockForProcess` | Base-class validation, then the mic's rate and channel count. Preallocates the scratch buffer. Takes ring ownership, drops stale audio and publishes the rate. |
| `APOProcess` | Heartbeat, read, mix, set `BUFFER_VALID` if anything was added (zeroing a `BUFFER_SILENT` input first). Otherwise passes the flags through. |
| `UnlockForProcess` | Sets rate to 0 and gives up ownership, so another instance or a later lock can take it. |
| `Reset` | Drops queued audio. |

Several instances can exist for one mic (one per processing mode), all in one audiodg. Only one
reads that mic's ring: the `owner` field in the header, `(pid << 32) | instance`, claimed with a
compare-and-swap. An owner with another pid is a dead audiodg's, so it's taken over.

## 3. Resampling is in the app

The plugin never resamples. It publishes the mic's rate in the header and the app's
`StreamResampler` converts the 48 kHz mix to it, keeping its position between blocks so block
edges don't click. The ring stays stereo, so a rate change never changes the layout. The plugin
only maps stereo to the mic's channels: mono gets (L+R)/2, anything else gets L and R in the first
two channels.

The app also uses the heartbeat: when nobody is recording from the mic, audiodg stops calling
the plugin, and the app plays sounds into nothing instead of queuing them to burst out later.

## 4. Real-time rules (APOProcess)

No locks, allocation, logging, COM calls or exceptions. Positions are read and written through
`std::atomic_ref` with acquire/release ordering. The writer is Python, so a write position that
looks torn (behind the reader, or more than capacity ahead) reads nothing that period. A backlog
over 100 ms jumps to the newest 20 ms.

## 5. Installing on mics

`soundboard/micplugin/admin.py`, run elevated as `soundboard --admin install|add|uninstall`:

1. Stops Windows Audio. From source, copies the DLL to `C:\Program Files\Soundboard\` (audiodg
   can't read a user's folders); the installed app ships it next to `Soundboard.exe`. Creates the
   log folder with LocalService write access, then `regsvr32` (COM keys with `ThreadingModel=Both`,
   plus `RegisterAPO`).
2. For each mic: backs up the `FxProperties` values it will touch to
   `HKLM\SOFTWARE\Soundboard\Apo\<id>`, only once, so a reinstall doesn't back up our own values.
   Mics without `FxProperties` (some virtual ones) are skipped.
3. Attaches to the endpoint-effect slot, keeping whatever was there (`micplugin/fx.py`, pure and tested):
   - the driver uses a composite chain (`{d04e05a6-…},15`, e.g. the Realtek mics here): put ours first in it
   - a single vendor effect in `{d04e05a6-…},7`: make a composite chain of ours + it
   - nothing (the Yeti): `{d04e05a6-…},7` = our CLSID
   - and make sure `{d3993a3f-…},7` lists the default mode
4. Restarts Windows Audio. That happens even if an earlier step failed.

Admins only have **SetValue + ReadKey** on `FxProperties`, so it's opened with exactly those
rights (deleting a value only needs SetValue). Failures exit with code 1 and the reason in
`C:\ProgramData\Soundboard\admin-error.txt`, which the app shows.

`uninstall` restores every backed-up mic value for value, removes us from any mic that still lists
us, unregisters, and (from source) deletes the copied DLL. It works even if the DLL is missing.
Backups written by the old PowerShell installer use the same format and still restore.

## 6. Testing on the real mic

1. Install. Open Sound settings → Input → the Yeti and watch the level meter: your voice
   must sound normal. `apo.log` should show `CreateInstance: aggregated=1 -> 0x00000000`,
   `OpenRing: created Global\SoundboardMicRing.{552c99d7-…}` and `LockForProcess: 48000 Hz, … reading the ring`.
2. Start the app (mic output: mic plugin): the status should stop saying the plugin isn't running.
3. Discord → Voice → mic test, play a sound: you hear it. Talk over it: both.
4. Close Discord, play a sound, reopen it: no old sound bursts out.
5. Change the Yeti's format (Sound settings → Advanced, e.g. 44.1 kHz): sounds keep the right pitch.
6. `Restart-Service Audiosrv -Force` while the app runs: it reconnects by itself.

If the mic ever goes silent, run `soundboard --admin uninstall` as admin (or turn off "Audio enhancements" for that mic,
which disables all effects).

## Known limits

- Sounds go into one mic at a time (the one picked in Settings); the plugin on the others passes
  their audio through untouched.
- Apps that capture in exclusive mode or raw mode bypass all effects, Soundpad included.
- Driver updates or Windows feature updates can rewrite `FxProperties`; reinstall if the
  sounds stop and the log shows no `Initialize`.
- The DLL is installed to Program Files. Whether audiodg loads it from there is confirmed by
  step 1 of the test; if not, System32 (where Soundpad puts its DLL) is the fallback.
