import pytest

from soundboard import paths
from soundboard.library import Library, clean_name
from soundboard.settings import Settings


def test_add_copies_file_and_persists(wav_file):
    src = wav_file("Vine_Boom.wav")
    lib = Library.load()
    sound = lib.add_file(src)

    assert sound.name == "Vine Boom"
    assert sound.path.parent == paths.sounds_dir()
    assert sound.path.exists() and src.exists()
    assert Library.load().get(sound.id).name == "Vine Boom"


def test_add_move_removes_source(wav_file):
    src = wav_file()
    Library.load().add_file(src, move=True)
    assert not src.exists()


def test_rejects_non_audio(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(ValueError):
        Library.load().add_file(bad)


def test_remove_deletes_file(wav_file):
    lib = Library.load()
    sound = lib.add_file(wav_file())
    lib.remove(sound.id)
    assert not sound.path.exists()
    assert Library.load().sounds == []


def test_hotkey_moves_to_new_owner(wav_file):
    lib = Library.load()
    a = lib.add_file(wav_file("a.wav"))
    b = lib.add_file(wav_file("b.wav"))
    lib.update(a.id, hotkey="ctrl+1")
    lib.update(b.id, hotkey="ctrl+1")
    assert lib.get(a.id).hotkey == ""
    assert lib.get(b.id).hotkey == "ctrl+1"


def test_blank_rename_keeps_old_name(wav_file):
    lib = Library.load()
    sound = lib.add_file(wav_file("keep.wav"))
    lib.update(sound.id, name="   ")
    assert lib.get(sound.id).name == "keep"


def test_search_matches_all_words(wav_file):
    lib = Library.load()
    lib.add_file(wav_file("x.wav"), name="Vine boom loud")
    lib.add_file(wav_file("y.wav"), name="Bruh")
    assert [s.name for s in lib.search("boom vine")] == ["Vine boom loud"]
    assert len(lib.search("")) == 2


def test_move_reorders(wav_file):
    lib = Library.load()
    a = lib.add_file(wav_file("a.wav"))
    b = lib.add_file(wav_file("b.wav"))
    lib.move(b.id, 0)
    assert [s.id for s in Library.load().sounds] == [b.id, a.id]


def test_has_origin(wav_file):
    lib = Library.load()
    lib.add_file(wav_file(), origin="soundbuttonsworld", origin_id="abc.mp3")
    assert lib.has_origin("soundbuttonsworld", "abc.mp3")
    assert not lib.has_origin("soundbuttonsworld", "other.mp3")


def test_clean_name():
    assert clean_name("  hello__world   x ") == "hello world x"
    assert len(clean_name("a" * 200)) == 80


def test_settings_roundtrip_ignores_unknown_keys():
    s = Settings(mic_volume=0.3, stop_hotkey="f12")
    s.save()
    raw = paths.settings_file().read_text().replace("{", '{"from_the_future": 1,', 1)
    paths.settings_file().write_text(raw)
    loaded = Settings.load()
    assert loaded.mic_volume == 0.3 and loaded.stop_hotkey == "f12"
