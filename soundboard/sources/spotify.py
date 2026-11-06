"""Add songs from Spotify links (tracks, albums, playlists).

Spotify doesn't let anyone download its audio. Like spotDL, we read each song's title, artists and
length from Spotify's public embed page (no account or API key), find the same song on YouTube,
and download that with the YouTube source. The length is what picks the right upload: a live
version, a remix or a ten-hour loop is a different length.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

import requests

from . import youtube
from .cancel import CancelToken

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130 Safari/537.36"}
TIMEOUT = 20
_LINK = re.compile(r"(?:open\.spotify\.com/(?:intl-[\w-]+/)?|spotify:)(track|album|playlist)[/:]([A-Za-z0-9]{22})")
# Words that mean "a different recording" unless the Spotify title has them too.
_OTHER_VERSION = ("live", "cover", "remix", "karaoke", "instrumental", "8d", "slowed", "sped up", "nightcore",
                  "reverb", "1 hour", "10 hours", "loop", "reaction", "tutorial")


@dataclass(frozen=True)
class SpotifyTrack:
    title: str
    artists: str  # "Pitbull, TJR"
    seconds: float

    @property
    def label(self) -> str:
        return f"{self.artists} – {self.title}" if self.artists else self.title


@dataclass(frozen=True)
class SpotifyLink:
    kind: str  # track | album | playlist
    name: str
    tracks: list[SpotifyTrack]


def parse_link(text: str) -> tuple[str, str] | None:
    """(kind, id) for a Spotify track/album/playlist link or URI, else None."""
    m = _LINK.search(text.strip())
    return (m.group(1), m.group(2)) if m else None


def looks_like_spotify(text: str) -> bool:
    return parse_link(text) is not None


def fetch(url: str) -> SpotifyLink:
    """What a link points to. Raises ValueError for links that aren't Spotify tracks/albums/playlists."""
    parsed = parse_link(url)
    if not parsed:
        raise ValueError("That isn't a Spotify track, album or playlist link")
    kind, spotify_id = parsed
    resp = requests.get(f"https://open.spotify.com/embed/{kind}/{spotify_id}", headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code == 404:
        raise ValueError("Spotify says that link doesn't exist (or it's private)")
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return parse_embed(resp.text, kind)


def parse_embed(html: str, kind: str) -> SpotifyLink:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("Couldn't read that Spotify page (Spotify may have changed it)")
    entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    name = entity.get("name") or entity.get("title") or "Spotify"
    if kind == "track":
        artists = ", ".join(a.get("name", "") for a in entity.get("artists") or [])
        tracks = [SpotifyTrack(name, artists, (entity.get("duration") or 0) / 1000)]
    else:
        tracks = [SpotifyTrack(item.get("title", ""), _clean(item.get("subtitle", "")), (item.get("duration") or 0) / 1000)
                  for item in entity.get("trackList") or [] if item.get("title")]
    if not tracks:
        raise ValueError("That Spotify link has no songs in it")
    return SpotifyLink(kind, name, tracks)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


_HARMLESS = re.compile(r"^(official|audio|video|music|lyrics?|visuali[sz]er|animated|hd|hq|4k|remaster(ed)?|explicit|"
                       r"clean|\d{4}|ft\.?|feat\.?|featuring|with|and|&|-|,)$")


def _foreign_qualifier(track: SpotifyTrack, title: str) -> bool:
    """A bracketed note on the upload, like "(Pianoforte)" or "[Originally Performed By ...]", that the
    Spotify title doesn't have: usually a different recording."""
    known = set(re.findall(r"[\w']+", f"{track.title} {track.artists}".lower()))
    for note in re.findall(r"[(\[]([^)\]]+)[)\]]", title.lower()):
        words = re.findall(r"[\w'.&-]+", note)
        if any(not _HARMLESS.match(w) and w not in known for w in words):
            return True
    return False


def score(track: SpotifyTrack, title: str, channel: str, seconds: float | None) -> float:
    """How likely a YouTube result is this song; higher is better."""
    t, c = title.lower(), (channel or "").lower()
    s = 0.0
    if seconds and track.seconds:
        s -= 2 * abs(seconds - track.seconds)
        if abs(seconds - track.seconds) > 30:
            s -= 100
    for word in (*_OTHER_VERSION, "originally performed", "made famous", "in the style of", "tribute", "acoustic",
                 "piano"):
        if word in t and word not in track.title.lower():
            s -= 40
    if _foreign_qualifier(track, title):
        s -= 40
    first_artist = track.artists.split(",")[0].strip().lower()
    if first_artist and c.replace("vevo", "").replace(" ", "") == first_artist.replace(" ", ""):
        s += 20  # the artist's own channel
    if c.endswith("- topic") or "official audio" in t or "provided to youtube" in t:
        s += 10
    if re.sub(r"\s*\(.*?\)", "", track.title).lower() in t:
        s += 10
    if first_artist and (first_artist in t or first_artist in c):
        s += 10
    return s


def find_on_youtube(track: SpotifyTrack, cancel: CancelToken | None = None) -> str:
    """The YouTube URL that best matches this song."""
    import yt_dlp

    query = f"{track.artists} - {track.title} audio" if track.artists else f"{track.title} audio"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch8:{query}", download=False)
    if cancel:
        cancel.check()
    entries = [e for e in (info or {}).get("entries") or [] if e and e.get("id")]
    if not entries:
        raise RuntimeError(f"Couldn't find “{track.label}” on YouTube")
    best = max(entries, key=lambda e: score(track, e.get("title") or "", e.get("channel") or e.get("uploader") or "",
                                            e.get("duration")))
    return f"https://www.youtube.com/watch?v={best['id']}"


def download(track: SpotifyTrack, on_progress: Callable[[float, str], None] | None = None,
             cancel: CancelToken | None = None) -> youtube.YouTubeResult:
    if on_progress:
        on_progress(0.0, f"Finding “{track.label}” on YouTube…")
    url = find_on_youtube(track, cancel)
    result = youtube.download_mp3(url, on_progress=on_progress, cancel=cancel)
    return youtube.YouTubeResult(result.path, track.title)  # name it as Spotify does, not the upload's title
