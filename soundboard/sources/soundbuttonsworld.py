"""Client for soundbuttonsworld.com's public JSON API (the same calls its website makes)."""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

BASE = "https://soundbuttonsworld.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Soundboard/1.0"}
TIMEOUT = 15
_SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+\.(mp3|wav|ogg|m4a)$")


@dataclass(frozen=True)
class RemoteSound:
    id: int
    name: str
    file_name: str
    category: str = ""

    @property
    def audio_url(self) -> str:
        return f"{BASE}/uploads/{self.file_name}"


@dataclass(frozen=True)
class Page:
    sounds: list[RemoteSound]
    total: int | None  # trends/new don't report a total
    page: int
    page_size: int

    @property
    def has_more(self) -> bool:
        if self.total is None:
            return len(self.sounds) == self.page_size
        return self.page * self.page_size < self.total


def parse_page(payload: dict, page: int, page_size: int) -> Page:
    sounds = []
    for item in payload.get("data") or []:
        file_name = str(item.get("fileName") or "")
        if not _SAFE_FILE.match(file_name):
            continue  # skip anything that isn't a plain audio file name
        sounds.append(RemoteSound(
            id=int(item.get("id") or 0),
            name=" ".join(str(item.get("name") or file_name).split()),
            file_name=file_name,
            category=str(item.get("categoryName") or "").replace(" Soundboard", ""),
        ))
    total = payload.get("total")
    return Page(sounds, int(total) if total is not None else None, page, page_size)


class SoundButtonsWorld:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, path: str, params: dict) -> dict:
        resp = self.session.get(f"{BASE}/api/{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str, page: int = 1, page_size: int = 30) -> Page:
        payload = self._get("memes/search", {"page": page, "pageSize": page_size, "q": query.strip()})
        return parse_page(payload, page, page_size)

    def trending(self, page: int = 1, page_size: int = 30) -> Page:
        return parse_page(self._get("memes/trends", {"page": page, "pageSize": page_size}), page, page_size)

    def newest(self, page: int = 1, page_size: int = 30) -> Page:
        return parse_page(self._get("memes/new", {"page": page, "pageSize": page_size}), page, page_size)

    def download(self, sound: RemoteSound, dest_dir: Path | None = None) -> Path:
        """Download to a temp (or given) folder and return the file path."""
        dest_dir = Path(dest_dir or tempfile.mkdtemp(prefix="sbw-"))
        dest = dest_dir / sound.file_name
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        with self.session.get(sound.audio_url, timeout=TIMEOUT, stream=True) as resp:
            resp.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(64 * 1024):
                    fh.write(chunk)
        tmp.replace(dest)
        return dest
