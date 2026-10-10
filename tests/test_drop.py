import tkinter

from soundboard.ui.drop import split_drop


class FakeApp:
    def __init__(self):
        self.tk = tkinter.Tcl()


def test_split_drop_handles_spaces_folders_and_non_audio(tmp_path):
    spaced = tmp_path / "vine boom.mp3"
    spaced.write_bytes(b"x")
    notes = tmp_path / "notes.txt"
    notes.write_text("x")
    folder = tmp_path / "pack"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.wav").write_bytes(b"x")
    (folder / "sub" / "b.OGG").write_bytes(b"x")
    (folder / "readme.md").write_text("x")

    # tkdnd wraps paths containing spaces in braces
    data = f"{{{spaced}}} {notes} {folder}".replace("\\", "/")
    audio, skipped = split_drop(FakeApp(), data)

    assert sorted(p.name for p in audio) == ["a.wav", "b.OGG", "vine boom.mp3"]
    assert sorted(p.name for p in skipped) == ["notes.txt", "readme.md"]
