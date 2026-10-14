# AutoClick Pro

AutoClick Pro is a desktop auto-clicker for Windows built with Python and PySide6.

## Features

- Automatic clicks with left, right, or middle button, single or double.
- Custom interval in milliseconds (default 100 ms, minimum 10 ms) with slider.
- Remappable global hotkeys (F1–F12): start/pause and emergency stop. Hotkeys are swallowed, so the focused app never sees them.
- Click at the cursor or at fixed coordinates.
- Auto-stop limits: max clicks and max duration, with live `count / target`.
- Pause and resume keep the click count, the click target and the remaining duration.
- Corner failsafe: slam the cursor into the top-left corner of the primary monitor to halt.
- Emergency stop button in the window.
- System tray icon with Start/Pause, Emergency Stop, and Quit.
- Minimize to tray, always-on-top, sound feedback, dark card UI.
- Settings save automatically to `%APPDATA%\AutoClick Pro\settings.json` (settings from 1.x are migrated once).
- Profiles store click settings (interval, button, position, limits); import/export them as JSON.
- Single-instance guard: a second launch just warns.
- Clicks run on a background thread so the window stays responsive.
- Errors and crashes append to `~/.autoclick_pro.log` (rotated, ~512 KB x2).

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

1. Set the interval in milliseconds (slider covers 10–2000 ms, the box goes up to one hour).
2. Pick the mouse button and single or double-click.
3. Select **At cursor position** to click wherever the cursor is, or **At fixed coordinates**.
4. For fixed coordinates, point the mouse at the target and press **Capture position**.
5. Optional caps: max clicks and max duration stop automatically with a status note.
6. Press **Start** or the start hotkey to begin. Press **Pause** or the hotkey again to pause, and **Resume** to continue the same run.
7. Press **Emergency Stop** or its hotkey to halt clicks immediately. After that, restarting requires a new start action.

Global hotkeys are only active while AutoClick Pro is open and can be remapped in the Hotkeys card (F1–F12, must differ). Only one app instance runs at a time. Emergency stop waits for the click currently being sent to finish, then blocks further clicks.

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

## Installer (optional)

Build the EXE first, then compile the Inno Setup script (needs Inno Setup 6):

```text
iscc installer.iss
```

Output goes to `installer\AutoClickPro-Setup-<version>.exe`. Per-user install, no admin needed, optional desktop icon.

The version lives only in `__version__` in `autoclick_pro/__init__.py`. The spec writes it into the EXE, and `installer.iss` reads it back from the built EXE.

## Build EXE (one-file, optional)

To produce a single EXE file:

```powershell
.\.venv\Scripts\Activate.ps1
pyinstaller --noconfirm --clean --windowed --onefile --name AutoClickPro --collect-all pynput main.py
```

Output goes to `dist\AutoClickPro.exe`. One-file may take longer to start because its contents are extracted temporarily when the app opens. Note: one-file mode does not bundle `assets\`; prefer the spec build.

## Troubleshooting

- **Hotkeys not working:** make sure the app is not blocked by another hotkey tool, and that start/pause and emergency stop use different keys. Close and reopen the app after changing keyboard or security software settings.
- **Hotkeys/clicks not reaching the target app:** Windows does not allow a lower-privilege process to control some higher-privilege apps. Run AutoClick Pro and the target app at the same privilege level. The About dialog shows whether this app runs as admin.
- **App does not start after build:** build on Windows in a clean Python environment, then read the PyInstaller output in PowerShell. If the message mentions a missing Windows runtime DLL, install the matching Microsoft Visual C++ Redistributable.
- **Fixed coordinates are off:** display scaling or monitor layout changes can shift coordinates; capture the current position again after changing display settings.
- **Clicks stop at once with a failsafe note:** the cursor entered the top-left corner of the primary monitor. Move it away and start again, or turn the failsafe off.
- **Settings reset with a warning:** the settings file was unreadable. The old copy is kept next to it as `settings.json.corrupt`.
- **Already running warning:** an instance is active (maybe in the tray). Use the tray icon to show or quit it.

## Packaging notes

PyInstaller builds for the OS it runs on; build the Windows EXE on Windows. The spec file uses PyInstaller hooks for PySide6/shiboken6, collects pynput explicitly, and bundles `assets\` so the required Qt plugins, binaries, dynamic imports, and icons end up in the output folder.

Official references:

- [PyInstaller: Using Spec Files](https://pyinstaller.org/en/latest/spec-files.html)
- [PyInstaller: Using PyInstaller](https://pyinstaller.org/en/latest/usage.html)
- [Qt for Python: Deployment with PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)
- [pynput: Handling the keyboard](https://pynput.readthedocs.io/en/latest/keyboard.html)
