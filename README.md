# AutoClick Pro

AutoClick Pro is a desktop auto-clicker for Windows built with Python and PySide6.

## Features

- Automatic clicks with left, right, or middle button, single or double. Clicks are sent with the Windows `SendInput` API; "left" is always the primary button, also with swapped (left-handed) buttons.
- Custom interval in milliseconds (default 100 ms, minimum 1 ms, so up to 1000 clicks per second) with slider and a live clicks-per-second readout. A high-resolution timer keeps the cadence accurate to well under a millisecond on average.
- Optional randomness: vary each delay by up to ±50 % and scatter fixed-position clicks within a radius of up to 50 px.
- Remappable global hotkeys with modifiers (for example `Ctrl+Alt+S`): start/pause (default F6) and emergency stop (default F8). They are registered with `RegisterHotKey`, so the focused app never sees them and no keyboard hook is installed.
- Click at the cursor or at fixed coordinates chosen with a full-screen picker (magnifier, color readout, arrow keys nudge by one pixel; works across monitors and display scaling).
- **Sequences** (Sequence tab): a list of steps, each with its own delay: clicks (button, double, repeat count), mouse press/release, moves, key presses and *wait until a pixel has a color*. Reorder by drag and drop or the arrow buttons, edit delays in the table, play once, N times or forever, at 0.25×–4× speed.
- **Recorder**: press Record, use the mouse and keyboard, and stop with the start/pause hotkey. Quick clicks become click steps, drags stay press/release pairs, timing is kept. Input aimed at AutoClick Pro itself and injected input are ignored; the stop hotkey is removed from the end. Keys or buttons a sequence leaves pressed are released when it stops.
- **Color trigger** (Clicker tab): click only while a pixel has a given color, or stop when it changes.
- **Background clicks**: send clicks to the picked window as window messages without moving your cursor. Many games and some apps ignore these.
- Optional start countdown and a floating, draggable status overlay.
- Auto-stop limits: max clicks and max duration, with live `count / target`.
- Pause and resume keep the click count, the click target and the remaining duration.
- Corner failsafe: slam the cursor into the top-left corner of the desktop to halt. With several monitors, this is the corner the cursor actually stops at when pushed up and left.
- Emergency stop button in the window.
- System tray icon with Start/Pause, Emergency Stop, and Quit.
- Minimize to tray, always-on-top, sound feedback, dark card UI.
- Settings save automatically to `%APPDATA%\AutoClick Pro\settings.json` (settings from 1.x are migrated once).
- Profiles store click settings (interval, button, position, trigger, limits and the sequence); import/export them as JSON.
- Single-instance guard: a second launch just warns.
- Clicks run on a background thread so the window stays responsive.
- Errors and crashes append to `~/.autoclick_pro.log` (rotated, ~512 KB x2). Native crashes (access violations) are written to `%APPDATA%\AutoClick Pro\crash.log`; the next start moves the report aside as `crash-<time>.log` and tells you.
- **About → Copy diagnostics** puts a report on the clipboard (version, Windows build, screens, hotkeys, last log lines). Home folders are replaced by `~`, and recorded keys, sequences and profile contents are never included.
- **Update check** (Settings tab): off by default. When on, it asks GitHub once a week for the latest release number and shows a link. Nothing is downloaded or installed by the app, and no personal data is sent. It uses Windows' own HTTPS stack (WinHTTP), so it adds nothing to the build.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer to run from source and build the EXE.
- Internet access while installing Python packages.

## Install and run from source

Open PowerShell in the project folder:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

For development (tests, lint, type check, EXE build):

```powershell
pip install -r requirements-dev.txt
python -m pytest
ruff check .
mypy
```

