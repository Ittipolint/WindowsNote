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
