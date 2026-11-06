# PyInstaller spec: builds dist\Soundboard\Soundboard.exe (one folder, no console window).
# Run through installer\build.ps1, which also builds the plugin DLL and the setup .exe.
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "installer" / "launch.py")],
    pathex=[str(root)],
    datas=[(str(root / "soundboard" / "assets"), "soundboard/assets")],
    hiddenimports=["soundboard.micplugin.admin", "pystray._win32"],  # imported lazily
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Soundboard",
    icon=str(root / "soundboard" / "assets" / "icon.ico"),
    console=False,
    version=str(root / "installer" / "build" / "version-info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Soundboard")
