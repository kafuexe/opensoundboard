import numpy as np
import pytest
import soundfile as sf


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("SOUNDBOARD_HOME", str(home))
    return home


@pytest.fixture
def wav_file(tmp_path):
    def make(name="beep.wav", seconds=0.1, rate=44100, channels=1):
        frames = int(seconds * rate)
        data = np.full((frames, channels), 0.25, dtype=np.float32)
        path = tmp_path / name
        sf.write(str(path), data, rate)
        return path
    return make
