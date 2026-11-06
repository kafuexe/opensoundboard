import json

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


def test_folders_create_rename_delete(wav_file):
    lib = Library.load()
    memes = lib.add_folder("  Memes ")
    assert memes == "Memes"
    a = lib.add_file(wav_file("a.wav"), folder="Memes")
    b = lib.add_file(wav_file("b.wav"))
    assert [s.id for s in lib.search("", folder="Memes")] == [a.id]
    assert [s.id for s in lib.search("", folder="")] == [b.id]
    assert len(lib.search("", folder=None)) == 2

    lib.rename_folder("Memes", "Funny")
    assert Library.load().get(a.id).folder == "Funny"
    assert Library.load().folders == ["Funny"]

    assert lib.delete_folder("Funny") == 1
    reloaded = Library.load()
    assert reloaded.folders == [] and reloaded.get(a.id).folder == ""
    assert reloaded.get(a.id).path.exists()  # deleting a folder keeps its sounds


@pytest.mark.parametrize("name", ["", "   ", "memes", "All", "unsorted"])
def test_folder_name_rules(name):
    lib = Library.load()
    lib.add_folder("Memes")
    with pytest.raises(ValueError):
        lib.add_folder(name)


def test_move_to_folder_and_unknown_folder_falls_back(wav_file):
    lib = Library.load()
    lib.add_folder("Games")
    s = lib.add_file(wav_file(), folder="Nope")
    assert s.folder == ""
    lib.update(s.id, folder="Games")
    assert lib.get(s.id).folder == "Games"
    lib.update(s.id, folder="Gone")
    assert lib.get(s.id).folder == ""


def test_loads_library_from_before_folders(wav_file):
    lib = Library.load()
    s = lib.add_file(wav_file())
    raw = json.loads(paths.library_file().read_text())
    del raw["folders"]
    for item in raw["sounds"]:
        del item["folder"]
    paths.library_file().write_text(json.dumps(raw))
    old = Library.load()
    assert old.folders == [] and old.get(s.id).folder == ""


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


def test_files_are_named_after_sounds_with_numbers_for_duplicates(wav_file):
    lib = Library.load()
    files = [lib.add_file(wav_file("Vine_Boom.wav")).file for _ in range(3)]
    assert files == ["Vine Boom.wav", "Vine Boom 1.wav", "Vine Boom 2.wav"]
    assert all((paths.sounds_dir() / f).exists() for f in files)


def test_unsafe_characters_are_dropped_from_file_names(wav_file):
    sound = Library.load().add_file(wav_file(), name='what?? "no" <way>: a/b')
    assert sound.name == 'what?? "no" <way>: a/b'
    assert sound.file == "what no way ab.wav"


def test_rename_renames_the_file(wav_file):
    lib = Library.load()
    a = lib.add_file(wav_file("a.wav"))
    lib.add_file(wav_file("b.wav"))
    lib.update(a.id, name="b")
    assert a.file == "b 1.wav" and a.path.exists()
    assert not (paths.sounds_dir() / "a.wav").exists()
    lib.update(a.id, name="b", hotkey="f1")  # same name keeps the file
    assert Library.load().get(a.id).file == "b 1.wav"


def test_old_id_named_files_get_their_sound_name(wav_file):
    lib = Library.load()
    s = lib.add_file(wav_file("Bruh.wav"))
    s.path.rename(paths.sounds_dir() / f"{s.id}.wav")
    raw = json.loads(paths.library_file().read_text())
    raw["sounds"][0]["file"] = f"{s.id}.wav"
    paths.library_file().write_text(json.dumps(raw))

    loaded = Library.load()
    assert loaded.get(s.id).file == "Bruh.wav" and loaded.get(s.id).path.exists()
    assert Library.load().get(s.id).file == "Bruh.wav"  # saved, not just renamed in memory


def test_folder_random_key_plays_from_that_folder_without_repeats(wav_file):
    lib = Library.load()
    lib.add_folder("Memes")
    a = lib.add_file(wav_file("a.wav"), folder="Memes")
    b = lib.add_file(wav_file("b.wav"), folder="Memes")
    lib.add_file(wav_file("c.wav"))  # unsorted: never picked
    picks, last = [], None
    for _ in range(40):
        last = lib.random_sound("Memes", avoid=last).id
        picks.append(last)
    assert set(picks) == {a.id, b.id}
    assert all(x != y for x, y in zip(picks, picks[1:]))  # never twice in a row
    assert lib.random_sound("Memes", avoid=a.id) is b


def test_random_from_a_one_sound_or_empty_folder(wav_file):
    lib = Library.load()
    lib.add_folder("Solo")
    lib.add_folder("Empty")
    only = lib.add_file(wav_file(), folder="Solo")
    assert lib.random_sound("Solo", avoid=only.id) is only  # the only one is allowed to repeat
    assert lib.random_sound("Empty") is None


def test_folder_keys_persist_follow_renames_and_have_one_owner(wav_file):
    lib = Library.load()
    lib.add_folder("Memes")
    s = lib.add_file(wav_file(), name="Bruh")
    lib.update(s.id, hotkey="f5")
    lib.set_folder_hotkey("Memes", "f5")  # taking a sound's key clears it there
    assert lib.get(s.id).hotkey == "" and lib.folder_hotkeys == {"Memes": "f5"}
    assert lib.hotkey_owner("f5") == "the “Memes” folder"

    lib.rename_folder("Memes", "Funny")
    assert Library.load().folder_hotkeys == {"Funny": "f5"}

    lib.update(s.id, hotkey="f5")  # and a sound taking it back clears the folder's
    assert lib.folder_hotkeys == {} and lib.hotkey_owner("f5") == "“Bruh”"

    lib.set_folder_hotkey("Funny", "f6")
    lib.delete_folder("Funny")
    assert Library.load().folder_hotkeys == {}
