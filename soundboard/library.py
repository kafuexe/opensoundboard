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
_RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


@dataclass
class Sound:
    id: str
    name: str
    file: str  # file name inside sounds_dir()
    hotkey: str = ""
    volume: float = 1.0  # per-sound gain, 0..1.5
    source: str = "file"  # file | soundbuttonsworld | youtube
    origin_id: str = ""  # e.g. the site's file name, so we can show "Added" in search results
    folder: str = ""  # "" = unsorted

    @property
    def path(self) -> Path:
        return paths.sounds_dir() / self.file


@dataclass
class Library:
    sounds: list[Sound] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)  # display order
    index_path: Path = field(default_factory=paths.library_file)

    @classmethod
    def load(cls, index_path: Path | None = None) -> "Library":
        index_path = index_path or paths.library_file()
        lib = cls(index_path=index_path)
        if index_path.exists():
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            known = Sound.__dataclass_fields__.keys()
            lib.sounds = [Sound(**{k: v for k, v in item.items() if k in known}) for item in raw.get("sounds", [])]
            lib.folders = [f for f in raw.get("folders", []) if isinstance(f, str) and f]
            for sound in lib.sounds:  # a folder missing from the list (hand-edited file) shouldn't hide sounds
                if sound.folder and sound.folder not in lib.folders:
                    lib.folders.append(sound.folder)
            if lib._name_files_after_sounds():
                lib.save()
        return lib

    def save(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"folders": self.folders, "sounds": [asdict(s) for s in self.sounds]}, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def get(self, sound_id: str) -> Sound | None:
        return next((s for s in self.sounds if s.id == sound_id), None)

    def add_file(self, source: Path, name: str | None = None, origin: str = "file", move: bool = False,
                 origin_id: str = "", folder: str = "") -> Sound:
        """Copy (or move) an audio file into the library and index it."""
        source = Path(source)
        if source.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"{source.name} is not a supported audio file")
        name = clean_name(name or source.stem)
        stored = self._free_file_name(name, source.suffix.lower())
        (shutil.move if move else shutil.copy2)(str(source), str(paths.sounds_dir() / stored))
        sound = Sound(id=uuid.uuid4().hex[:12], name=name, file=stored, source=origin, origin_id=origin_id,
                      folder=folder if folder in self.folders else "")
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
        if "folder" in changes and changes["folder"] not in self.folders:
            changes["folder"] = ""
        if changes.get("hotkey"):
            # A hotkey belongs to one sound only; taking it clears the previous owner.
            for other in self.sounds:
                if other is not sound and other.hotkey == changes["hotkey"]:
                    other.hotkey = ""
        for key, value in changes.items():
            setattr(sound, key, value)
        if "name" in changes:
            self._rename_file(sound)
        self.save()
        return sound

    def move(self, sound_id: str, new_index: int) -> None:
        sound = self.get(sound_id)
        if sound is None:
            return
        self.sounds.remove(sound)
        self.sounds.insert(max(0, min(new_index, len(self.sounds))), sound)
        self.save()

    def search(self, query: str, folder: str | None = None) -> list[Sound]:
        """folder=None searches everything; "" is unsorted; otherwise one folder."""
        words = query.lower().split()
        return [s for s in self.sounds
                if (folder is None or s.folder == folder)
                and all(w in f"{s.name} {s.hotkey}".lower() for w in words)]

    # --- folders -------------------------------------------------------------------------------
    def add_folder(self, name: str) -> str:
        name = self._check_folder_name(name)
        self.folders.append(name)
        self.save()
        return name

    def rename_folder(self, old: str, new: str) -> str:
        if old not in self.folders:
            raise KeyError(old)
        new = clean_name(new)
        if new == old:
            return old
        new = self._check_folder_name(new)
        self.folders[self.folders.index(old)] = new
        for sound in self.sounds:
            if sound.folder == old:
                sound.folder = new
        self.save()
        return new

    def delete_folder(self, name: str) -> int:
        """Remove the folder; its sounds become unsorted. Returns how many moved."""
        if name not in self.folders:
            return 0
        self.folders.remove(name)
        moved = 0
        for sound in self.sounds:
            if sound.folder == name:
                sound.folder = ""
                moved += 1
        self.save()
        return moved

    def folder_count(self, folder: str | None) -> int:
        return len(self.sounds) if folder is None else sum(1 for s in self.sounds if s.folder == folder)

    def _check_folder_name(self, name: str) -> str:
        name = clean_name(name)
        if not name:
            raise ValueError("Give the folder a name")
        if name.lower() in {f.lower() for f in self.folders} or name.lower() in {"all", "unsorted"}:
            raise ValueError(f"There's already a folder called “{name}”")
        return name

    def has_origin(self, origin: str, origin_id: str) -> bool:
        return any(s.source == origin and s.origin_id == origin_id for s in self.sounds)

    # --- file names ----------------------------------------------------------------------------
    def _free_file_name(self, name: str, ext: str, current: str = "") -> str:
        """"<name><ext>", or "<name> 1<ext>", "<name> 2<ext>"... when that's taken. `current` is the
        sound's own file, which doesn't count as taken (renaming to the same name keeps it)."""
        base = safe_file_stem(name)
        taken = {s.file.lower() for s in self.sounds if s.file.lower() != current.lower()}
        candidate, n = f"{base}{ext}", 0
        while candidate.lower() in taken or (
                candidate.lower() != current.lower() and (paths.sounds_dir() / candidate).exists()):
            n += 1
            candidate = f"{base} {n}{ext}"
        return candidate

    def _rename_file(self, sound: Sound) -> bool:
        """Rename the sound's file to match its name. Keeps the old file name if the rename fails
        (e.g. the file is open elsewhere). Returns whether the file name changed."""
        wanted = self._free_file_name(sound.name, Path(sound.file).suffix.lower(), current=sound.file)
        if wanted == sound.file:
            return False
        try:
            sound.path.rename(paths.sounds_dir() / wanted)
        except OSError:
            return False
        sound.file = wanted
        return True

    def _name_files_after_sounds(self) -> bool:
        """Older versions stored files as "<id>.mp3"; give those their sound's name."""
        changed = False
        for sound in self.sounds:
            if Path(sound.file).stem == sound.id and sound.path.exists():
                changed |= self._rename_file(sound)
        return changed


def safe_file_stem(name: str) -> str:
    """A Windows-safe file name (without extension) that still reads like the sound's name."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    stem = re.sub(r"\s+", " ", stem).strip(" .")[:60].rstrip(" .")
    if not stem or stem.lower() in _RESERVED_NAMES:
        stem = f"{stem} sound".strip()
    return stem


def clean_name(name: str) -> str:
    name = re.sub(r"[_]+", " ", name or "")
    return re.sub(r"\s+", " ", name).strip()[:80]
