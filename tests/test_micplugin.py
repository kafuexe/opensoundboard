import sys

import pytest

from soundboard.micplugin import CLSID, admin, fx, mics, ring_name

DEFAULT = fx.DEFAULT_MODE
REALTEK_AEC = "{AB3B404A-B18F-4b4f-B91F-77F2DE95EB18}"
VENDOR = "{11111111-2222-3333-4444-555555555555}"


def test_ring_name_is_per_mic_and_lowercase():
    assert ring_name("{552C99D7-3A86-46FD-89BA-6E88C24FE4E8}") == \
        "Global\\SoundboardMicRing.{552c99d7-3a86-46fd-89ba-6e88c24fe4e8}"


def test_attach_to_a_mic_with_no_effects():  # the Yeti
    out = fx.attached({})
    assert out == {fx.EFX: ("String", CLSID), fx.EFX_MODES: ("MultiString", [DEFAULT])}
    assert fx.has_plugin(out)


def test_attach_goes_first_in_a_composite_chain():  # the Realtek mics here
    values = {fx.COMPOSITE_EFX: ("MultiString", [REALTEK_AEC]),
              fx.EFX_MODES: ("MultiString", [DEFAULT, "{FC1CFC9B-B9D6-4CFA-B5E0-4BB2166878B2}"])}
    out = fx.attached(values)
    assert out[fx.COMPOSITE_EFX] == ("MultiString", [CLSID, REALTEK_AEC])
    assert out[fx.EFX_MODES] == values[fx.EFX_MODES]  # default mode already listed
    assert fx.EFX not in out
    assert fx.attached(out) == out  # attaching twice changes nothing


def test_attach_keeps_a_single_vendor_effect_by_chaining_it():
    out = fx.attached({fx.EFX: ("String", VENDOR), fx.EFX_MODES: ("MultiString", [DEFAULT])})
    assert out[fx.COMPOSITE_EFX] == ("MultiString", [CLSID, VENDOR])
    assert out[fx.EFX] == ("String", VENDOR)


def test_restore_puts_back_exactly_the_backup():
    for original in ({}, {fx.COMPOSITE_EFX: ("MultiString", [REALTEK_AEC])}, {fx.EFX: ("String", VENDOR)}):
        backup = fx.backup_of(original)
        assert fx.restored(fx.attached(original), backup) == original


def test_restore_without_a_backup_just_removes_us():
    values = {fx.COMPOSITE_EFX: ("MultiString", [CLSID, REALTEK_AEC]), fx.EFX_MODES: ("MultiString", [DEFAULT])}
    out = fx.restored(values, None)
    assert out == {fx.COMPOSITE_EFX: ("MultiString", [REALTEK_AEC]), fx.EFX_MODES: ("MultiString", [DEFAULT])}
    assert fx.restored({fx.EFX: ("String", CLSID.lower())}, None) == {}


def test_backups_from_the_old_powershell_installer_still_load(monkeypatch):
    # install.ps1 stored {"name": {"Kind": ..., "Data": [...]}} with Data always a list.
    import json
    raw = json.dumps({fx.EFX: {"Kind": "String", "Data": [VENDOR]},
                      fx.EFX_MODES: {"Kind": "MultiString", "Data": [DEFAULT]}})

    class Key:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(admin.winreg, "OpenKey", lambda *a: Key())
    monkeypatch.setattr(admin.winreg, "QueryValueEx", lambda k, n: (raw, 1))
    assert admin._load_backup("{x}") == {fx.EFX: ("String", VENDOR), fx.EFX_MODES: ("MultiString", [DEFAULT])}


def test_duplicate_mic_names_get_numbers():
    found = [("{a}", "Microphone (LifeCam)"), ("{b}", "Microphone (LifeCam)"), ("{c}", "Yeti")]
    assert [n for _, n in mics.unique_names(found)] == ["Microphone (LifeCam)", "Microphone (LifeCam) 2", "Yeti"]


def test_list_microphones_reads_active_endpoints(monkeypatch):
    class Key:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *a): pass

    tree = {
        "{AAA}": {"DeviceState": 1, "Properties": {mics._NAME_PROP: "Microphone", mics._DEVICE_PROP: "Yeti"}},
        "{bbb}": {"DeviceState": 4, "Properties": {mics._NAME_PROP: "Microphone", mics._DEVICE_PROP: "Gone"}},
    }

    def lookup(path):
        parts = path.split("\\")[-2:] if path.endswith("Properties") else [path.split("\\")[-1]]
        node = tree[parts[0]]
        return node["Properties"] if len(parts) == 2 else node

    monkeypatch.setattr(mics.winreg, "OpenKey", lambda parent, sub, *a: Key(sub if isinstance(parent, int) else f"{parent.path}\\{sub}"))
    monkeypatch.setattr(mics.winreg, "QueryInfoKey", lambda k: (len(tree), 0, 0))
    monkeypatch.setattr(mics.winreg, "EnumKey", lambda k, i: list(tree)[i])
    monkeypatch.setattr(mics.winreg, "QueryValueEx", lambda k, name: (lookup(k.path)[name], 1))
    monkeypatch.setattr(mics, "read_fx", lambda mic_id: {fx.EFX: ("String", CLSID)})
    assert mics.list_microphones() == [mics.Microphone("{aaa}", "Microphone (Yeti)", True)]


def test_default_mic_falls_back_to_one_with_the_plugin(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)  # no audio API: can't ask Windows
    listed = [mics.Microphone("{a}", "A", False), mics.Microphone("{b}", "B", True)]
    assert mics.default_mic_id(listed) == "{b}"


def test_admin_command_from_source_runs_the_package():
    program, params = admin.admin_command(["add", "{552c99d7-3a86-46fd-89ba-6e88c24fe4e8}"])
    assert program == sys.executable
    assert params == "-m soundboard --admin add {552c99d7-3a86-46fd-89ba-6e88c24fe4e8}"


def test_admin_command_when_installed(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Soundboard\Soundboard.exe")
    assert admin.admin_command(["uninstall"]) == (r"C:\Program Files\Soundboard\Soundboard.exe", "--admin uninstall")
    assert str(admin.installed_dll()) == r"C:\Program Files\Soundboard\SoundboardApo.dll"


def test_admin_refuses_without_admin_and_says_why(monkeypatch, tmp_path):
    monkeypatch.setattr(admin, "DATA_DIR", tmp_path)
    monkeypatch.setattr(admin, "ERROR_FILE", tmp_path / "admin-error.txt")
    monkeypatch.setattr(admin.ctypes.windll.shell32, "IsUserAnAdmin", lambda: 0)
    assert admin.main(["uninstall"]) == 1
    assert "administrator" in (tmp_path / "admin-error.txt").read_text()


def test_bad_admin_command_is_rejected():
    with pytest.raises(SystemExit):
        admin.main(["bogus"])
