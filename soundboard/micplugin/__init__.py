"""The Soundboard mic plugin (apo/, SoundboardApo.dll): which mics have it, and putting it on or off.

- mics.py: read-only, runs as the normal user (listing mics, ring names).
- fx.py: the pure rules for editing a mic's effect settings, tested without a registry.
- admin.py: the steps that need admin, run as `soundboard --admin ...` (elevated by the app or by
  the installer).
"""

CLSID = "{6C2825A3-7231-43EA-8D9B-A3B5BCF81B06}"
RING_PREFIX = "Global\\SoundboardMicRing"


def ring_name(mic_id: str) -> str:
    """The shared-memory ring the plugin on this mic reads from (see docs/mic-bridge.md)."""
    return f"{RING_PREFIX}.{mic_id.lower()}"