CI (`.github/workflows/ci.yml`) runs the same checks on Windows, builds the EXE, smoke-tests it and uploads `dist\AutoClickPro\` as an artifact.

If PowerShell blocks virtual environment activation, run once in the current PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## How to use

1. Set the interval in milliseconds (slider covers 1–2000 ms, the box goes up to one hour). Optionally add a random delay or position spread.
2. Pick the mouse button and single or double-click.
3. Select **At cursor position** to click wherever the cursor is, or **At fixed coordinates**.
4. For fixed coordinates, press **Pick position…**, point at the target and click (Esc cancels). Tick **Click the window in the background** to send clicks to that window without moving the cursor.
5. Optional caps: max clicks and max duration stop automatically with a status note.
6. Press **Start** or the start hotkey to begin. Press **Pause** or the hotkey again to pause, and **Resume** to continue the same run.
7. Press **Emergency Stop** or its hotkey to halt clicks immediately. After that, restarting requires a new start action.

To automate a series of actions, open the **Sequence** tab: add steps with **+ Click…** and **+ Wait for color…**, or press **● Record**, do the actions, and press the start/pause hotkey to stop. **Start** plays the sequence while the Sequence tab is open; the Clicker tab's max clicks, max duration and failsafe apply too.

Global hotkeys are only active while AutoClick Pro is open and can be remapped in the Hotkeys card: toggle Ctrl/Alt/Shift/Win and pick a key (F1–F24, navigation keys, or A–Z/0–9 with a modifier). The two hotkeys must differ. Bare F12 is reserved by Windows for debuggers and cannot be used; settings from older versions that used F12 move to F8. Only one app instance runs at a time. Emergency stop waits for the click currently being sent to finish, then blocks further clicks.

## Build EXE (one-folder)

Build on Windows using the same virtual environment, with `requirements-dev.txt` installed:

```powershell
.\.venv\Scripts\Activate.ps1
pyinstaller --noconfirm --clean AutoClickPro.spec
```

Output goes to:

```text
dist\AutoClickPro\AutoClickPro.exe
```

Copy the whole `dist\AutoClickPro\` folder to distribute the app; the EXE needs the DLLs, plugins, and `assets\` next to it. The spec bundles `assets\`, sets the EXE icon, generates the EXE version resource from `autoclick_pro/__init__.py`, and leaves out unused Qt modules, plugins and translations (about 53 MB instead of 116 MB).

## Releasing

One command tests, builds, signs (when configured), packages and writes checksums:

```powershell
python tools/make_release.py --repo owner/name
```

It runs ruff, mypy and pytest, builds with PyInstaller, checks that the EXE's version matches `__version__`, launches the EXE for a few seconds, then writes to `release\`:

- `AutoClickPro-<version>-win64-portable.zip`
- `AutoClickPro-Setup-<version>.exe` (only when Inno Setup 6.3+ is installed)
- `SHA256SUMS.txt`
- `winget\<version>\*.yaml` manifests (when `--repo` is given and the installer was built)

**Code signing.** Unsigned EXEs trigger Windows SmartScreen and antivirus false positives. To sign, install the Windows SDK (for `signtool.exe`), buy a code-signing certificate, and set one of:

```powershell
$env:AUTOCLICK_SIGN_THUMBPRINT = "<SHA-1 of a certificate in your Windows store>"
# or
$env:AUTOCLICK_SIGN_PFX = "C:\path\cert.pfx"; $env:AUTOCLICK_SIGN_PASSWORD = "..."
python tools/make_release.py --repo owner/name --sign
```

Signing uses SHA-256 with an RFC 3161 timestamp (`AUTOCLICK_SIGN_TIMESTAMP` to change the server) and verifies the result. A new certificate still builds SmartScreen reputation over time unless it is an EV certificate.

**GitHub release.** Pushing a tag such as `v2.2.0` runs `.github/workflows/release.yml`, which does the same and attaches the files to a GitHub release. To sign there, add the repository secrets `SIGN_PFX_BASE64` (the .pfx, base64-encoded) and `SIGN_PFX_PASSWORD`.

**Update source.** Set `UPDATE_REPO = "owner/name"` in `autoclick_pro/updater.py` so the update check knows where releases live. It is empty by default, which keeps the check disabled.

**winget.** `packaging/winget/*.yaml.in` are templates; the release tool fills in the version, installer URL and SHA-256. Review the publisher, license and package identifier in them once, then submit the generated folder to [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs). Check a folder locally with `winget validate --manifest release\winget\<version>`.

## Installer (optional)

Build the EXE first, then compile the Inno Setup script (needs Inno Setup 6.3 or newer; the release tool does this for you):

```text
iscc installer.iss
```

Output goes to `installer\AutoClickPro-Setup-<version>.exe`. Per-user install, no admin needed, optional desktop icon.

The version lives only in `__version__` in `autoclick_pro/__init__.py`. The spec writes it into the EXE, and `installer.iss` reads it back from the built EXE.

## Build EXE (one-file, optional)

To produce a single EXE file:

```powershell
.\.venv\Scripts\Activate.ps1
pyinstaller --noconfirm --clean --windowed --onefile --name AutoClickPro main.py
```

Output goes to `dist\AutoClickPro.exe`. One-file may take longer to start because its contents are extracted temporarily when the app opens. Note: one-file mode does not bundle `assets\`; prefer the spec build.

## Troubleshooting

- **"Could not register … another program already uses it":** another app owns that key combination. Pick a different hotkey in the Hotkeys card; the message disappears once both hotkeys are registered.
- **Hotkeys/clicks not reaching the target app:** Windows does not allow a lower-privilege process to control some higher-privilege apps. Run AutoClick Pro and the target app at the same privilege level. The About dialog shows whether this app runs as admin.
- **App does not start after build:** build on Windows in a clean Python environment, then read the PyInstaller output in PowerShell. If the message mentions a missing Windows runtime DLL, install the matching Microsoft Visual C++ Redistributable.
- **Fixed coordinates are off:** display scaling or monitor layout changes can shift coordinates; pick the position again after changing display settings.
- **Background clicks do nothing:** the target app reads the real mouse instead of window messages (common for games and browsers' web content). Turn background clicks off.
- **A recording plays back in the wrong place:** recordings use screen coordinates. Keep the target window where it was when you recorded it.
- **Clicks stop at once with a failsafe note:** the cursor entered the top-left corner of the desktop. Move it away and start again, or turn the failsafe off.
- **Settings reset with a warning:** the settings file was unreadable. The old copy is kept next to it as `settings.json.corrupt`.
- **Already running warning:** an instance is active (maybe in the tray). Use the tray icon to show or quit it.

## Packaging notes

PyInstaller builds for the OS it runs on; build the Windows EXE on Windows. The spec file uses PyInstaller hooks for PySide6/shiboken6 and bundles `assets\` so the required Qt plugins, binaries, dynamic imports, and icons end up in the output folder.

Official references:

- [PyInstaller: Using Spec Files](https://pyinstaller.org/en/latest/spec-files.html)
- [PyInstaller: Using PyInstaller](https://pyinstaller.org/en/latest/usage.html)
- [Qt for Python: Deployment with PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)
- [SendInput](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput) and [RegisterHotKey](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-registerhotkey)
