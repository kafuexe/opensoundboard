import json

import pytest

from soundboard.sources.spotify import SpotifyTrack, looks_like_spotify, parse_embed, parse_link, score


@pytest.mark.parametrize("link, expected", [
    ("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc123", ("track", "4cOdK2wGLETKBW3PvgPWqT")),
    ("https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT", ("track", "4cOdK2wGLETKBW3PvgPWqT")),
    ("open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy", ("album", "4aawyAB9vmqN3uQ7FjRGTy")),
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x", ("playlist", "37i9dQZF1DXcBWIGoYBM5M")),
    ("spotify:track:4cOdK2wGLETKBW3PvgPWqT", ("track", "4cOdK2wGLETKBW3PvgPWqT")),
    ("https://open.spotify.com/artist/0gxyHStUsqpMadRV0Di1Qt", None),  # artists aren't supported
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None),
])
def test_parse_link(link, expected):
    assert parse_link(link) == expected
    assert looks_like_spotify(link) == (expected is not None)


def _page(entity: dict) -> str:
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_parse_track_page():
    link = parse_embed(_page({"name": "Never Gonna Give You Up", "artists": [{"name": "Rick Astley"}],
                              "duration": 213573}), "track")
    assert link.tracks == [SpotifyTrack("Never Gonna Give You Up", "Rick Astley", 213.573)]


def test_parse_album_page():
    link = parse_embed(_page({"name": "Global Warming", "trackList": [
        {"title": "Global Warming (feat. Sensato)", "subtitle": "Pitbull,\xa0Sensato", "duration": 85400},
        {"title": "Don't Stop the Party (feat. TJR)", "subtitle": "Pitbull,\xa0TJR", "duration": 206120},
    ]}), "album")
    assert link.name == "Global Warming"
    assert [t.label for t in link.tracks] == ["Pitbull, Sensato – Global Warming (feat. Sensato)",
                                             "Pitbull, TJR – Don't Stop the Party (feat. TJR)"]


def test_unreadable_or_empty_pages_are_clear_errors():
    with pytest.raises(ValueError, match="changed"):
        parse_embed("<html>nothing here</html>", "track")
    with pytest.raises(ValueError, match="no songs"):
        parse_embed(_page({"name": "Empty", "trackList": []}), "playlist")


def _best(track, candidates):
    return max(candidates, key=lambda c: score(track, *c))


def test_picks_the_original_not_a_re_recording():
    # Real search results for this song; the "Pianoforte" one used to win on the "Official Audio" bonus.
    track = SpotifyTrack("Never Gonna Give You Up", "Rick Astley", 213.573)
    candidates = [
        ("Never Gonna Give You Up (2022 Remaster)", "Rick Astley", 214),
        ("Rick Astley - Never Gonna Give You Up (HQ Audio)", "Rick Astley", 212),
        ("Rick Astley  - Never Gonna Give You Up (Pianoforte) (Official Audio)", "Rick Astley", 210),
        ("Rick Astley - Never Gonna Give You Up", "Amazing Lyrics", 214),
    ]
    assert "Pianoforte" not in _best(track, candidates)[0]


def test_picks_the_artist_not_a_karaoke_cover_on_a_topic_channel():
    track = SpotifyTrack("Don't Stop the Party (feat. TJR)", "Pitbull, TJR", 206.12)
    candidates = [
        ("Pitbull ft. TJR - Don't Stop The Party (Official Audio)", "Pitbull", 205),
        ("Don't Stop the Party (Originally Performed By Pitbull Feat Tjr)", "The True Star - Topic", 207),
        ("Pitbull - Don't Stop The Party (Lyrics) ft. TJR", "7clouds", 207),
    ]
    assert _best(track, candidates)[1] == "Pitbull"


def test_length_rules_out_loops_and_live_versions():
    track = SpotifyTrack("Loser", "Tame Impala", 223.0)
    candidates = [
        ("Tame Impala - Loser (1 Hour Loop)", "loops", 3600),
        ("Tame Impala - Loser (Live at Coachella)", "Tame Impala", 250),
        ("Tame Impala - Loser", "someone", 224),
    ]
    assert _best(track, candidates)[2] == 224
