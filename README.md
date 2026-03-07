# WindowsNote

Windows desktop note-taking app for Microsoft Surface Pro 6 with a OneNote-like hierarchy:

- Notebooks
- Sections
- Pages

The app stores all notes on your local machine folder (configurable) using JSON files.

## Features

- Notebook > Section > Page structure
- Rich text formatting (bold, italic, underline, highlight)
- Quick page search
- Autosave and manual save (`Ctrl+S`)
- Rename and delete notebook/section/page
- Choose a custom local storage folder

## Run

```powershell
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

## Storage Layout

Configured folder (default: `./local_notes`) contains:

- `notebooks/<notebook-id>/meta.json`
- `notebooks/<notebook-id>/sections/<section-id>/meta.json`
- `notebooks/<notebook-id>/sections/<section-id>/pages/<page-id>.json`

## Config

Edit `config.json`:

```json
{
  "data_root": "./local_notes"
}
```

## Notes

This implementation targets core behavior similar to OneNote's organization model and local-first storage.
