import pytest

from soundboard.sources.soundbuttonsworld import RemoteSound, SoundButtonsWorld, parse_page
from soundboard.sources.youtube import looks_like_url, parse_time


def test_parse_search_page():
    payload = {"total": 472, "data": [
        {"id": 718, "name": "BRUH ", "color": "red", "fileName": "96c4a22c-f139.mp3", "url": "bruh-1"},
        {"id": 2, "name": "evil", "fileName": "../../etc/passwd"},
        {"id": 3, "name": "VINE  BOOM", "fileName": "707db471.mp3", "categoryName": "Memes Soundboard"},
    ]}
    page = parse_page(payload, page=1, page_size=30)
    assert [s.name for s in page.sounds] == ["BRUH", "VINE BOOM"]
    assert page.sounds[1].category == "Memes"
    assert page.sounds[0].audio_url == "https://soundbuttonsworld.com/uploads/96c4a22c-f139.mp3"
    assert page.has_more


def test_feed_without_total_has_more_when_full():
    items = [{"id": i, "name": f"s{i}", "fileName": f"{i}.mp3"} for i in range(3)]
    assert parse_page({"data": items}, 1, 3).has_more
    assert not parse_page({"data": items[:2]}, 1, 3).has_more


class FakeResponse:
    def __init__(self, payload=None, body=b""):
        self.payload, self.body = payload, body

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, _size):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append((url, params))
        if url.endswith(".mp3"):
            return FakeResponse(body=b"ID3fake")
        return FakeResponse({"total": 1, "data": [{"id": 1, "name": "bruh", "fileName": "a.mp3"}]})


def test_search_calls_api_and_download_writes_file(tmp_path):
    session = FakeSession()
    client = SoundButtonsWorld(session)
    page = client.search(" bruh ")
    assert session.calls[0] == ("https://soundbuttonsworld.com/api/memes/search", {"page": 1, "pageSize": 30, "q": "bruh"})
    path = client.download(page.sounds[0], tmp_path)
    assert path.read_bytes() == b"ID3fake"
    client.download(RemoteSound(1, "bruh", "a.mp3"), tmp_path)  # cached: no second request
    assert len(session.calls) == 2


@pytest.mark.parametrize("text,expected", [("", None), ("83", 83), ("1:23", 83), ("0:01:23.5", 83.5), ("2:00:00", 7200)])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


def test_parse_time_rejects_junk():
    with pytest.raises(ValueError):
        parse_time("soon")


def test_looks_like_url():
    assert looks_like_url("https://youtu.be/abc")
    assert not looks_like_url("never gonna give you up")
