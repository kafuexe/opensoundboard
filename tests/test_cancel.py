import sys
import types

import pytest

from soundboard.sources import youtube
from soundboard.sources.cancel import CancelToken, Cancelled
from soundboard.sources.soundbuttonsworld import RemoteSound, SoundButtonsWorld


class ChunkedResponse:
    def __init__(self, chunks, on_chunk=None):
        self.chunks, self.on_chunk = chunks, on_chunk

    def raise_for_status(self):
        pass

    def iter_content(self, _size):
        for i, chunk in enumerate(self.chunks):
            if self.on_chunk:
                self.on_chunk(i)
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class Session:
    def __init__(self, response):
        self.headers, self.response = {}, response

    def get(self, *a, **kw):
        return self.response


def test_sbw_download_cancel_mid_stream_leaves_nothing(tmp_path):
    token = CancelToken()
    resp = ChunkedResponse([b"a" * 10] * 5, on_chunk=lambda i: token.cancel() if i == 2 else None)
    client = SoundButtonsWorld(Session(resp))
    with pytest.raises(Cancelled):
        client.download(RemoteSound(1, "x", "x.mp3"), tmp_path, cancel=token)
    assert list(tmp_path.iterdir()) == []


def test_sbw_download_without_cancel_completes(tmp_path):
    client = SoundButtonsWorld(Session(ChunkedResponse([b"ab", b"cd"])))
    path = client.download(RemoteSound(1, "x", "x.mp3"), tmp_path, cancel=CancelToken())
    assert path.read_bytes() == b"abcd"


def _fake_yt_dlp(monkeypatch, hook_calls):
    """A stand-in for yt_dlp that reports progress through the hooks like the real one."""
    from yt_dlp.utils import DownloadCancelled, DownloadError

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download):
            try:
                for i in range(hook_calls):
                    for hook in self.opts["progress_hooks"]:
                        hook({"status": "downloading", "downloaded_bytes": i, "total_bytes": hook_calls})
            except DownloadCancelled as exc:  # the real yt-dlp wraps it like this
                raise DownloadError(str(exc)) from exc
            return {"title": "t"}

    fake = types.SimpleNamespace(YoutubeDL=FakeYDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setattr(youtube, "ffmpeg_path", lambda: "ffmpeg")


def test_youtube_cancel_raises_cancelled(monkeypatch):
    _fake_yt_dlp(monkeypatch, hook_calls=5)
    token = CancelToken()
    seen = []

    def progress(frac, msg):
        seen.append(frac)
        if len(seen) == 2:
            token.cancel()

    with pytest.raises(Cancelled):
        youtube.download_mp3("https://youtu.be/x", on_progress=progress, cancel=token)
    assert len(seen) == 2  # stopped at the next progress update


def test_youtube_cancel_before_start(monkeypatch):
    _fake_yt_dlp(monkeypatch, hook_calls=3)
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        youtube.download_mp3("https://youtu.be/x", cancel=token)
