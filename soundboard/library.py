"""The user's sound library: a JSON index plus audio files copied into the app's data folder."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus", ".aac", ".wma"}


@dataclass
class Sound:
    id: str
    name: str
    file: str  # file name inside sounds_dir()
    hotkey: str = ""
    volume: float = 1.0  # per-sound gain, 0..1.5
    source: str = "file"  # file | soundbuttonsworld | youtube
    origin_id: str = ""  # e.g. the site's file name, so we can show "Added" in search results

    @property
    def path(self) -> Path:
        return paths.sounds_dir() / self.file


@dataclass
class Library:
    sounds: list[Sound] = field(default_factory=list)
    index_path: Path = field(default_factory=paths.library_file)

    @classmethod
    def load(cls, index_path: Path | None = None) -> "Library":
        index_path = index_path or paths.library_file()
        lib = cls(index_path=index_path)
        if index_path.exists():
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            known = Sound.__dataclass_fields__.keys()
            lib.sounds = [Sound(**{k: v for k, v in item.items() if k in known}) for item in raw.get("sounds", [])]
        return lib

    def save(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sounds": [asdict(s) for s in self.sounds]}, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def get(self, sound_id: str) -> Sound | None:
        return next((s for s in self.sounds if s.id == sound_id), None)

    def add_file(self, source: Path, name: str | None = None, origin: str = "file", move: bool = False,
                 origin_id: str = "") -> Sound:
        """Copy (or move) an audio file into the library and index it."""
        source = Path(source)
        if source.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"{source.name} is not a supported audio file")
        sound_id = uuid.uuid4().hex[:12]
        stored = f"{sound_id}{source.suffix.lower()}"
        (shutil.move if move else shutil.copy2)(str(source), str(paths.sounds_dir() / stored))
        sound = Sound(id=sound_id, name=clean_name(name or source.stem), file=stored, source=origin, origin_id=origin_id)
        self.sounds.append(sound)
        self.save()
        return sound

    def remove(self, sound_id: str) -> None:
        sound = self.get(sound_id)
        if not sound:
            return
        self.sounds.remove(sound)
        sound.path.unlink(missing_ok=True)
        self.save()

    def update(self, sound_id: str, **changes) -> Sound:
        sound = self.get(sound_id)
        if sound is None:
            raise KeyError(sound_id)
        if "name" in changes:
            changes["name"] = clean_name(changes["name"]) or sound.name
        if changes.get("hotkey"):
            # A hotkey belongs to one sound only; taking it clears the previous owner.
            for other in self.sounds:
                if other is not sound and other.hotkey == changes["hotkey"]:
                    other.hotkey = ""
        for key, value in changes.items():
            setattr(sound, key, value)
        self.save()
        return sound

    def move(self, sound_id: str, new_index: int) -> None:
        sound = self.get(sound_id)
        if sound is None:
            return
        self.sounds.remove(sound)
        self.sounds.insert(max(0, min(new_index, len(self.sounds))), sound)
        self.save()

    def search(self, query: str) -> list[Sound]:
        words = query.lower().split()
        if not words:
            return list(self.sounds)
        return [s for s in self.sounds if all(w in f"{s.name} {s.hotkey}".lower() for w in words)]

    def has_origin(self, origin: str, origin_id: str) -> bool:
        return any(s.source == origin and s.origin_id == origin_id for s in self.sounds)


def clean_name(name: str) -> str:
    name = re.sub(r"[_]+", " ", name or "")
    return re.sub(r"\s+", " ", name).strip()[:80]
