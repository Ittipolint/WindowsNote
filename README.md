# WindowsNote

Windows desktop note-taking app for Microsoft Surface Pro 6 with a OneNote-like hierarchy:

- Notebooks
- Sections
- Pages

The app stores all notes on your local machine folder (configurable) using JSON files.

## Features

- Notebook > Section > Page structure
- Ink-focused note canvas (no text editor area)
- Adjustable pane widths (Notebooks / Pages / Editor)
- Ink + images in one continuous page canvas (single view)
- One shared vertical/horizontal scrollbar for continuous page navigation
- Ink canvas for stylus/mouse drawing
- Pen color, stroke size, and stroke eraser tools (Surface Pen supported)
- Insert image into page, select/move/delete image position
- Print page to PDF (paper size via dropdown: A4, LETTER, LEGAL, A5)
- Save As (export `.wnote.json`)
- Quick page search
- Autosave and manual save (`Ctrl+S`)
- Rename and delete notebook/section/page
- Choose a custom local storage folder

## Run

```powershell
python -m pip install -r requirements.txt
python src\windows_note.py
```

## Build Windows Installer Package

Build executable + installer assets:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_release.ps1
```

Output files:

- `release\WindowsNote-payload.zip`
- `release\Install-WindowsNote.ps1`

Install on Windows:

```powershell
cd .\release
powershell -ExecutionPolicy Bypass -File .\Install-WindowsNote.ps1
```

Default installation path:

- `%LOCALAPPDATA%\WindowsNote\WindowsNote.exe`

Default data folder:

- `%USERPROFILE%\Documents\WindowsNoteData`

## Build One-Click Setup.exe (Wizard Installer)

Create a single `Setup.exe` file:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_setup_exe.ps1
```

The script auto-downloads portable NSIS on first run.

Output:

- `release\WindowsNote-Setup.exe`

## Code Signing (Reduce SmartScreen Warnings)

Set signing certificate via environment variables (PowerShell):

```powershell
$env:CODE_SIGN_PFX="C:\path\to\codesign.pfx"
$env:CODE_SIGN_PASSWORD="your-pfx-password"
# Optional timestamp URL override:
# $env:CODE_SIGN_TIMESTAMP_URL="http://timestamp.digicert.com"
```

Build and sign both app EXE + Setup EXE:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_setup_exe.ps1 -Sign -SignStrict
```

Alternative signing from cert store:

```powershell
$env:CODE_SIGN_SUBJECT="Your Company LLC"
powershell -ExecutionPolicy Bypass -File .\tools\build_setup_exe.ps1 -Sign -SignStrict
```

Notes:
- `-Sign` enables signing (warning only if signing is skipped/failed).
- `-SignStrict` fails build when signing is not successful.
- For best SmartScreen reputation, use OV/EV code-signing certificates and sign consistently across releases.

## Storage Layout

Configured folder (default: `./local_notes`) contains:

- `notebooks/<notebook-id>/meta.json`
- `notebooks/<notebook-id>/sections/<section-id>/meta.json`
- `notebooks/<notebook-id>/sections/<section-id>/pages/<page-id>.json`
- `notebooks/<notebook-id>/sections/<section-id>/pages/<page-id>_ink.json`
- `notebooks/<notebook-id>/sections/<section-id>/pages/<page-id>_ink.png`

## Config

Edit `config.json`:

```json
{
  "data_root": "./local_notes"
}
```

## Notes

This implementation targets core behavior similar to OneNote's organization model and local-first storage.
