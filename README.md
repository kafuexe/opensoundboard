# Soundboard

A Soundpad-style soundboard for Windows. Press a key and a sound plays in your headphones and into
your microphone at the same time, at two separate volumes.

## Install it

Download `Soundboard-Setup-<version>.exe` from the GitHub releases and run it. It installs the app
and, unless you untick it, puts the mic plugin on your microphones. Uninstalling (Windows Settings →
Apps) takes the plugin off every mic and puts back whatever effects each mic had.

## Run it from source

```
py -3.14 -m venv .venv
.venv\Scripts\pip install -e . -r requirements-dev.txt
```

Then double-click `run.bat`, or run `C:\projects\Soundboard\.venv\Scripts\soundboard.exe` from anywhere. YouTube downloads also need ffmpeg on your PATH
(`winget install ffmpeg`).

## What it does

- **My sounds:** a grid of pads. Click to play, right-click (or ⋯) to rename, set a hotkey, change
  volume, or delete. The search box filters by name or key.
- **Drag and drop:** drag audio files (or a folder of them) from Explorer onto the window, pick a
  folder, and add them.
- **Import audio files:** MP3, WAV, OGG, FLAC, M4A, Opus, AAC. Files are copied into
  `%APPDATA%\Soundboard\sounds`, so moving the originals doesn't break anything.
- **Sound Buttons World:** search soundbuttonsworld.com or browse Trending and New. ▶ previews in
  your headphones only; **Add** downloads the sound into your library.
- **YouTube:** paste a link, optionally set start and end times (`83`, `1:23`, `0:01:23.5`), and
  it's downloaded as an MP3 and added.
- **Global hotkeys:** a key per sound, plus a Stop all key, working while a game or Discord is
  focused. Games running as administrator only see them if the app also runs as administrator.
- **Two faders:** *Into my mic* and *In my headphones*.

## Where the mic audio goes

Settings → *Into my mic*:

- **Mic plugin:** sounds are mixed straight into your real microphone by the Soundboard mic
  plugin, like Soundpad. Pick the mic you talk into; switching is instant. A mic plugged in after
  installing shows **Add the plugin to this mic** (one Windows permission prompt). See
  [docs/dll-spec.md](docs/dll-spec.md) and [docs/mic-bridge.md](docs/mic-bridge.md).
- **Output device:** sends the mic share to any output device instead, such as a virtual cable.
  Handy for testing in the meantime.

## Build the installer

```
installer\build.ps1            # DLL (apo\), app (PyInstaller), then dist\Soundboard-Setup-<version>.exe
```

Needs the Visual Studio C++ build tools with the Windows SDK, and Inno Setup 6
(`winget install JRSoftware.InnoSetup`). The version comes from `pyproject.toml`.

**Releases:** push a tag like `v0.2.0` and `.github/workflows/release.yml` tests, builds the
installer on GitHub and attaches it to a release. The app icon is drawn by `tools/make_icon.py`.

## Layout

```
soundboard/
  library.py, settings.py, paths.py   data (JSON in %APPDATA%\Soundboard)
  hotkeys.py                          global hotkeys (keyboard library)
  audio/decode.py                     decode + resample to 48 kHz stereo, with a cache
  audio/mixer.py                      sums the sounds that are playing
  audio/outputs.py                    device output (WASAPI) and the mic-plugin ring
  audio/engine.py                     one play() feeds headphones and mic
  micplugin/                          which mics have the plugin; `--admin` install/add/uninstall
  sources/soundbuttonsworld.py        site search/trending/new + download
  sources/youtube.py                  yt-dlp + ffmpeg to MP3, with trimming
  ui/                                 customtkinter views
tests/                                pytest (no window or audio device needed)
apo/                                  the mic plugin DLL (C++) and its native tests
installer/                            PyInstaller spec, Inno Setup script, build.ps1
```

Run the tests with `.venv\Scripts\python -m pytest`.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). The installer also ships FFmpeg (LGPL) and deno (MIT);
see `tools\README.txt` in the install folder.
