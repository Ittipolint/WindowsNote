import json
import os
import shutil
import uuid
import base64
import time
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont
try:
    from PIL import Image, ImageDraw, ImageTk, ImageGrab, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = Any
    ImageDraw = Any
    ImageTk = Any
    ImageGrab = Any
    ImageFont = Any

try:
    from reportlab.lib.pagesizes import A4, A5, LEGAL, LETTER
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    A4 = A5 = LEGAL = LETTER = None
    ImageReader = Any
    pdf_canvas = Any

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_DATA_ROOT = "./local_notes"
TEXT_TAGS = ("bold", "italic", "underline", "highlight")
DEFAULT_INK_COLOR = "#111827"
APP_VERSION = "1.3.3"
PAGE_CANVAS_WIDTH = 8000
PAGE_CANVAS_HEIGHT = 12000
INK_SMOOTHING_ALPHA = 1.0
INK_MIN_POINT_DELTA = 0
INK_INTERPOLATION_STEP = 2.0
INK_RELEASE_ALPHA = 1.0
INK_STROKE_CONTINUE_DISTANCE = 28
INK_STROKE_CONTINUE_WINDOW_SEC = 0.45
INK_PRESSURE_MIN_FACTOR = 0.55
INK_PRESSURE_MAX_FACTOR = 1.45
HIGHLIGHTER_ALPHA = 0.28
HIGHLIGHTER_MIN_WIDTH = 10
ERASER_INTERPOLATION_STEP = 2.0
ERASER_MODE_PARTIAL = "partial"
ERASER_MODE_STROKE = "stroke"
THEME_LIGHT = "light"
THEME_DARK = "dark"
UI_SCALE_NORMAL = "normal"
UI_SCALE_LARGE = "large"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_title(title: str) -> str:
    return " ".join(title.strip().split()) or "Untitled"


@dataclass
class Page:
    id: str
    title: str
    content: str
    formatting: list
    created_at: str
    updated_at: str


class LocalNoteStorage:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.notebooks_dir = self.root_dir / "notebooks"
        self.notebooks_dir.mkdir(parents=True, exist_ok=True)

    def set_root(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.notebooks_dir = self.root_dir / "notebooks"
        self.notebooks_dir.mkdir(parents=True, exist_ok=True)

    def list_notebooks(self) -> list[dict]:
        items = []
        if not self.notebooks_dir.exists():
            return items
        for nb_dir in sorted(self.notebooks_dir.iterdir()):
            meta_path = nb_dir / "meta.json"
            if nb_dir.is_dir() and meta_path.exists():
                meta = self._read_json(meta_path, {})
                items.append(
                    {
                        "id": nb_dir.name,
                        "title": meta.get("title", "Untitled Notebook"),
                        "order": meta.get("order"),
                    }
                )
        items.sort(key=lambda x: (self._order_key(x.get("order")), x.get("title", "").lower(), x.get("id", "")))
        return items

    def create_notebook(self, title: str) -> str:
        nb_id = uuid.uuid4().hex[:12]
        nb_dir = self.notebooks_dir / nb_id
        (nb_dir / "sections").mkdir(parents=True, exist_ok=True)
        self._write_json(
            nb_dir / "meta.json",
            {
                "id": nb_id,
                "title": sanitize_title(title),
                "created_at": utc_now_iso(),
                "order": self._next_notebook_order(),
            },
        )
        return nb_id

    def reorder_notebooks(self, ordered_notebook_ids: list[str]) -> None:
        for index, notebook_id in enumerate(ordered_notebook_ids):
            meta_path = self.notebooks_dir / notebook_id / "meta.json"
            meta = self._read_json(meta_path, {})
            if not meta:
                continue
            meta["order"] = index
            meta["updated_at"] = utc_now_iso()
            self._write_json(meta_path, meta)

    def rename_notebook(self, notebook_id: str, title: str) -> None:
        meta_path = self.notebooks_dir / notebook_id / "meta.json"
        meta = self._read_json(meta_path, {})
        meta["title"] = sanitize_title(title)
        meta["updated_at"] = utc_now_iso()
        self._write_json(meta_path, meta)

    def delete_notebook(self, notebook_id: str) -> None:
        target = self.notebooks_dir / notebook_id
        if target.exists():
            shutil.rmtree(target)

    def list_sections(self, notebook_id: str) -> list[dict]:
        base = self.notebooks_dir / notebook_id / "sections"
        out = []
        if not base.exists():
            return out
        for section_dir in sorted(base.iterdir()):
            meta_path = section_dir / "meta.json"
            if section_dir.is_dir() and meta_path.exists():
                meta = self._read_json(meta_path, {})
                out.append(
                    {
                        "id": section_dir.name,
                        "title": meta.get("title", "Untitled Section"),
                        "order": meta.get("order"),
                    }
                )
        out.sort(key=lambda x: (self._order_key(x.get("order")), x.get("title", "").lower(), x.get("id", "")))
        return out

    def create_section(self, notebook_id: str, title: str) -> str:
        section_id = uuid.uuid4().hex[:12]
        section_dir = self.notebooks_dir / notebook_id / "sections" / section_id
        (section_dir / "pages").mkdir(parents=True, exist_ok=True)
        self._write_json(
            section_dir / "meta.json",
            {
                "id": section_id,
                "title": sanitize_title(title),
                "created_at": utc_now_iso(),
                "order": self._next_section_order(notebook_id),
            },
        )
        return section_id

    def reorder_sections(self, notebook_id: str, ordered_section_ids: list[str]) -> None:
        for index, section_id in enumerate(ordered_section_ids):
            meta_path = self.notebooks_dir / notebook_id / "sections" / section_id / "meta.json"
            meta = self._read_json(meta_path, {})
            if not meta:
                continue
            meta["order"] = index
            meta["updated_at"] = utc_now_iso()
            self._write_json(meta_path, meta)

    def move_section(
        self,
        source_notebook_id: str,
        section_id: str,
        target_notebook_id: str,
        before_section_id: str | None = None,
    ) -> bool:
        if not (source_notebook_id and target_notebook_id and section_id):
            return False
        source_dir = self.notebooks_dir / source_notebook_id / "sections" / section_id
        if not source_dir.exists():
            return False
        target_sections_dir = self.notebooks_dir / target_notebook_id / "sections"
        target_sections_dir.mkdir(parents=True, exist_ok=True)
        target_dir = target_sections_dir / section_id
        if source_dir.resolve() != target_dir.resolve():
            if target_dir.exists():
                return False
            shutil.move(str(source_dir), str(target_sections_dir))

        moved_meta_path = target_dir / "meta.json"
        moved_meta = self._read_json(moved_meta_path, {})
        if moved_meta:
            moved_meta["updated_at"] = utc_now_iso()
            self._write_json(moved_meta_path, moved_meta)

        if source_notebook_id != target_notebook_id:
            source_order = [sec["id"] for sec in self.list_sections(source_notebook_id)]
            self.reorder_sections(source_notebook_id, source_order)

        target_order = [sec["id"] for sec in self.list_sections(target_notebook_id)]
        if section_id in target_order:
            target_order.remove(section_id)
        if before_section_id and before_section_id in target_order:
            target_order.insert(target_order.index(before_section_id), section_id)
        else:
            target_order.append(section_id)
        self.reorder_sections(target_notebook_id, target_order)
        return True

    def rename_section(self, notebook_id: str, section_id: str, title: str) -> None:
        meta_path = self.notebooks_dir / notebook_id / "sections" / section_id / "meta.json"
        meta = self._read_json(meta_path, {})
        meta["title"] = sanitize_title(title)
        meta["updated_at"] = utc_now_iso()
        self._write_json(meta_path, meta)

    def delete_section(self, notebook_id: str, section_id: str) -> None:
        target = self.notebooks_dir / notebook_id / "sections" / section_id
        if target.exists():
            shutil.rmtree(target)

    def list_pages(self, notebook_id: str, section_id: str) -> list[dict]:
        pages_dir = self.notebooks_dir / notebook_id / "sections" / section_id / "pages"
        pages = []
        if not pages_dir.exists():
            return pages
        for page_file in sorted(pages_dir.glob("*.json")):
            if page_file.stem.endswith("_ink"):
                continue
            doc = self._read_json(page_file, {})
            pages.append(
                {
                    "id": page_file.stem,
                    "title": doc.get("title", "Untitled Page"),
                    "updated_at": doc.get("updated_at", ""),
                    "content": doc.get("content", ""),
                    "order": doc.get("order"),
                }
            )
        pages.sort(
            key=lambda x: (
                self._order_key(x.get("order")),
                x.get("updated_at", ""),
                x.get("id", ""),
            )
        )
        self._normalize_page_order(notebook_id, section_id, pages)
        return pages

    def create_page(self, notebook_id: str, section_id: str, title: str) -> str:
        page_id = uuid.uuid4().hex[:12]
        now = utc_now_iso()
        page = {
            "id": page_id,
            "title": sanitize_title(title),
            "content": "",
            "formatting": [],
            "created_at": now,
            "updated_at": now,
            "order": self._next_page_order(notebook_id, section_id),
        }
        page_path = self._page_path(notebook_id, section_id, page_id)
        page_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(page_path, page)
        return page_id

    def reorder_pages(self, notebook_id: str, section_id: str, ordered_page_ids: list[str]) -> None:
        for index, page_id in enumerate(ordered_page_ids):
            path = self._page_path(notebook_id, section_id, page_id)
            doc = self._read_json(path, {})
            if not doc:
                continue
            doc["order"] = index
            doc["updated_at"] = utc_now_iso()
            self._write_json(path, doc)

    def rename_page(self, notebook_id: str, section_id: str, page_id: str, title: str) -> None:
        path = self._page_path(notebook_id, section_id, page_id)
        doc = self._read_json(path, {})
        doc["title"] = sanitize_title(title)
        doc["updated_at"] = utc_now_iso()
        self._write_json(path, doc)

    def delete_page(self, notebook_id: str, section_id: str, page_id: str) -> None:
        path = self._page_path(notebook_id, section_id, page_id)
        if path.exists():
            path.unlink()
        ink_json = self._ink_json_path(notebook_id, section_id, page_id)
        ink_png = self._ink_png_path(notebook_id, section_id, page_id)
        if ink_json.exists():
            ink_json.unlink()
        if ink_png.exists():
            ink_png.unlink()
        assets_dir = self._page_assets_dir(notebook_id, section_id, page_id)
        if assets_dir.exists():
            shutil.rmtree(assets_dir)

    def load_page(self, notebook_id: str, section_id: str, page_id: str) -> Page:
        path = self._page_path(notebook_id, section_id, page_id)
        doc = self._read_json(path, {})
        return Page(
            id=doc.get("id", page_id),
            title=doc.get("title", "Untitled Page"),
            content=doc.get("content", ""),
            formatting=doc.get("formatting", []),
            created_at=doc.get("created_at", utc_now_iso()),
            updated_at=doc.get("updated_at", utc_now_iso()),
        )

    def save_page(self, notebook_id: str, section_id: str, page_id: str, title: str, content: str, formatting: list) -> None:
        path = self._page_path(notebook_id, section_id, page_id)
        existing = self._read_json(path, {})
        now = utc_now_iso()
        data = {
            "id": page_id,
            "title": sanitize_title(title),
            "content": content,
            "formatting": formatting,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
            "order": existing.get("order", self._next_page_order(notebook_id, section_id)),
        }
        self._write_json(path, data)

    def load_ink_payload(self, notebook_id: str, section_id: str, page_id: str) -> dict:
        path = self._ink_json_path(notebook_id, section_id, page_id)
        payload = self._read_json(path, {})
        strokes = payload.get("strokes", [])
        images = payload.get("images", [])
        texts = payload.get("texts", [])
        return {
            "strokes": strokes if isinstance(strokes, list) else [],
            "images": images if isinstance(images, list) else [],
            "texts": texts if isinstance(texts, list) else [],
        }

    def load_ink_strokes(self, notebook_id: str, section_id: str, page_id: str) -> list[dict]:
        return self.load_ink_payload(notebook_id, section_id, page_id).get("strokes", [])

    def save_ink_payload(
        self,
        notebook_id: str,
        section_id: str,
        page_id: str,
        strokes: list[dict],
        images: list[dict],
        texts: list[dict] | None = None,
    ) -> None:
        path = self._ink_json_path(notebook_id, section_id, page_id)
        data = {
            "page_id": page_id,
            "updated_at": utc_now_iso(),
            "strokes": strokes,
            "images": images,
            "texts": texts if isinstance(texts, list) else [],
        }
        self._write_json(path, data)

    def save_ink_strokes(self, notebook_id: str, section_id: str, page_id: str, strokes: list[dict]) -> None:
        payload = self.load_ink_payload(notebook_id, section_id, page_id)
        self.save_ink_payload(
            notebook_id,
            section_id,
            page_id,
            strokes,
            payload.get("images", []),
            payload.get("texts", []),
        )

    def save_ink_image(self, notebook_id: str, section_id: str, page_id: str, image: Any) -> None:
        path = self.ink_png_path(notebook_id, section_id, page_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")

    def ink_png_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self._ink_png_path(notebook_id, section_id, page_id)

    def import_page_asset(self, notebook_id: str, section_id: str, page_id: str, source_path: Path) -> str:
        ext = source_path.suffix.lower() or ".png"
        filename = f"{uuid.uuid4().hex[:12]}{ext}"
        target = self._page_assets_dir(notebook_id, section_id, page_id) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        return filename

    def page_asset_path(self, notebook_id: str, section_id: str, page_id: str, filename: str) -> Path:
        return self._page_assets_dir(notebook_id, section_id, page_id) / filename

    def save_page_asset_image(self, notebook_id: str, section_id: str, page_id: str, image: Any, ext: str = ".png") -> str:
        suffix = ext.lower() if ext and ext.startswith(".") else ".png"
        filename = f"{uuid.uuid4().hex[:12]}{suffix}"
        target = self._page_assets_dir(notebook_id, section_id, page_id) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        return filename

    def _page_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}.json"

    def _ink_json_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}_ink.json"

    def _ink_png_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}_ink.png"

    def _page_assets_dir(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}_assets"

    @staticmethod
    def _order_key(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10**9

    def _next_notebook_order(self) -> int:
        max_order = -1
        for item in self.list_notebooks():
            max_order = max(max_order, self._order_key(item.get("order")))
        return max_order + 1 if max_order < 10**9 else len(self.list_notebooks())

    def _next_section_order(self, notebook_id: str) -> int:
        max_order = -1
        for item in self.list_sections(notebook_id):
            max_order = max(max_order, self._order_key(item.get("order")))
        return max_order + 1 if max_order < 10**9 else len(self.list_sections(notebook_id))

    def _next_page_order(self, notebook_id: str, section_id: str) -> int:
        max_order = -1
        pages_dir = self.notebooks_dir / notebook_id / "sections" / section_id / "pages"
        if not pages_dir.exists():
            return 0
        for page_file in pages_dir.glob("*.json"):
            if page_file.stem.endswith("_ink"):
                continue
            doc = self._read_json(page_file, {})
            max_order = max(max_order, self._order_key(doc.get("order")))
        return max_order + 1 if max_order < 10**9 else len(self.list_pages(notebook_id, section_id))

    def _normalize_page_order(self, notebook_id: str, section_id: str, pages: list[dict]) -> None:
        dirty = False
        for index, page in enumerate(pages):
            if self._order_key(page.get("order")) != index:
                dirty = True
                page["order"] = index
        if not dirty:
            return
        for page in pages:
            path = self._page_path(notebook_id, section_id, page["id"])
            doc = self._read_json(path, {})
            if not doc:
                continue
            doc["order"] = int(page.get("order", 0))
            self._write_json(path, doc)

    @staticmethod
    def _read_json(path: Path, fallback):
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            return fallback

    @staticmethod
    def _write_json(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class WindowsNoteApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"WindowsNote v{APP_VERSION} - OneNote-style Local Notes")
        self.geometry("1280x800")
        self.minsize(980, 620)

        self.config_data = self._load_config()
        self.storage_root = self._resolve_data_root(self.config_data.get("data_root", DEFAULT_DATA_ROOT))
        self.storage = LocalNoteStorage(self.storage_root)
        initial_theme = str(self.config_data.get("theme", THEME_LIGHT)).strip().lower()
        if initial_theme not in (THEME_LIGHT, THEME_DARK):
            initial_theme = THEME_LIGHT
        initial_ui_scale = str(self.config_data.get("ui_scale", UI_SCALE_NORMAL)).strip().lower()
        if initial_ui_scale not in (UI_SCALE_NORMAL, UI_SCALE_LARGE):
            initial_ui_scale = UI_SCALE_NORMAL
        initial_eraser_mode = str(self.config_data.get("eraser_mode", ERASER_MODE_PARTIAL)).strip().lower()
        if initial_eraser_mode not in (ERASER_MODE_PARTIAL, ERASER_MODE_STROKE):
            initial_eraser_mode = ERASER_MODE_PARTIAL
        self.theme_var = tk.StringVar(value=initial_theme)
        self.ui_scale_var = tk.StringVar(value=initial_ui_scale)
        self.eraser_mode_var = tk.StringVar(value=initial_eraser_mode)
        self.eraser_mode_var.trace_add("write", self._on_eraser_mode_change)
        self.style = ttk.Style(self)
        self.current_theme_colors = {}
        self.base_font_sizes = {}
        self.base_treeview_rowheight = 20
        self._cache_base_fonts()

        self.selected_notebook_id = None
        self.selected_section_id = None
        self.selected_page_id = None
        self.page_cache = []
        self.is_loading_page = False
        self.autosave_job = None
        self.loading_depth = 0
        self.loading_total_steps = 0
        self.loading_current_step = 0
        self.loading_mode = "indeterminate"
        self.loading_base_message = ""
        self.ink_strokes = []
        self.redo_strokes = []
        self.ink_images = []
        self.ink_texts = []
        self.ink_text_widgets = {}
        self.ink_image_cache = {}
        self.ink_image_items = {}
        self.selected_image_id = None
        self.selected_image_outline = None
        self.dragging_image_id = None
        self.dragging_offset = (0, 0)
        self.dragging_text_id = None
        self.dragging_text_offset = (0, 0)
        self.selected_object_kind = None
        self.selected_object_id = None
        self.current_stroke = None
        self.current_stroke_item = None
        self.current_raw_point = None
        self.current_eraser_point = None
        self.last_stroke_end_point = None
        self.last_stroke_end_time = 0.0
        self.current_tool = tk.StringVar(value="pen")
        initial_pen_size = self._safe_pen_size(self.config_data.get("pen_size", 4))
        self.pen_size_var = tk.IntVar(value=initial_pen_size)
        self.pen_size_var.trace_add("write", self._on_pen_size_change)
        self.pen_color = self._safe_pen_color(self.config_data.get("pen_color", DEFAULT_INK_COLOR))
        self.pillow_warning_shown = False
        self.tree_drag_token = None
        self.tree_drag_start_y = None
        self.tree_drag_active = False
        self.tree_drag_ghost = None
        self.tree_drag_indicator = None
        self.page_drag_index = None
        self.page_drag_start_y = None
        self.page_drag_active = False

        self._build_ui()
        self.apply_theme(self.theme_var.get(), persist=False)
        self.apply_ui_scale(self.ui_scale_var.get(), persist=False)
        self._bind_shortcuts()
        self.refresh_notebooks()
        self.after(120, self._restore_ui_state)
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        if not PIL_AVAILABLE:
            self.after(
                200,
                lambda: messagebox.showwarning(
                    "Pillow Missing",
                    "Ink PNG export requires Pillow.\nRun: python -m pip install pillow",
                ),
            )

    def _load_config(self) -> dict:
        if not CONFIG_FILE.exists():
            data = {"data_root": DEFAULT_DATA_ROOT}
            self._save_config(data)
            return data
        try:
            with CONFIG_FILE.open("r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {"data_root": DEFAULT_DATA_ROOT}
            self._save_config(data)
            return data

    def _save_config(self, data: dict) -> None:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ui_state(self) -> dict:
        state = self.config_data.get("ui_state", {})
        return state if isinstance(state, dict) else {}

    def _capture_ui_state(self) -> dict:
        self._sync_selection_context()
        selected_page_id = self.selected_page_id
        sel = self.pages_list.curselection()
        if sel and sel[0] < len(self.page_cache):
            selected_page_id = self.page_cache[sel[0]]["id"]

        state = {
            "selected_notebook_id": self.selected_notebook_id,
            "selected_section_id": self.selected_section_id,
            "selected_page_id": selected_page_id,
        }
        try:
            state["main_sash"] = int(self.main_paned.sashpos(0))
        except (tk.TclError, ValueError):
            pass
        try:
            state["right_sash"] = int(self.right_paned.sashpos(0))
        except (tk.TclError, ValueError):
            pass
        try:
            win_state = self.state()
            if win_state in ("normal", "zoomed", "iconic"):
                state["window_state"] = win_state
        except tk.TclError:
            pass
        try:
            state["window_geometry"] = self.geometry()
        except tk.TclError:
            pass
        return state

    def _save_ui_state(self) -> None:
        self.config_data["ui_state"] = self._capture_ui_state()
        self._save_config(self.config_data)

    def _apply_tree_selection(self, notebook_id: str | None, section_id: str | None) -> bool:
        section_token = f"sec:{notebook_id}:{section_id}" if notebook_id and section_id else None
        notebook_token = f"nb:{notebook_id}" if notebook_id else None
        token = section_token if section_token and self.tree.exists(section_token) else notebook_token
        if not token or not self.tree.exists(token):
            return False
        self.tree.selection_set(token)
        self.tree.focus(token)
        self.tree.see(token)
        self.selected_notebook_id = notebook_id
        self.selected_section_id = section_id if token.startswith("sec:") else None
        return True

    def _restore_ui_state(self) -> None:
        state = self._ui_state()
        if not state:
            return
        self.update_idletasks()
        main_sash = state.get("main_sash")
        right_sash = state.get("right_sash")
        if isinstance(main_sash, int):
            try:
                self.main_paned.sashpos(0, main_sash)
            except tk.TclError:
                pass
        if isinstance(right_sash, int):
            try:
                self.right_paned.sashpos(0, right_sash)
            except tk.TclError:
                pass
        geometry = state.get("window_geometry")
        if isinstance(geometry, str) and geometry:
            try:
                self.geometry(geometry)
            except tk.TclError:
                pass
        win_state = state.get("window_state")
        if isinstance(win_state, str) and win_state in ("normal", "zoomed", "iconic"):
            try:
                self.state(win_state)
            except tk.TclError:
                pass

        notebook_id = state.get("selected_notebook_id")
        section_id = state.get("selected_section_id")
        page_id = state.get("selected_page_id")
        if not self._apply_tree_selection(notebook_id, section_id):
            return

        self.refresh_pages()
        if page_id and self._select_page_in_list(page_id):
            self.selected_page_id = page_id
            self.load_current_page()

    def on_app_close(self):
        try:
            if self.autosave_job:
                self.after_cancel(self.autosave_job)
                self.autosave_job = None
            self.save_current_page()
            self._save_ui_state()
        finally:
            self.destroy()

    def _resolve_data_root(self, value: str) -> Path:
        p = Path(value)
        if p.is_absolute():
            return p
        return (CONFIG_FILE.parent / p).resolve()

    def _build_ui(self):
        self._build_menu()

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.search_var = tk.StringVar()
        ttk.Label(top, text="Search Page:").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(top, textvariable=self.search_var, width=45)
        self.search_entry.pack(side=tk.LEFT, padx=(6, 12))
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh_pages())

        self.loading_text_var = tk.StringVar(value="")
        self.loading_label = ttk.Label(top, textvariable=self.loading_text_var)
        self.loading_bar = ttk.Progressbar(top, mode="determinate", length=180, maximum=100, value=0)

        self.storage_label_var = tk.StringVar(value=f"Storage: {self.storage_root}")
        ttk.Label(top, textvariable=self.storage_label_var).pack(side=tk.LEFT, padx=(8, 0))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Button(toolbar, text="Print PDF", command=self.print_to_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)
        ttk.Label(toolbar, text="Ink:").pack(side=tk.LEFT)
        self.pen_tool_radio = ttk.Radiobutton(toolbar, text="Pen", value="pen", variable=self.current_tool)
        self.pen_tool_radio.pack(side=tk.LEFT, padx=2)
        self.highlighter_tool_radio = ttk.Radiobutton(toolbar, text="Highlighter", value="highlighter", variable=self.current_tool)
        self.highlighter_tool_radio.pack(side=tk.LEFT, padx=2)
        self.eraser_tool_radio = ttk.Radiobutton(toolbar, text="Eraser", value="eraser", variable=self.current_tool)
        self.eraser_tool_radio.pack(side=tk.LEFT, padx=2)
        ttk.Label(toolbar, text="Mode").pack(side=tk.LEFT, padx=(6, 2))
        self.eraser_mode_combo = ttk.Combobox(
            toolbar,
            textvariable=self.eraser_mode_var,
            values=[ERASER_MODE_PARTIAL, ERASER_MODE_STROKE],
            state="readonly",
            width=8,
        )
        self.eraser_mode_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.pick_color_btn = ttk.Button(toolbar, text="Pick Color", command=self.pick_ink_color)
        self.pick_color_btn.pack(side=tk.LEFT, padx=2)
        self.ink_color_buttons = []
        for color in ("#111827", "#2563eb", "#dc2626", "#15803d"):
            color_btn = tk.Button(
                toolbar,
                width=2,
                bg=color,
                relief=tk.GROOVE,
                command=lambda c=color: self.set_ink_color(c),
            )
            color_btn.pack(side=tk.LEFT, padx=1)
            self.ink_color_buttons.append(color_btn)
        ttk.Label(toolbar, text="Size").pack(side=tk.LEFT, padx=(8, 2))
        self.pen_size_spin = ttk.Spinbox(toolbar, from_=1, to=24, width=4, textvariable=self.pen_size_var)
        self.pen_size_spin.pack(side=tk.LEFT, padx=2)
        self.insert_image_btn = ttk.Button(toolbar, text="Insert Image", command=self.insert_image_at_cursor)
        self.insert_image_btn.pack(side=tk.LEFT, padx=6)
        self.delete_image_btn = ttk.Button(toolbar, text="Delete Image", command=self.delete_selected_image)
        self.delete_image_btn.pack(side=tk.LEFT, padx=2)
        self.clear_ink_btn = ttk.Button(toolbar, text="Clear Ink", command=self.clear_ink)
        self.clear_ink_btn.pack(side=tk.LEFT, padx=6)
        self.undo_stroke_btn = ttk.Button(toolbar, text="Undo Stroke", command=self.undo_stroke)
        self.undo_stroke_btn.pack(side=tk.LEFT, padx=2)
        self.redo_stroke_btn = ttk.Button(toolbar, text="Redo Stroke", command=self.redo_stroke)
        self.redo_stroke_btn.pack(side=tk.LEFT, padx=2)
        ttk.Label(toolbar, text=f"Version {APP_VERSION}").pack(side=tk.RIGHT, padx=4)

        self.main_paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        notebook_frame = ttk.Frame(self.main_paned)
        self.right_paned = ttk.Panedwindow(self.main_paned, orient=tk.HORIZONTAL)
        pages_frame = ttk.Frame(self.right_paned)
        right = ttk.Frame(self.right_paned)

        self.main_paned.add(notebook_frame, weight=3)
        self.main_paned.add(self.right_paned, weight=9)
        self.right_paned.add(pages_frame, weight=2)
        self.right_paned.add(right, weight=8)

        ttk.Label(notebook_frame, text="Notebooks / Sections").pack(anchor=tk.W)
        tree_wrap = ttk.Frame(notebook_frame)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_wrap, show="tree")
        tree_y = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        tree_x = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.tree_drag_indicator = tk.Frame(self.tree, bg="#2563eb", height=2)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_select)
        self.tree.bind("<ButtonPress-1>", self.on_tree_drag_start)
        self.tree.bind("<B1-Motion>", self.on_tree_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_drag_drop, add="+")

        nb_btns = ttk.Frame(notebook_frame)
        nb_btns.pack(fill=tk.X, pady=4)
        ttk.Button(nb_btns, text="+ Notebook", command=self.add_notebook).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="+ Section", command=self.add_section).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="Rename", command=self.rename_tree_item).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="Delete", command=self.delete_tree_item).pack(side=tk.LEFT, padx=2)

        ttk.Label(pages_frame, text="Pages").pack(anchor=tk.W)
        pages_wrap = ttk.Frame(pages_frame)
        pages_wrap.pack(fill=tk.BOTH, expand=True)
        self.pages_list = tk.Listbox(pages_wrap, exportselection=False)
        pages_y = ttk.Scrollbar(pages_wrap, orient=tk.VERTICAL, command=self.pages_list.yview)
        pages_x = ttk.Scrollbar(pages_wrap, orient=tk.HORIZONTAL, command=self.pages_list.xview)
        self.pages_list.configure(yscrollcommand=pages_y.set, xscrollcommand=pages_x.set)
        self.pages_list.grid(row=0, column=0, sticky="nsew")
        pages_y.grid(row=0, column=1, sticky="ns")
        pages_x.grid(row=1, column=0, sticky="ew")
        pages_wrap.rowconfigure(0, weight=1)
        pages_wrap.columnconfigure(0, weight=1)
        self.pages_list.bind("<<ListboxSelect>>", self.on_page_select)
        self.pages_list.bind("<ButtonPress-1>", self.on_page_drag_start)
        self.pages_list.bind("<B1-Motion>", self.on_page_drag_motion)
        self.pages_list.bind("<ButtonRelease-1>", self.on_page_drag_drop, add="+")

        page_btns = ttk.Frame(pages_frame)
        page_btns.pack(fill=tk.X, pady=4)
        ttk.Button(page_btns, text="+ Page", command=self.add_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(page_btns, text="Rename", command=self.rename_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(page_btns, text="Delete", command=self.delete_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(page_btns, text="Delete Section", command=self.delete_current_section).pack(side=tk.LEFT, padx=2)

        title_frame = ttk.Frame(right)
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text="Page Title:").pack(side=tk.LEFT)
        self.page_title_var = tk.StringVar(value="")
        self.page_title_entry = ttk.Entry(title_frame, textvariable=self.page_title_var)
        self.page_title_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.page_title_entry.bind("<KeyRelease>", self._on_page_text_change)

        page_frame = ttk.Frame(right)
        page_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        ttk.Label(page_frame, text="Page (Ink + Images)").grid(row=0, column=0, sticky="w")

        self.page_canvas = tk.Canvas(page_frame, bg="#f7f7f7", cursor="pencil")
        page_y = ttk.Scrollbar(page_frame, orient=tk.VERTICAL, command=self.page_canvas.yview)
        page_x = ttk.Scrollbar(page_frame, orient=tk.HORIZONTAL, command=self.page_canvas.xview)
        self.page_canvas.configure(
            yscrollcommand=page_y.set,
            xscrollcommand=page_x.set,
            scrollregion=(0, 0, PAGE_CANVAS_WIDTH, PAGE_CANVAS_HEIGHT),
        )
        self.page_canvas.grid(row=1, column=0, sticky="nsew")
        page_y.grid(row=1, column=1, sticky="ns")
        page_x.grid(row=2, column=0, sticky="ew")
        page_frame.rowconfigure(1, weight=1)
        page_frame.columnconfigure(0, weight=1)

        self.ink_start_y = 20
        self.page_bounds = (10, self.ink_start_y, PAGE_CANVAS_WIDTH - 190, PAGE_CANVAS_HEIGHT - 200)
        self.page_canvas.create_rectangle(
            self.page_bounds[0],
            10,
            self.page_bounds[2],
            self.page_bounds[3],
            fill="white",
            outline="#d1d5db",
            tags=("inkbg",),
        )
        self.editor = None

        self.ink_canvas = self.page_canvas
        self.canvas_cursor = (80, self.ink_start_y + 80)
        self.ink_canvas.bind("<ButtonPress-1>", self.on_ink_press)
        self.ink_canvas.bind("<B1-Motion>", self.on_ink_drag)
        self.ink_canvas.bind("<ButtonRelease-1>", self.on_ink_release)
        self.ink_canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.ink_canvas.bind("<Motion>", self._on_canvas_motion)
        self.ink_canvas.bind("<MouseWheel>", self._on_ink_mousewheel)
        self.ink_canvas.bind("<KeyPress>", self.on_canvas_keypress)
        self.object_menu = tk.Menu(self, tearoff=0)
        self.object_menu.add_command(label="Bring to Front", command=self.bring_selected_object_to_front)
        self.object_menu.add_command(label="Send to Back", command=self.send_selected_object_to_back)

        self._setup_text_tags()
        self._update_page_ready_state()

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Print to PDF...", command=self.print_to_pdf)
        file_menu.add_command(label="Change Local Storage Folder", command=self.change_storage_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_app_close)
        menubar.add_cascade(label="File", menu=file_menu)

        create_menu = tk.Menu(menubar, tearoff=0)
        create_menu.add_command(label="New Notebook", command=self.add_notebook)
        create_menu.add_command(label="New Section", command=self.add_section)
        create_menu.add_command(label="New Page", command=self.add_page)
        menubar.add_cascade(label="Create", menu=create_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Rename Notebook", command=self.rename_current_notebook)
        edit_menu.add_command(label="Rename Section", command=self.rename_current_section)
        edit_menu.add_command(label="Rename Page", command=self.rename_current_page)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Section", command=self.delete_current_section)
        edit_menu.add_command(label="Delete Page", command=self.delete_current_page)
        edit_menu.add_command(label="Delete Selected Image", command=self.delete_selected_image)
        edit_menu.add_separator()
        edit_menu.add_command(label="Undo Stroke", command=self.undo_stroke, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo Stroke", command=self.redo_stroke, accelerator="Ctrl+Y")
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_radiobutton(
            label="White Theme", value=THEME_LIGHT, variable=self.theme_var, command=lambda: self.apply_theme(THEME_LIGHT)
        )
        view_menu.add_radiobutton(
            label="Dark Theme", value=THEME_DARK, variable=self.theme_var, command=lambda: self.apply_theme(THEME_DARK)
        )
        view_menu.add_separator()
        view_menu.add_radiobutton(
            label="Text Size Normal",
            value=UI_SCALE_NORMAL,
            variable=self.ui_scale_var,
            command=lambda: self.apply_ui_scale(UI_SCALE_NORMAL),
        )
        view_menu.add_radiobutton(
            label="Text Size Large (+1)",
            value=UI_SCALE_LARGE,
            variable=self.ui_scale_var,
            command=lambda: self.apply_ui_scale(UI_SCALE_LARGE),
        )
        menubar.add_cascade(label="View", menu=view_menu)

        self.config(menu=menubar)

    def _bind_shortcuts(self):
        self.bind_all("<Control-z>", lambda _e: self.undo_stroke())
        self.bind_all("<Control-y>", lambda _e: self.redo_stroke())
        self.bind_all("<Control-Shift-Z>", lambda _e: self.redo_stroke())
        self.bind_all("<Control-v>", lambda _e: self.paste_image_from_clipboard())

    @staticmethod
    def _safe_pen_size(value) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 4
        return max(1, min(24, parsed))

    @staticmethod
    def _safe_pen_color(value) -> str:
        if not isinstance(value, str):
            return DEFAULT_INK_COLOR
        color = value.strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return color.lower()
        return DEFAULT_INK_COLOR

    def _on_pen_size_change(self, *_args):
        try:
            current = self.pen_size_var.get()
        except tk.TclError:
            return
        size = self._safe_pen_size(current)
        if size != current:
            self.pen_size_var.set(size)
            return
        if self.config_data.get("pen_size") == size:
            return
        self.config_data["pen_size"] = size
        self._save_config(self.config_data)

    def _on_eraser_mode_change(self, *_args):
        mode = self.eraser_mode_var.get().strip().lower()
        if mode not in (ERASER_MODE_PARTIAL, ERASER_MODE_STROKE):
            mode = ERASER_MODE_PARTIAL
            self.eraser_mode_var.set(mode)
            return
        if self.config_data.get("eraser_mode") == mode:
            return
        self.config_data["eraser_mode"] = mode
        self._save_config(self.config_data)

    def _page_ready(self) -> bool:
        return bool(self.selected_notebook_id and self.selected_section_id and self.selected_page_id)

    def _update_page_ready_state(self):
        ready = self._page_ready()
        ttk_state = "normal" if ready else "disabled"
        tk_state = tk.NORMAL if ready else tk.DISABLED
        cursor = "pencil" if ready else "arrow"
        canvas_bg = "#f7f7f7" if ready else "#eceff3"
        paper_bg = "white" if ready else "#f3f4f6"
        paper_outline = "#d1d5db" if ready else "#cbd5e1"

        self.pen_tool_radio.configure(state=ttk_state)
        self.highlighter_tool_radio.configure(state=ttk_state)
        self.eraser_tool_radio.configure(state=ttk_state)
        self.eraser_mode_combo.configure(state="readonly" if ready else "disabled")
        self.pick_color_btn.configure(state=ttk_state)
        self.pen_size_spin.configure(state=ttk_state)
        self.insert_image_btn.configure(state=ttk_state)
        self.delete_image_btn.configure(state=ttk_state)
        self.clear_ink_btn.configure(state=ttk_state)
        self.undo_stroke_btn.configure(state=ttk_state)
        self.redo_stroke_btn.configure(state=ttk_state)
        for btn in self.ink_color_buttons:
            btn.configure(state=tk_state)

        self.ink_canvas.configure(cursor=cursor, bg=canvas_bg)
        self.ink_canvas.itemconfigure("inkbg", fill=paper_bg, outline=paper_outline)

    def _clamp_to_page_bounds(self, x: int, y: int) -> tuple[int, int]:
        left, top, right, bottom = self.page_bounds
        return max(left, min(right, x)), max(top, min(bottom, y))

    def _inside_page_bounds(self, x: int, y: int) -> bool:
        left, top, right, bottom = self.page_bounds
        return left <= x <= right and top <= y <= bottom

    @staticmethod
    def _hex_to_rgb(color: str) -> tuple[int, int, int]:
        c = color.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    @staticmethod
    def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"

    def _blend_color(self, fg_hex: str, bg_hex: str, alpha: float) -> str:
        fr, fg, fb = self._hex_to_rgb(fg_hex)
        br, bg, bb = self._hex_to_rgb(bg_hex)
        a = max(0.0, min(1.0, alpha))
        out = (
            int((fr * a) + (br * (1.0 - a))),
            int((fg * a) + (bg * (1.0 - a))),
            int((fb * a) + (bb * (1.0 - a))),
        )
        return self._rgb_to_hex(out)

    def _read_event_pressure(self, event) -> float | None:
        raw = getattr(event, "pressure", None)
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value > 1.5:
            value = value / 1024.0
        return max(0.0, min(1.0, value))

    def _stroke_width_for_tool(self, tool: str, base_width: int, pressure: float | None) -> float:
        if tool == "highlighter":
            return float(max(HIGHLIGHTER_MIN_WIDTH, base_width * 3))
        if pressure is None:
            return float(base_width)
        factor = INK_PRESSURE_MIN_FACTOR + ((INK_PRESSURE_MAX_FACTOR - INK_PRESSURE_MIN_FACTOR) * pressure)
        return float(max(1, min(32, int(round(base_width * factor)))))

    def _stroke_render_color(self, stroke: dict) -> str:
        color = stroke.get("color", DEFAULT_INK_COLOR)
        if stroke.get("tool") != "highlighter":
            return color
        paper_bg = self.current_theme_colors.get("paper_bg", "#ffffff")
        return self._blend_color(color, paper_bg, HIGHLIGHTER_ALPHA)

    def _configure_tree_highlight_tags(self):
        if not hasattr(self, "tree"):
            return
        dark = self.theme_var.get() == THEME_DARK
        if dark:
            nb_bg, nb_fg = "#1e3a8a", "#e5e7eb"
            sec_bg, sec_fg = "#2563eb", "#ffffff"
        else:
            nb_bg, nb_fg = "#dbeafe", "#1e3a8a"
            sec_bg, sec_fg = "#bfdbfe", "#0f172a"
        self.tree.tag_configure("active_notebook", background=nb_bg, foreground=nb_fg)
        self.tree.tag_configure("active_section", background=sec_bg, foreground=sec_fg)

    def _apply_tree_selection_tags(self):
        if not hasattr(self, "tree"):
            return
        for nb_iid in self.tree.get_children(""):
            nb_id = nb_iid.split(":")[1] if ":" in nb_iid else ""
            nb_tags = ("active_notebook",) if nb_id and nb_id == self.selected_notebook_id else ()
            self.tree.item(nb_iid, tags=nb_tags)
            for sec_iid in self.tree.get_children(nb_iid):
                parts = sec_iid.split(":")
                sec_id = parts[2] if len(parts) == 3 else ""
                sec_tags = ("active_section",) if sec_id and sec_id == self.selected_section_id else ()
                self.tree.item(sec_iid, tags=sec_tags)

    def _restore_tree_selection(self):
        token = None
        if self.selected_notebook_id and self.selected_section_id:
            sec_token = f"sec:{self.selected_notebook_id}:{self.selected_section_id}"
            if self.tree.exists(sec_token):
                token = sec_token
        if not token and self.selected_notebook_id:
            nb_token = f"nb:{self.selected_notebook_id}"
            if self.tree.exists(nb_token):
                token = nb_token
        if token:
            self.tree.selection_set(token)
            self.tree.focus(token)
            self.tree.see(token)
        self._apply_tree_selection_tags()

    def _update_tree_horizontal_extent(self):
        if not hasattr(self, "tree"):
            return
        self.update_idletasks()
        try:
            text_font = tkfont.nametofont("TkTextFont")
        except tk.TclError:
            text_font = tkfont.nametofont("TkDefaultFont")
        max_px = 180
        for nb_iid in self.tree.get_children(""):
            nb_text = self.tree.item(nb_iid, "text") or ""
            max_px = max(max_px, text_font.measure(nb_text) + 32)
            for sec_iid in self.tree.get_children(nb_iid):
                sec_text = self.tree.item(sec_iid, "text") or ""
                # Add indentation/expand icon space for section rows.
                max_px = max(max_px, text_font.measure(sec_text) + 72)
        self.tree.column("#0", width=max_px, minwidth=max_px, stretch=False)

    def _cache_base_fonts(self):
        font_names = (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
            "TkFixedFont",
        )
        for name in font_names:
            try:
                f = tkfont.nametofont(name)
                self.base_font_sizes[name] = abs(int(f.cget("size")))
            except (tk.TclError, ValueError):
                continue
        rowheight = self.style.lookup("Treeview", "rowheight")
        try:
            self.base_treeview_rowheight = int(rowheight)
        except (TypeError, ValueError):
            self.base_treeview_rowheight = 20

    def apply_ui_scale(self, scale_name: str, persist: bool = True):
        name = str(scale_name).strip().lower()
        if name not in (UI_SCALE_NORMAL, UI_SCALE_LARGE):
            name = UI_SCALE_NORMAL
        self.ui_scale_var.set(name)
        factor = 1.15 if name == UI_SCALE_LARGE else 1.0
        for font_name, base_size in self.base_font_sizes.items():
            try:
                scaled = max(8, int(round(base_size * factor)))
                tkfont.nametofont(font_name).configure(size=scaled)
            except tk.TclError:
                continue
        rowheight = max(18, int(round(self.base_treeview_rowheight * factor)))
        self.style.configure("Treeview", rowheight=rowheight)
        self.update_idletasks()
        self._update_tree_horizontal_extent()
        if persist:
            self.config_data["ui_scale"] = name
            self._save_config(self.config_data)

    def _theme_palette(self, theme_name: str) -> dict:
        if theme_name == THEME_DARK:
            return {
                "window_bg": "#0f172a",
                "panel_bg": "#111827",
                "text": "#e5e7eb",
                "muted_text": "#94a3b8",
                "entry_bg": "#1f2937",
                "entry_fg": "#f9fafb",
                "canvas_bg": "#0b1220",
                "paper_bg": "#111827",
                "paper_outline": "#334155",
                "select_bg": "#2563eb",
                "select_fg": "#ffffff",
            }
        return {
            "window_bg": "#f3f4f6",
            "panel_bg": "#f9fafb",
            "text": "#111827",
            "muted_text": "#4b5563",
            "entry_bg": "#ffffff",
            "entry_fg": "#111827",
            "canvas_bg": "#f7f7f7",
            "paper_bg": "#ffffff",
            "paper_outline": "#d1d5db",
            "select_bg": "#2563eb",
            "select_fg": "#ffffff",
        }

    def apply_theme(self, theme_name: str, persist: bool = True):
        name = str(theme_name).strip().lower()
        if name not in (THEME_LIGHT, THEME_DARK):
            name = THEME_LIGHT
        self.theme_var.set(name)
        colors = self._theme_palette(name)
        self.current_theme_colors = colors

        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.configure(bg=colors["window_bg"])
        self.style.configure(".", background=colors["panel_bg"], foreground=colors["text"])
        self.style.configure("TFrame", background=colors["panel_bg"])
        self.style.configure("TLabel", background=colors["panel_bg"], foreground=colors["text"])
        self.style.configure("TButton", background=colors["panel_bg"], foreground=colors["text"])
        self.style.configure("TRadiobutton", background=colors["panel_bg"], foreground=colors["text"])
        self.style.configure("TCheckbutton", background=colors["panel_bg"], foreground=colors["text"])
        self.style.configure("TEntry", fieldbackground=colors["entry_bg"], foreground=colors["entry_fg"])
        self.style.configure("TSpinbox", fieldbackground=colors["entry_bg"], foreground=colors["entry_fg"])
        self.style.configure(
            "Treeview",
            background=colors["entry_bg"],
            fieldbackground=colors["entry_bg"],
            foreground=colors["entry_fg"],
        )
        self.style.map(
            "Treeview",
            background=[("selected", colors["select_bg"])],
            foreground=[("selected", colors["select_fg"])],
        )

        if hasattr(self, "pages_list"):
            self.pages_list.configure(
                bg=colors["entry_bg"],
                fg=colors["entry_fg"],
                selectbackground=colors["select_bg"],
                selectforeground=colors["select_fg"],
                highlightbackground=colors["paper_outline"],
                highlightcolor=colors["paper_outline"],
            )
        if hasattr(self, "page_canvas"):
            self.page_canvas.configure(bg=colors["canvas_bg"])
            self.page_canvas.itemconfigure("inkbg", fill=colors["paper_bg"], outline=colors["paper_outline"])
            self._update_page_ready_state()
        for holder in getattr(self, "ink_text_widgets", {}).values():
            widget = holder.get("widget")
            if widget:
                self._style_text_widget(widget)
        self._configure_tree_highlight_tags()
        self._apply_tree_selection_tags()

        if persist:
            self.config_data["theme"] = name
            self._save_config(self.config_data)

    def _setup_text_tags(self):
        if not self.editor:
            return
        base_font = tkfont.nametofont("TkTextFont")
        bold_font = tkfont.Font(self.editor, base_font)
        bold_font.configure(weight="bold")
        italic_font = tkfont.Font(self.editor, base_font)
        italic_font.configure(slant="italic")
        underline_font = tkfont.Font(self.editor, base_font)
        underline_font.configure(underline=True)

        self.editor.tag_configure("bold", font=bold_font)
        self.editor.tag_configure("italic", font=italic_font)
        self.editor.tag_configure("underline", font=underline_font)
        self.editor.tag_configure("highlight", background="#fff3a3")

    def apply_text_tag(self, tag_name: str):
        if not self.editor:
            return
        try:
            start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
        except tk.TclError:
            return

        if tag_name in self.editor.tag_names("sel.first"):
            self.editor.tag_remove(tag_name, start, end)
        else:
            self.editor.tag_add(tag_name, start, end)
        self._queue_autosave()

    def _show_loading(self, message: str = "Loading page...", determinate: bool = False, total_steps: int = 100):
        self.loading_depth += 1
        if self.loading_depth == 1:
            self.loading_base_message = message
            self.loading_mode = "determinate" if determinate else "indeterminate"
            self.loading_total_steps = max(1, int(total_steps)) if determinate else 0
            self.loading_current_step = 0
            self.loading_text_var.set(message)
            self.loading_label.pack(side=tk.RIGHT, padx=(8, 4))
            self.loading_bar.pack(side=tk.RIGHT, padx=(0, 8))
            if self.loading_mode == "determinate":
                self.loading_bar.configure(mode="determinate", maximum=self.loading_total_steps, value=0)
            else:
                self.loading_bar.configure(mode="indeterminate", maximum=100, value=0)
                self.loading_bar.start(12)
            self.update_idletasks()

    def _advance_loading(self, steps: int = 1, message: str | None = None):
        if self.loading_depth <= 0:
            return
        if self.loading_mode != "determinate":
            return
        self.loading_current_step = min(self.loading_total_steps, self.loading_current_step + max(1, int(steps)))
        self.loading_bar.configure(value=self.loading_current_step)
        base = message or self.loading_base_message or "Loading..."
        percent = int((self.loading_current_step * 100) / max(1, self.loading_total_steps))
        self.loading_text_var.set(f"{base} {percent}%")
        self.update_idletasks()

    def _hide_loading(self):
        if self.loading_depth <= 0:
            self.loading_depth = 0
            return
        self.loading_depth -= 1
        if self.loading_depth == 0:
            if self.loading_mode == "indeterminate":
                self.loading_bar.stop()
            else:
                self.loading_bar.configure(value=self.loading_total_steps if self.loading_total_steps else 0)
            self.loading_bar.pack_forget()
            self.loading_label.pack_forget()
            self.loading_text_var.set("")
            self.loading_base_message = ""
            self.loading_total_steps = 0
            self.loading_current_step = 0
            self.loading_mode = "indeterminate"
            self.update_idletasks()

    def set_ink_color(self, color: str):
        safe_color = self._safe_pen_color(color)
        self.pen_color = safe_color
        if self.current_tool.get() == "eraser":
            self.current_tool.set("pen")
        if self.config_data.get("pen_color") != safe_color:
            self.config_data["pen_color"] = safe_color
            self._save_config(self.config_data)

    def pick_ink_color(self):
        chosen = colorchooser.askcolor(color=self.pen_color, title="Choose Ink Color", parent=self)
        if chosen and chosen[1]:
            self.set_ink_color(chosen[1])

    def clear_ink(self):
        if not self._page_ready():
            return
        self.ink_strokes = []
        self.redo_strokes = []
        self.ink_images = []
        self.ink_texts = []
        self.ink_text_widgets = {}
        self.ink_image_cache = {}
        self.ink_image_items = {}
        self._clear_image_selection()
        self.current_stroke = None
        self.current_stroke_item = None
        self.current_raw_point = None
        self.current_eraser_point = None
        self.last_stroke_end_point = None
        self.last_stroke_end_time = 0.0
        self.ink_canvas.delete("inkstroke")
        self.ink_canvas.delete("ink_image")
        self._queue_autosave()

    def _redraw_strokes_only(self):
        self.ink_canvas.delete("inkstroke")
        for stroke in self.ink_strokes:
            self._draw_stroke(stroke)

    def undo_stroke(self):
        if not self._page_ready() or not self.ink_strokes:
            return
        self.redo_strokes.append(self.ink_strokes.pop())
        self._redraw_strokes_only()
        self._queue_autosave()

    def redo_stroke(self):
        if not self._page_ready() or not self.redo_strokes:
            return
        self.ink_strokes.append(self.redo_strokes.pop())
        self._redraw_strokes_only()
        self._queue_autosave()

    def on_ink_press(self, event):
        if self.is_loading_page or not self._page_ready():
            return
        raw_x = int(self.ink_canvas.canvasx(event.x))
        raw_y = int(self.ink_canvas.canvasy(event.y))
        x, y = self._clamp_to_page_bounds(raw_x, raw_y)
        self.canvas_cursor = (x, y)
        self.ink_canvas.focus_set()
        hit_image_id = self._image_id_at(raw_x, raw_y)
        if hit_image_id:
            self._select_image(hit_image_id)
            self.dragging_image_id = hit_image_id
            item_id = self.ink_image_items.get(hit_image_id)
            if not item_id:
                return
            item_x, item_y = self.ink_canvas.coords(item_id)
            self.dragging_offset = (x - int(item_x), y - int(item_y))
            return
        self._clear_image_selection()
        if not self._inside_page_bounds(raw_x, raw_y):
            return
        if self.current_tool.get() == "eraser":
            self.current_stroke = None
            self.current_raw_point = None
            self.current_eraser_point = [x, y]
            self._erase_at_point(x, y)
            return
        tool = self.current_tool.get()
        base_width = int(self.pen_size_var.get())
        pressure = self._read_event_pressure(event)
        width = self._stroke_width_for_tool(tool, base_width, pressure)
        points = [[x, y]]
        now = time.monotonic()
        if self.last_stroke_end_point and (now - self.last_stroke_end_time) <= INK_STROKE_CONTINUE_WINDOW_SEC:
            px, py = self.last_stroke_end_point
            if ((x - px) * (x - px) + (y - py) * (y - py)) <= (INK_STROKE_CONTINUE_DISTANCE * INK_STROKE_CONTINUE_DISTANCE):
                if px != x or py != y:
                    points = [[px, py], [x, y]]
        pressures = [pressure if pressure is not None else 0.5] * len(points)
        self.current_stroke = {
            "tool": tool,
            "color": self.pen_color,
            "base_width": base_width,
            "width": width,
            "points": points,
            "pressures": pressures,
        }
        render_color = self._stroke_render_color(self.current_stroke)
        flat = []
        for px, py in points:
            flat.extend((px, py))
        if len(flat) < 4:
            flat.extend((x, y))
        self.current_stroke_item = self.ink_canvas.create_line(
            *flat,
            fill=render_color,
            width=self.current_stroke["width"],
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
            smooth=True,
            splinesteps=24,
            tags=("inkstroke", "currentstroke"),
        )
        self.current_raw_point = [x, y]

    def on_ink_drag(self, event):
        if not self._page_ready():
            return
        raw_x = int(self.ink_canvas.canvasx(event.x))
        raw_y = int(self.ink_canvas.canvasy(event.y))
        x, y = self._clamp_to_page_bounds(raw_x, raw_y)
        self.canvas_cursor = (x, y)
        if self.dragging_image_id:
            self._move_image(self.dragging_image_id, x - self.dragging_offset[0], y - self.dragging_offset[1])
            return
        if self.current_tool.get() == "eraser":
            if self.current_eraser_point is None:
                self.current_eraser_point = [x, y]
            sx, sy = self.current_eraser_point
            self._erase_along_path(sx, sy, x, y)
            self.current_eraser_point = [x, y]
            return
        if not self.current_stroke:
            return
        pressure = self._read_event_pressure(event)
        if self.current_raw_point:
            raw_dx = x - self.current_raw_point[0]
            raw_dy = y - self.current_raw_point[1]
            if abs(raw_dx) + abs(raw_dy) < INK_MIN_POINT_DELTA:
                return
        self.current_raw_point = [x, y]
        points = self.current_stroke["points"]
        prev_len = len(points)
        last_x, last_y = points[-1]
        smoothed_x = int((last_x * (1.0 - INK_SMOOTHING_ALPHA)) + (x * INK_SMOOTHING_ALPHA))
        smoothed_y = int((last_y * (1.0 - INK_SMOOTHING_ALPHA)) + (y * INK_SMOOTHING_ALPHA))
        dx = smoothed_x - last_x
        dy = smoothed_y - last_y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= 0.0:
            return
        steps = max(1, int(dist / INK_INTERPOLATION_STEP))
        for i in range(1, steps + 1):
            ix = int(last_x + (dx * i / steps))
            iy = int(last_y + (dy * i / steps))
            if ix != points[-1][0] or iy != points[-1][1]:
                points.append([ix, iy])
        if pressure is None:
            pressure = self.current_stroke.get("pressures", [0.5])[-1] if self.current_stroke.get("pressures") else 0.5
        added = len(points) - prev_len
        if added > 0:
            self.current_stroke.setdefault("pressures", []).extend([pressure] * added)
        if self.current_stroke.get("tool") == "pen":
            base = int(self.current_stroke.get("base_width", self.pen_size_var.get()))
            target_width = self._stroke_width_for_tool("pen", base, pressure)
            current_width = float(self.current_stroke.get("width", base))
            self.current_stroke["width"] = (current_width * 0.65) + (target_width * 0.35)
        if len(points) <= 1 or len(points) == prev_len:
            return
        flat = []
        for px, py in points:
            flat.extend((px, py))
        if self.current_stroke_item is None:
            self.current_stroke_item = self.ink_canvas.create_line(
                *flat,
                fill=self.current_stroke["color"],
                width=self.current_stroke["width"],
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                smooth=True,
                splinesteps=24,
                tags=("inkstroke", "currentstroke"),
            )
        else:
            self.ink_canvas.coords(self.current_stroke_item, *flat)
            self.ink_canvas.itemconfigure(self.current_stroke_item, width=self.current_stroke["width"])

    def on_ink_release(self, event):
        if not self._page_ready():
            return
        raw_x = int(self.ink_canvas.canvasx(event.x))
        raw_y = int(self.ink_canvas.canvasy(event.y))
        x, y = self._clamp_to_page_bounds(raw_x, raw_y)
        self.canvas_cursor = (x, y)
        if self.dragging_image_id:
            self.dragging_image_id = None
            self._queue_autosave()
            return
        if self.current_tool.get() == "eraser":
            self.current_stroke = None
            self.current_raw_point = None
            self.current_eraser_point = None
            self.last_stroke_end_point = None
            return
        if not self.current_stroke:
            return
        self._append_smoothed_point(x, y, INK_RELEASE_ALPHA)
        points = self.current_stroke["points"]
        render_color = self._stroke_render_color(self.current_stroke)
        if len(points) == 1:
            x, y = points[0]
            half = max(1, self.current_stroke["width"] // 2)
            self.current_stroke_item = self.ink_canvas.create_oval(
                x - half,
                y - half,
                x + half,
                y + half,
                outline=render_color,
                fill=render_color,
                tags=("inkstroke",),
            )
        else:
            self.ink_canvas.dtag("currentstroke", "currentstroke")
        self.ink_strokes.append(self.current_stroke)
        self.redo_strokes = []
        self.last_stroke_end_point = list(points[-1]) if points else None
        self.last_stroke_end_time = time.monotonic()
        self.current_stroke = None
        self.current_stroke_item = None
        self.current_raw_point = None
        self._queue_autosave()

    def _append_smoothed_point(self, x: int, y: int, alpha: float):
        if not self.current_stroke:
            return
        points = self.current_stroke["points"]
        if not points:
            points.append([x, y])
            return
        prev_len = len(points)
        last_x, last_y = points[-1]
        smoothed_x = int((last_x * (1.0 - alpha)) + (x * alpha))
        smoothed_y = int((last_y * (1.0 - alpha)) + (y * alpha))
        dx = smoothed_x - last_x
        dy = smoothed_y - last_y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= 0.0:
            return
        steps = max(1, int(dist / INK_INTERPOLATION_STEP))
        for i in range(1, steps + 1):
            ix = int(last_x + (dx * i / steps))
            iy = int(last_y + (dy * i / steps))
            if ix != points[-1][0] or iy != points[-1][1]:
                points.append([ix, iy])
        added = len(points) - prev_len
        if added > 0:
            pressures = self.current_stroke.setdefault("pressures", [])
            tail_pressure = pressures[-1] if pressures else 0.5
            pressures.extend([tail_pressure] * added)
        if len(points) <= prev_len:
            return
        flat = []
        for px, py in points:
            flat.extend((px, py))
        if self.current_stroke_item is not None:
            self.ink_canvas.coords(self.current_stroke_item, *flat)

    def _image_id_at(self, x: int, y: int):
        if not self.ink_images:
            return None
        for meta in reversed(self.ink_images):
            image_id = meta.get("id")
            item_id = self.ink_image_items.get(image_id)
            if not item_id:
                continue
            bbox = self.ink_canvas.bbox(item_id)
            if not bbox:
                continue
            if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return image_id
        return None

    def _move_image(self, image_id: str, x: int, y: int):
        item_id = self.ink_image_items.get(image_id)
        if not item_id:
            return
        bbox = self.ink_canvas.bbox(item_id)
        if bbox:
            width = max(1, int(bbox[2] - bbox[0]))
            height = max(1, int(bbox[3] - bbox[1]))
            x, y = self._clamp_image_position(int(x), int(y), width, height)
        self.ink_canvas.coords(item_id, x, y)
        self._raise_ink_layers()
        for img in self.ink_images:
            if img.get("id") == image_id:
                img["x"] = x
                img["y"] = y
                break
        self._update_selected_image_outline()

    def _erase_strokes_at(self, x: int, y: int, queue_save: bool = True) -> bool:
        radius = max(8, int(self.pen_size_var.get()) * 2)
        radius_sq = radius * radius
        changed = False
        rebuilt: list[dict] = []
        for stroke in self.ink_strokes:
            split_parts, stroke_changed = self._split_stroke_by_eraser(stroke, x, y, radius_sq)
            rebuilt.extend(split_parts)
            changed = changed or stroke_changed

        if changed:
            self.ink_strokes = rebuilt
            self.redo_strokes = []
            self.ink_canvas.delete("inkstroke")
            for stroke in self.ink_strokes:
                self._draw_stroke(stroke)
            if queue_save:
                self._queue_autosave()
            return True
        return False

    def _erase_strokes_whole_at(self, x: int, y: int, queue_save: bool = True) -> bool:
        radius = max(8, int(self.pen_size_var.get()) * 2)
        radius_sq = radius * radius
        kept = []
        changed = False
        for stroke in self.ink_strokes:
            points = stroke.get("points", [])
            if not points:
                continue
            hit = False
            if len(points) == 1:
                px, py = points[0]
                hit = ((px - x) * (px - x) + (py - y) * (py - y)) <= radius_sq
            else:
                for i in range(1, len(points)):
                    x1, y1 = points[i - 1]
                    x2, y2 = points[i]
                    if self._distance_sq_point_to_segment(x, y, x1, y1, x2, y2) <= radius_sq:
                        hit = True
                        break
            if hit:
                changed = True
            else:
                kept.append(stroke)
        if changed:
            self.ink_strokes = kept
            self.redo_strokes = []
            self.ink_canvas.delete("inkstroke")
            for stroke in self.ink_strokes:
                self._draw_stroke(stroke)
            if queue_save:
                self._queue_autosave()
            return True
        return False

    def _erase_at_point(self, x: int, y: int, queue_save: bool = True) -> bool:
        if self.eraser_mode_var.get() == ERASER_MODE_STROKE:
            return self._erase_strokes_whole_at(x, y, queue_save=queue_save)
        return self._erase_strokes_at(x, y, queue_save=queue_save)

    def _split_stroke_by_eraser(self, stroke: dict, x: int, y: int, radius_sq: int) -> tuple[list[dict], bool]:
        points = stroke.get("points", [])
        if not points:
            return [], False

        def point_inside(px: int, py: int) -> bool:
            return ((px - x) * (px - x) + (py - y) * (py - y)) <= radius_sq

        pressures = stroke.get("pressures", [])
        has_pressures = isinstance(pressures, list) and len(pressures) == len(points)

        if len(points) == 1:
            px, py = points[0]
            if point_inside(px, py):
                return [], True
            return [stroke], False

        chunks: list[tuple[list[list[int]], list[float]]] = []
        current_points: list[list[int]] = []
        current_pressures: list[float] = []
        removed_any = False

        for idx, pt in enumerate(points):
            px, py = int(pt[0]), int(pt[1])
            inside = point_inside(px, py)
            if inside:
                removed_any = True
                if current_points:
                    chunks.append((current_points, current_pressures))
                    current_points = []
                    current_pressures = []
                continue
            current_points.append([px, py])
            if has_pressures:
                current_pressures.append(float(pressures[idx]))
            else:
                current_pressures.append(0.5)

        if current_points:
            chunks.append((current_points, current_pressures))

        if not removed_any:
            return [stroke], False

        out: list[dict] = []
        for chunk_points, chunk_pressures in chunks:
            if not chunk_points:
                continue
            part = dict(stroke)
            part["points"] = chunk_points
            if has_pressures:
                part["pressures"] = chunk_pressures
            out.append(part)
        return out, True

    def _erase_along_path(self, x1: int, y1: int, x2: int, y2: int):
        dx = x2 - x1
        dy = y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= 0.0:
            self._erase_at_point(x2, y2)
            return
        steps = max(1, int(dist / ERASER_INTERPOLATION_STEP))
        changed = False
        for i in range(1, steps + 1):
            px = int(x1 + (dx * i / steps))
            py = int(y1 + (dy * i / steps))
            if self._erase_at_point(px, py, queue_save=False):
                changed = True
        if changed:
            self._queue_autosave()

    @staticmethod
    def _distance_sq_point_to_segment(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return (px - x1) * (px - x1) + (py - y1) * (py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / float(dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        cx = x1 + t * dx
        cy = y1 + t * dy
        return (px - cx) * (px - cx) + (py - cy) * (py - cy)

    def _on_ink_mousewheel(self, event):
        self.ink_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_canvas_motion(self, event):
        self.canvas_cursor = (int(self.ink_canvas.canvasx(event.x)), int(self.ink_canvas.canvasy(event.y)))

    def _cursor_canvas_position(self):
        return self.canvas_cursor

    def on_canvas_keypress(self, event):
        if not self._page_ready():
            return
        if event.state & 0x4:
            return
        if not event.char or not event.char.isprintable():
            return
        widget = self.focus_get()
        if isinstance(widget, tk.Text):
            return
        x, y = self._cursor_canvas_position()
        x, y = self._clamp_to_page_bounds(x, y)
        text_id = self._create_text_block(x, y, event.char)
        self._focus_text_block(text_id, to_end=True)
        self._queue_autosave()
        return "break"

    def _create_text_block(
        self,
        x: int,
        y: int,
        text: str = "",
        text_id: str | None = None,
        width_px: int = 320,
        height_px: int = 30,
    ) -> str:
        text_id = text_id or uuid.uuid4().hex[:10]
        width_px = max(120, int(width_px))
        height_px = max(24, int(height_px))
        x, y = self._clamp_image_position(int(x), int(y), width_px, height_px)
        widget = tk.Text(
            self.ink_canvas,
            wrap=tk.WORD,
            relief=tk.FLAT,
            borderwidth=1,
            highlightthickness=1,
            undo=True,
            font=tkfont.nametofont("TkTextFont"),
        )
        widget.insert("1.0", text)
        window_id = self.ink_canvas.create_window(
            x,
            y,
            anchor=tk.NW,
            width=width_px,
            height=height_px,
            window=widget,
            tags=("ink_text", f"inktxt:{text_id}"),
        )
        self.ink_text_widgets[text_id] = {"widget": widget, "item_id": window_id}
        self.ink_texts = [t for t in self.ink_texts if t.get("id") != text_id]
        self.ink_texts.append({"id": text_id, "x": x, "y": y, "w": width_px, "h": height_px, "text": text})

        widget.bind("<ButtonPress-1>", lambda e, tid=text_id: self._on_text_block_press(e, tid))
        widget.bind("<B1-Motion>", lambda e, tid=text_id: self._on_text_block_drag(e, tid))
        widget.bind("<ButtonRelease-1>", lambda e, tid=text_id: self._on_text_block_release(e, tid))
        widget.bind("<KeyRelease>", lambda _e, tid=text_id: self._on_text_block_change(tid))
        widget.bind("<FocusOut>", lambda _e, tid=text_id: self._sync_text_block_meta(tid))
        self._style_text_widget(widget)
        self._autosize_text_widget(text_id)
        return text_id

    def _focus_text_block(self, text_id: str, to_end: bool = False):
        holder = self.ink_text_widgets.get(text_id)
        if not holder:
            return
        widget = holder.get("widget")
        if not widget:
            return
        widget.focus_set()
        if to_end:
            widget.mark_set("insert", "end-1c")

    def _on_text_block_press(self, event, text_id: str):
        self._focus_text_block(text_id)
        holder = self.ink_text_widgets.get(text_id)
        if not holder:
            return
        widget = holder.get("widget")
        if not widget:
            return
        width = max(1, int(widget.winfo_width()))
        height = max(1, int(widget.winfo_height()))
        edge_zone = 8
        near_edge = (
            event.x <= edge_zone
            or event.y <= edge_zone
            or event.x >= (width - edge_zone)
            or event.y >= (height - edge_zone)
        )
        if not near_edge:
            self.dragging_text_id = None
            return
        item_id = holder.get("item_id")
        coords = self.ink_canvas.coords(item_id)
        if not coords:
            self.dragging_text_id = None
            return
        cx, cy = coords[0], coords[1]
        canvas_x = self.ink_canvas.canvasx(event.x_root - self.ink_canvas.winfo_rootx())
        canvas_y = self.ink_canvas.canvasy(event.y_root - self.ink_canvas.winfo_rooty())
        self.dragging_text_id = text_id
        self.dragging_text_offset = (canvas_x - cx, canvas_y - cy)
        return "break"

    def _on_text_block_drag(self, event, text_id: str):
        if self.dragging_text_id != text_id:
            return
        holder = self.ink_text_widgets.get(text_id)
        if not holder:
            return "break"
        item_id = holder.get("item_id")
        if not item_id:
            return "break"
        bbox = self.ink_canvas.bbox(item_id)
        width = 320
        height = 30
        if bbox:
            width = max(1, bbox[2] - bbox[0])
            height = max(1, bbox[3] - bbox[1])
        canvas_x = self.ink_canvas.canvasx(event.x_root - self.ink_canvas.winfo_rootx())
        canvas_y = self.ink_canvas.canvasy(event.y_root - self.ink_canvas.winfo_rooty())
        new_x = int(canvas_x - self.dragging_text_offset[0])
        new_y = int(canvas_y - self.dragging_text_offset[1])
        clamped_x, clamped_y = self._clamp_image_position(new_x, new_y, width, height)
        self.ink_canvas.coords(item_id, clamped_x, clamped_y)
        self._sync_text_block_meta(text_id)
        return "break"

    def _on_text_block_release(self, _event, text_id: str):
        if self.dragging_text_id != text_id:
            return
        self.dragging_text_id = None
        self.dragging_text_offset = (0, 0)
        self._sync_text_block_meta(text_id)
        self._queue_autosave()
        return "break"

    def _style_text_widget(self, widget: tk.Text):
        colors = self.current_theme_colors or self._theme_palette(self.theme_var.get())
        widget.configure(
            bg=colors.get("paper_bg", "#ffffff"),
            fg=colors.get("entry_fg", "#111827"),
            insertbackground=colors.get("entry_fg", "#111827"),
            selectbackground=colors.get("select_bg", "#2563eb"),
            selectforeground=colors.get("select_fg", "#ffffff"),
            highlightbackground=colors.get("paper_outline", "#d1d5db"),
            highlightcolor=colors.get("select_bg", "#2563eb"),
        )

    def _on_text_block_change(self, text_id: str):
        self._autosize_text_widget(text_id)
        self._sync_text_block_meta(text_id)
        self._queue_autosave()

    def _autosize_text_widget(self, text_id: str):
        holder = self.ink_text_widgets.get(text_id)
        if not holder:
            return
        widget = holder["widget"]
        item_id = holder["item_id"]
        try:
            content = widget.get("1.0", "end-1c")
            lines = max(1, int(widget.index("end-1c").split(".")[0]))
        except tk.TclError:
            return
        font = tkfont.nametofont("TkTextFont")
        line_h = max(16, font.metrics("linespace"))
        desired_h = max(24, min(800, (lines * line_h) + 10))
        bbox = self.ink_canvas.bbox(item_id)
        width_px = 320
        if bbox:
            width_px = max(120, bbox[2] - bbox[0])
        x, y = self.ink_canvas.coords(item_id)
        x2, y2 = self._clamp_image_position(int(x), int(y), width_px, desired_h)
        self.ink_canvas.coords(item_id, x2, y2)
        self.ink_canvas.itemconfigure(item_id, width=width_px, height=desired_h)
        self._upsert_text_meta(text_id, x2, y2, width_px, desired_h, content)

    def _upsert_text_meta(self, text_id: str, x: int, y: int, w: int, h: int, text: str):
        found = False
        for meta in self.ink_texts:
            if meta.get("id") == text_id:
                meta.update({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "text": text})
                found = True
                break
        if not found:
            self.ink_texts.append({"id": text_id, "x": int(x), "y": int(y), "w": int(w), "h": int(h), "text": text})

    def _sync_text_block_meta(self, text_id: str):
        holder = self.ink_text_widgets.get(text_id)
        if not holder:
            return
        widget = holder["widget"]
        item_id = holder["item_id"]
        try:
            text = widget.get("1.0", "end-1c")
        except tk.TclError:
            text = ""
        bbox = self.ink_canvas.bbox(item_id)
        if not bbox:
            return
        self._upsert_text_meta(text_id, bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1], text)

    def _clear_text_blocks(self):
        for holder in self.ink_text_widgets.values():
            widget = holder.get("widget")
            item_id = holder.get("item_id")
            if item_id:
                self.ink_canvas.delete(item_id)
            if widget:
                try:
                    widget.destroy()
                except tk.TclError:
                    pass
        self.ink_text_widgets = {}
        self.ink_texts = []

    def _clamp_image_position(self, x: int, y: int, width: int, height: int) -> tuple[int, int]:
        left, top, right, bottom = self.page_bounds
        max_x = max(left, right - max(1, width))
        max_y = max(top, bottom - max(1, height))
        return max(left, min(max_x, x)), max(top, min(max_y, y))

    def insert_image_at_cursor(self):
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            messagebox.showinfo("Info", "Select a page first.")
            return
        if not PIL_AVAILABLE:
            messagebox.showwarning("Image Disabled", "Image insert requires Pillow.\nRun: python -m pip install pillow")
            return
        path = filedialog.askopenfilename(
            title="Insert image",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        asset = self.storage.import_page_asset(
            self.selected_notebook_id, self.selected_section_id, self.selected_page_id, Path(path)
        )
        x, y = self._cursor_canvas_position()
        x, y = self._clamp_to_page_bounds(x, y)
        image_meta = {"id": uuid.uuid4().hex[:10], "asset": asset, "x": x, "y": y}
        self.ink_images.append(image_meta)
        self._draw_canvas_image(image_meta)
        self._select_image(image_meta["id"])
        self._queue_autosave()

    def paste_image_from_clipboard(self):
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            return
        if not PIL_AVAILABLE:
            return
        try:
            grabbed = ImageGrab.grabclipboard()
        except Exception:
            return
        if grabbed is None:
            return

        asset = None
        if isinstance(grabbed, list):
            for item in grabbed:
                p = Path(str(item))
                if p.exists() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
                    asset = self.storage.import_page_asset(
                        self.selected_notebook_id, self.selected_section_id, self.selected_page_id, p
                    )
                    break
        elif hasattr(grabbed, "save"):
            pil_image = grabbed.convert("RGBA")
            asset = self.storage.save_page_asset_image(
                self.selected_notebook_id, self.selected_section_id, self.selected_page_id, pil_image, ext=".png"
            )
        if not asset:
            return

        x, y = self._cursor_canvas_position()
        x, y = self._clamp_to_page_bounds(x, y)
        image_meta = {"id": uuid.uuid4().hex[:10], "asset": asset, "x": x, "y": y}
        self.ink_images.append(image_meta)
        self._draw_canvas_image(image_meta)
        self._select_image(image_meta["id"])
        self._queue_autosave()

    def _draw_canvas_image(self, image_meta: dict):
        if not PIL_AVAILABLE:
            return
        image_id = image_meta.get("id")
        asset = image_meta.get("asset")
        if not image_id or not asset:
            return
        asset_path = self.storage.page_asset_path(
            self.selected_notebook_id, self.selected_section_id, self.selected_page_id, asset
        )
        if not asset_path.exists():
            return
        with Image.open(asset_path) as opened:
            pil_image = opened.convert("RGBA")
        max_side = 1200
        if pil_image.width > max_side or pil_image.height > max_side:
            pil_image.thumbnail((max_side, max_side))
        tk_image = ImageTk.PhotoImage(pil_image)
        self.ink_image_cache[image_id] = tk_image
        x = int(image_meta.get("x", 50))
        y = int(image_meta.get("y", 50))
        x, y = self._clamp_image_position(x, y, tk_image.width(), tk_image.height())
        image_meta["x"] = x
        image_meta["y"] = y
        item_id = self.ink_canvas.create_image(
            x, y, image=tk_image, anchor=tk.NW, tags=("ink_image", f"inkimg:{image_id}")
        )
        self.ink_image_items[image_id] = item_id
        self._raise_ink_layers()
        self.update_idletasks()

    def _select_image(self, image_id: str):
        self.selected_image_id = image_id
        self._update_selected_image_outline()

    def _clear_image_selection(self):
        self.selected_image_id = None
        if self.selected_image_outline:
            self.ink_canvas.delete(self.selected_image_outline)
            self.selected_image_outline = None

    def _update_selected_image_outline(self):
        if self.selected_image_outline:
            self.ink_canvas.delete(self.selected_image_outline)
            self.selected_image_outline = None
        if not self.selected_image_id:
            return
        item_id = self.ink_image_items.get(self.selected_image_id)
        if not item_id:
            return
        bbox = self.ink_canvas.bbox(item_id)
        if not bbox:
            return
        self.selected_image_outline = self.ink_canvas.create_rectangle(
            bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2, outline="#2563eb", width=2, dash=(4, 2)
        )
        self.ink_canvas.tag_raise(self.selected_image_outline)

    def delete_selected_image(self):
        if not self._page_ready():
            return
        if not self.selected_image_id:
            return
        target = self.selected_image_id
        item_id = self.ink_image_items.pop(target, None)
        if item_id:
            self.ink_canvas.delete(item_id)
        self.ink_images = [img for img in self.ink_images if img.get("id") != target]
        self._clear_image_selection()
        self._queue_autosave()

    def _draw_stroke(self, stroke: dict):
        points = stroke.get("points", [])
        color = self._stroke_render_color(stroke)
        width = max(1, float(stroke.get("width", 2)))
        if len(points) == 1:
            x, y = points[0]
            half = max(1, int(width // 2))
            self.ink_canvas.create_oval(
                x - half, y - half, x + half, y + half, outline=color, fill=color, tags=("inkstroke",)
            )
            self._raise_ink_layers()
            return
        if len(points) < 2:
            return
        flattened = []
        for x, y in points:
            flattened.extend((x, y))
        self.ink_canvas.create_line(
            *flattened,
            fill=color,
            width=width,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
            smooth=True,
            splinesteps=36,
            tags=("inkstroke",),
        )
        self._raise_ink_layers()

    def _raise_ink_layers(self):
        self.ink_canvas.tag_raise("ink_image")
        self.ink_canvas.tag_raise("inkstroke")
        if self.selected_image_outline:
            self.ink_canvas.tag_raise(self.selected_image_outline)

    def _load_ink_for_current_page(self, payload: dict | None = None):
        self.ink_canvas.delete("inkstroke")
        self.ink_canvas.delete("ink_image")
        self._clear_text_blocks()
        self.ink_strokes = []
        self.redo_strokes = []
        self.ink_images = []
        self.ink_texts = []
        self.ink_image_cache = {}
        self.ink_image_items = {}
        self._clear_image_selection()
        self.current_stroke = None
        self.current_stroke_item = None
        self.current_raw_point = None
        self.current_eraser_point = None
        self.last_stroke_end_point = None
        self.last_stroke_end_time = 0.0
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            return
        if payload is None:
            payload = self.storage.load_ink_payload(self.selected_notebook_id, self.selected_section_id, self.selected_page_id)
        self.ink_strokes = payload.get("strokes", [])
        self.ink_images = payload.get("images", [])
        self.ink_texts = payload.get("texts", [])
        for i, stroke in enumerate(self.ink_strokes):
            self._draw_stroke(stroke)
            self._advance_loading(1, "Loading strokes...")
            if i % 20 == 0:
                self.update_idletasks()
        for i, image_meta in enumerate(self.ink_images):
            self._draw_canvas_image(image_meta)
            self._advance_loading(1, "Loading images...")
            if i % 3 == 0:
                self.update_idletasks()
        for i, text_meta in enumerate(self.ink_texts):
            self._create_text_block(
                int(text_meta.get("x", 20)),
                int(text_meta.get("y", self.ink_start_y + 20)),
                text=str(text_meta.get("text", "")),
                text_id=str(text_meta.get("id", "")) or None,
                width_px=int(text_meta.get("w", 320)),
                height_px=int(text_meta.get("h", 30)),
            )
            self._advance_loading(1, "Loading texts...")
            if i % 5 == 0:
                self.update_idletasks()

    def _render_ink_image(self):
        region = self.ink_canvas.cget("scrollregion")
        if region:
            x0, y0, x1, y1 = [int(float(v)) for v in region.split()]
            width = max(1, x1 - x0)
            height = max(1, y1 - y0)
        else:
            width = max(1, self.ink_canvas.winfo_width())
            height = max(1, self.ink_canvas.winfo_height())
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        for image_meta in self.ink_images:
            asset = image_meta.get("asset")
            if not asset:
                continue
            asset_path = self.storage.page_asset_path(
                self.selected_notebook_id, self.selected_section_id, self.selected_page_id, asset
            )
            if not asset_path.exists():
                continue
            try:
                with Image.open(asset_path) as opened:
                    src = opened.convert("RGB")
                    image.paste(src, (int(image_meta.get("x", 0)), int(image_meta.get("y", 0))))
            except OSError:
                continue
        for stroke in self.ink_strokes:
            points = [tuple(p) for p in stroke.get("points", [])]
            color = self._stroke_render_color(stroke)
            line_width = max(1, int(stroke.get("width", 2)))
            if len(points) == 1:
                x, y = points[0]
                half = max(1, line_width // 2)
                draw.ellipse((x - half, y - half, x + half, y + half), fill=color, outline=color)
            elif len(points) > 1:
                draw.line(points, fill=color, width=line_width, joint="curve")
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        for text_meta in self._collect_canvas_texts():
            txt = str(text_meta.get("text", ""))
            if not txt:
                continue
            tx = int(text_meta.get("x", 0))
            ty = int(text_meta.get("y", 0))
            if font:
                draw.multiline_text((tx, ty), txt, fill="#111827", font=font, spacing=2)
            else:
                draw.multiline_text((tx, ty), txt, fill="#111827", spacing=2)
        return image

    def refresh_notebooks(self):
        self.tree.delete(*self.tree.get_children())
        for notebook in self.storage.list_notebooks():
            nb_node = self.tree.insert("", tk.END, iid=f"nb:{notebook['id']}", text=notebook["title"])
            for section in self.storage.list_sections(notebook["id"]):
                self.tree.insert(nb_node, tk.END, iid=f"sec:{notebook['id']}:{section['id']}", text=section["title"])
            self.tree.item(nb_node, open=True)
        self._update_tree_horizontal_extent()
        self._configure_tree_highlight_tags()
        self._restore_tree_selection()

    def on_tree_select(self, _event=None):
        self._sync_selection_context()
        self._apply_tree_selection_tags()
        self.refresh_pages()
        self._save_ui_state()

    @staticmethod
    def _move_before(items: list[str], source: str, target: str) -> list[str]:
        if source == target or source not in items or target not in items:
            return items
        out = list(items)
        out.remove(source)
        out.insert(out.index(target), source)
        return out

    def on_tree_drag_start(self, event):
        self.tree_drag_token = self.tree.identify_row(event.y)
        self.tree_drag_start_y = event.y
        self.tree_drag_active = False
        self._hide_tree_drag_indicator()
        self._hide_tree_drag_ghost()

    def on_tree_drag_motion(self, event):
        if self.tree_drag_start_y is None:
            return
        if abs(event.y - self.tree_drag_start_y) >= 4:
            self.tree_drag_active = True
        if not self.tree_drag_active:
            return
        self._update_tree_drag_indicator(event.y)
        self._show_tree_drag_ghost(event)

    def on_tree_drag_drop(self, event):
        source_token = self.tree_drag_token
        self.tree_drag_token = None
        drag_active = self.tree_drag_active
        self.tree_drag_active = False
        self.tree_drag_start_y = None
        self._hide_tree_drag_indicator()
        self._hide_tree_drag_ghost()
        if not drag_active:
            return
        if not source_token or not self.tree.exists(source_token):
            return
        target_token = self._nearest_tree_row(event.y)
        if not target_token or source_token == target_token:
            return
        source_parts = source_token.split(":")
        target_parts = target_token.split(":")
        if len(source_parts) < 2 or len(target_parts) < 2:
            return

        if source_parts[0] == "nb" and target_parts[0] == "nb":
            source_nb = source_parts[1]
            target_nb = target_parts[1]
            ordered = [nb["id"] for nb in self.storage.list_notebooks()]
            reordered = self._move_before(ordered, source_nb, target_nb)
            if reordered != ordered:
                self.storage.reorder_notebooks(reordered)
                self.refresh_notebooks()
                token = f"nb:{source_nb}"
                if self.tree.exists(token):
                    self.tree.selection_set(token)
                    self.tree.focus(token)
                    self.tree.see(token)
                self.on_tree_select()
            return

        if source_parts[0] == "sec" and target_parts[0] == "sec" and len(source_parts) == 3 and len(target_parts) == 3:
            source_nb, source_sec = source_parts[1], source_parts[2]
            target_nb, target_sec = target_parts[1], target_parts[2]
            if source_nb == target_nb:
                ordered = [sec["id"] for sec in self.storage.list_sections(source_nb)]
                reordered = self._move_before(ordered, source_sec, target_sec)
                if reordered != ordered:
                    self.storage.reorder_sections(source_nb, reordered)
            else:
                moved = self.storage.move_section(source_nb, source_sec, target_nb, before_section_id=target_sec)
                if not moved:
                    return
                if self.selected_notebook_id == source_nb and self.selected_section_id == source_sec:
                    self.selected_notebook_id = target_nb
                    self.selected_section_id = source_sec
            self.refresh_notebooks()
            token = f"sec:{target_nb}:{source_sec}" if source_nb != target_nb else f"sec:{source_nb}:{source_sec}"
            if self.tree.exists(token):
                self.tree.selection_set(token)
                self.tree.focus(token)
                self.tree.see(token)
            self.on_tree_select()
            return

        if source_parts[0] == "sec" and target_parts[0] == "nb" and len(source_parts) == 3:
            source_nb, source_sec = source_parts[1], source_parts[2]
            target_nb = target_parts[1]
            if source_nb == target_nb:
                return
            moved = self.storage.move_section(source_nb, source_sec, target_nb, before_section_id=None)
            if not moved:
                return
            if self.selected_notebook_id == source_nb and self.selected_section_id == source_sec:
                self.selected_notebook_id = target_nb
                self.selected_section_id = source_sec
            self.refresh_notebooks()
            token = f"sec:{target_nb}:{source_sec}"
            if self.tree.exists(token):
                self.tree.selection_set(token)
                self.tree.focus(token)
                self.tree.see(token)
            self.on_tree_select()

    def _nearest_tree_row(self, y: int):
        direct = self.tree.identify_row(y)
        if direct:
            return direct
        rows = []
        stack = list(self.tree.get_children(""))
        while stack:
            item = stack.pop(0)
            bbox = self.tree.bbox(item)
            if bbox:
                top = bbox[1]
                bottom = bbox[1] + bbox[3]
                mid = (top + bottom) / 2.0
                rows.append((abs(y - mid), item))
            children = self.tree.get_children(item)
            for child in children:
                stack.append(child)
        if not rows:
            return ""
        rows.sort(key=lambda x: x[0])
        return rows[0][1]

    def _update_tree_drag_indicator(self, y: int):
        if not self.tree_drag_indicator:
            return
        target = self._nearest_tree_row(y)
        if not target:
            self._hide_tree_drag_indicator()
            return
        bbox = self.tree.bbox(target)
        if not bbox:
            self._hide_tree_drag_indicator()
            return
        self.tree_drag_indicator.place(x=0, y=bbox[1], width=max(1, self.tree.winfo_width()), height=2)

    def _hide_tree_drag_indicator(self):
        if self.tree_drag_indicator:
            self.tree_drag_indicator.place_forget()

    def _show_tree_drag_ghost(self, event):
        if not self.tree_drag_token or not self.tree.exists(self.tree_drag_token):
            return
        if not self.tree_drag_ghost:
            self.tree_drag_ghost = tk.Toplevel(self)
            self.tree_drag_ghost.overrideredirect(True)
            self.tree_drag_ghost.attributes("-topmost", True)
            label = tk.Label(
                self.tree_drag_ghost,
                text=self.tree.item(self.tree_drag_token, "text"),
                bg="#1d4ed8",
                fg="#ffffff",
                padx=8,
                pady=3,
            )
            label.pack()
        self.tree_drag_ghost.geometry(f"+{event.x_root + 14}+{event.y_root + 14}")

    def _hide_tree_drag_ghost(self):
        if self.tree_drag_ghost:
            self.tree_drag_ghost.destroy()
            self.tree_drag_ghost = None

    def _sync_selection_context(self):
        notebook_id = self.selected_notebook_id
        section_id = self.selected_section_id
        candidates = list(self.tree.selection())
        focus = self.tree.focus()
        if focus:
            candidates.append(focus)
        for token in candidates:
            parts = token.split(":")
            if not parts:
                continue
            if parts[0] == "sec" and len(parts) == 3:
                notebook_id = parts[1]
                section_id = parts[2]
                break
            if parts[0] == "nb" and len(parts) == 2:
                notebook_id = parts[1]
                section_id = None
        self.selected_notebook_id = notebook_id
        self.selected_section_id = section_id

    def refresh_pages(self):
        self._sync_selection_context()
        self.pages_list.delete(0, tk.END)
        self.page_cache = []
        if not (self.selected_notebook_id and self.selected_section_id):
            self._update_page_ready_state()
            return
        pages = self.storage.list_pages(self.selected_notebook_id, self.selected_section_id)
        query = self.search_var.get().strip().lower()
        if query:
            pages = [p for p in pages if query in p["title"].lower() or query in p.get("content", "").lower()]
        self.page_cache = pages
        for page in pages:
            self.pages_list.insert(tk.END, page["title"])
        if self.selected_page_id:
            if not self._select_page_in_list(self.selected_page_id):
                self.selected_page_id = None
                self._clear_editor()
        self._update_page_ready_state()

    def on_page_drag_start(self, event):
        idx = self.pages_list.nearest(event.y)
        if 0 <= idx < len(self.page_cache):
            self.page_drag_index = idx
            self.page_drag_start_y = event.y
            self.page_drag_active = False
        else:
            self.page_drag_index = None
            self.page_drag_start_y = None
            self.page_drag_active = False

    def on_page_drag_motion(self, event):
        if self.page_drag_start_y is None:
            return
        if abs(event.y - self.page_drag_start_y) >= 4:
            self.page_drag_active = True

    def on_page_drag_drop(self, event):
        source_index = self.page_drag_index
        self.page_drag_index = None
        drag_active = self.page_drag_active
        self.page_drag_active = False
        self.page_drag_start_y = None
        if not drag_active:
            return
        if source_index is None:
            return
        target_index = self.pages_list.nearest(event.y)
        if target_index < 0 or target_index >= len(self.page_cache):
            return
        if source_index == target_index:
            return
        if not (self.selected_notebook_id and self.selected_section_id):
            return

        source_id = self.page_cache[source_index]["id"]
        target_id = self.page_cache[target_index]["id"]
        ordered = [p["id"] for p in self.storage.list_pages(self.selected_notebook_id, self.selected_section_id)]
        reordered = self._move_before(ordered, source_id, target_id)
        if reordered == ordered:
            return
        self.storage.reorder_pages(self.selected_notebook_id, self.selected_section_id, reordered)
        self.selected_page_id = source_id
        self.refresh_pages()
        self._select_page_in_list(source_id)
        self._save_ui_state()

    def _select_page_in_list(self, page_id: str) -> bool:
        for idx, page in enumerate(self.page_cache):
            if page["id"] == page_id:
                self.pages_list.selection_clear(0, tk.END)
                self.pages_list.selection_set(idx)
                self.pages_list.activate(idx)
                self.pages_list.see(idx)
                return True
        return False

    def add_notebook(self):
        title = simpledialog.askstring("New Notebook", "Notebook title:", parent=self)
        if not title:
            return
        self.storage.create_notebook(title)
        self.refresh_notebooks()

    def add_section(self):
        self._sync_selection_context()
        if not self.selected_notebook_id:
            messagebox.showinfo("Info", "Select a notebook first.")
            return
        title = simpledialog.askstring("New Section", "Section title:", parent=self)
        if not title:
            return
        self.storage.create_section(self.selected_notebook_id, title)
        self.refresh_notebooks()

    def add_page(self):
        self._sync_selection_context()
        if not (self.selected_notebook_id and self.selected_section_id):
            messagebox.showinfo("Info", "Select a section first.")
            return
        if self.autosave_job:
            self.after_cancel(self.autosave_job)
            self.autosave_job = None
        if self.selected_page_id:
            self.save_current_page()
        title = simpledialog.askstring("New Page", "Page title:", parent=self)
        if not title:
            return
        page_id = self.storage.create_page(self.selected_notebook_id, self.selected_section_id, title)
        self.refresh_pages()
        self.selected_page_id = page_id
        # Keep UI state aligned with the newly created page to avoid stale autosave overwriting its title.
        self.load_current_page()
        self._select_page_in_list(page_id)

    def rename_tree_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        token = sel[0]
        parts = token.split(":")
        current = self.tree.item(token, "text")
        new_title = simpledialog.askstring("Rename", "New title:", initialvalue=current, parent=self)
        if not new_title:
            return
        if parts[0] == "nb":
            self.storage.rename_notebook(parts[1], new_title)
        elif parts[0] == "sec":
            self.storage.rename_section(parts[1], parts[2], new_title)
        self.refresh_notebooks()

    def _current_notebook_context(self):
        self._sync_selection_context()
        notebook_id = self.selected_notebook_id
        title = None
        for nb in self.storage.list_notebooks():
            if nb["id"] == notebook_id:
                title = nb["title"]
                break
        return notebook_id, title

    def _current_section_context(self):
        self._sync_selection_context()
        notebook_id = self.selected_notebook_id
        section_id = self.selected_section_id
        title = None
        if notebook_id and section_id:
            for sec in self.storage.list_sections(notebook_id):
                if sec["id"] == section_id:
                    title = sec["title"]
                    break
        return notebook_id, section_id, title

    def _current_page_context(self):
        self._sync_selection_context()
        notebook_id = self.selected_notebook_id
        section_id = self.selected_section_id
        page_id = self.selected_page_id
        title = None
        if notebook_id and section_id:
            sel = self.pages_list.curselection()
            if sel and sel[0] < len(self.page_cache):
                page = self.page_cache[sel[0]]
                page_id = page["id"]
                title = page["title"]
            elif page_id:
                for page in self.page_cache:
                    if page["id"] == page_id:
                        title = page["title"]
                        break
        return notebook_id, section_id, page_id, title

    def rename_current_notebook(self):
        notebook_id, current_title = self._current_notebook_context()
        if not notebook_id:
            messagebox.showinfo("Info", "Select a notebook first.")
            return
        initial = current_title or "Untitled Notebook"
        new_title = simpledialog.askstring("Rename Notebook", "New title:", initialvalue=initial, parent=self)
        if not new_title:
            return
        self.storage.rename_notebook(notebook_id, new_title)
        self.refresh_notebooks()

    def rename_current_section(self):
        notebook_id, section_id, current_title = self._current_section_context()
        if not (notebook_id and section_id):
            messagebox.showinfo("Info", "Select a section first.")
            return
        initial = current_title or "Untitled Section"
        new_title = simpledialog.askstring("Rename Section", "New title:", initialvalue=initial, parent=self)
        if not new_title:
            return
        self.storage.rename_section(notebook_id, section_id, new_title)
        self.refresh_notebooks()

    def rename_current_page(self):
        notebook_id, section_id, page_id, current_title = self._current_page_context()
        if not (notebook_id and section_id and page_id):
            messagebox.showinfo("Info", "Select a page first.")
            return
        initial = current_title or "Untitled Page"
        new_title = simpledialog.askstring("Rename Page", "New title:", initialvalue=initial, parent=self)
        if not new_title:
            return
        self.storage.rename_page(notebook_id, section_id, page_id, new_title)
        self.refresh_pages()
        self._select_page_in_list(page_id)

    def delete_tree_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        token = sel[0]
        parts = token.split(":")
        item_label = self.tree.item(token, "text")
        if not messagebox.askyesno("Confirm Delete", f"Delete '{item_label}'?"):
            return

        if parts[0] == "nb":
            self.storage.delete_notebook(parts[1])
            if self.selected_notebook_id == parts[1]:
                self.selected_notebook_id = None
                self.selected_section_id = None
                self.selected_page_id = None
                self._clear_editor()
        elif parts[0] == "sec":
            self.storage.delete_section(parts[1], parts[2])
            if self.selected_section_id == parts[2]:
                self.selected_section_id = None
                self.selected_page_id = None
                self._clear_editor()

        self.refresh_notebooks()
        self.refresh_pages()

    def on_page_select(self, _event=None):
        sel = self.pages_list.curselection()
        if not sel:
            return
        if sel[0] >= len(self.page_cache):
            return
        new_page_id = self.page_cache[sel[0]]["id"]

        if self.autosave_job:
            self.after_cancel(self.autosave_job)
            self.autosave_job = None
        if self.selected_page_id and self.selected_page_id != new_page_id:
            self.save_current_page()

        self.selected_page_id = new_page_id
        self._select_page_in_list(new_page_id)
        self.load_current_page(manage_loading=True)
        self._save_ui_state()

    def load_current_page(self, manage_loading: bool = True):
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            self._update_page_ready_state()
            return
        self._select_page_in_list(self.selected_page_id)
        payload = self.storage.load_ink_payload(self.selected_notebook_id, self.selected_section_id, self.selected_page_id)
        total_steps = 4 + len(payload.get("strokes", [])) + len(payload.get("images", [])) + len(payload.get("texts", []))
        if manage_loading:
            self._show_loading("Loading page...", determinate=True, total_steps=max(8, total_steps))
        page = self.storage.load_page(self.selected_notebook_id, self.selected_section_id, self.selected_page_id)
        self._advance_loading(1, "Loading page...")

        self.is_loading_page = True
        try:
            self.page_title_var.set(page.title)
            self._advance_loading(1, "Loading page title...")
            self._load_ink_for_current_page(payload)
            self._advance_loading(1, "Finalizing...")
        finally:
            self.is_loading_page = False
            self._update_page_ready_state()
            if manage_loading:
                self._hide_loading()

    def rename_page(self):
        self.rename_current_page()

    def delete_page(self):
        self._sync_selection_context()
        if not (self.selected_notebook_id and self.selected_section_id):
            return
        page = None
        sel = self.pages_list.curselection()
        if sel:
            page = self.page_cache[sel[0]]
        elif self.selected_page_id:
            for item in self.page_cache:
                if item["id"] == self.selected_page_id:
                    page = item
                    break
        if not page:
            messagebox.showinfo("Info", "Select a page first.")
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete page '{page['title']}'?"):
            return
        self.storage.delete_page(self.selected_notebook_id, self.selected_section_id, page["id"])
        if self.selected_page_id == page["id"]:
            self.selected_page_id = None
            self._clear_editor()
        self.refresh_pages()

    def delete_current_page(self):
        self.delete_page()

    def delete_current_section(self):
        self._sync_selection_context()
        section_id = self.selected_section_id
        notebook_id = self.selected_notebook_id
        if not (notebook_id and section_id):
            tree_sel = self.tree.selection()
            if tree_sel:
                token = tree_sel[0].split(":")
                if token[0] == "sec" and len(token) == 3:
                    notebook_id = token[1]
                    section_id = token[2]
        if not (notebook_id and section_id):
            messagebox.showinfo("Info", "Select a section first.")
            return
        section_title = ""
        for sec in self.storage.list_sections(notebook_id):
            if sec["id"] == section_id:
                section_title = sec["title"]
                break
        label = section_title or section_id
        if not messagebox.askyesno("Confirm Delete", f"Delete section '{label}' and all pages?"):
            return
        self.storage.delete_section(notebook_id, section_id)
        self.selected_section_id = None
        self.selected_page_id = None
        self._clear_editor()
        self.refresh_notebooks()
        self.refresh_pages()

    def _on_page_text_change(self, _event=None):
        if not self.is_loading_page:
            self._queue_autosave()

    def _on_text_modified(self, _event=None):
        if not self.editor:
            return
        if self.is_loading_page:
            self.editor.edit_modified(False)
            return
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            self._queue_autosave()

    def _queue_autosave(self):
        if self.autosave_job:
            self.after_cancel(self.autosave_job)
        self.autosave_job = self.after(900, lambda: self.save_current_page(write_preview_png=False, refresh_ui=False))

    def _collect_canvas_texts(self) -> list[dict]:
        for text_id in list(self.ink_text_widgets.keys()):
            self._sync_text_block_meta(text_id)
        cleaned = []
        for meta in self.ink_texts:
            text = str(meta.get("text", ""))
            if not text.strip():
                continue
            cleaned.append(
                {
                    "id": str(meta.get("id", uuid.uuid4().hex[:10])),
                    "x": int(meta.get("x", 20)),
                    "y": int(meta.get("y", self.ink_start_y + 20)),
                    "w": int(meta.get("w", 320)),
                    "h": int(meta.get("h", 30)),
                    "text": text,
                }
            )
        self.ink_texts = cleaned
        return cleaned

    def save_current_page(self, write_preview_png: bool = True, refresh_ui: bool = True):
        if self.autosave_job:
            self.after_cancel(self.autosave_job)
            self.autosave_job = None
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            return

        title = sanitize_title(self.page_title_var.get())
        content = ""
        formatting = []
        self.storage.save_page(
            self.selected_notebook_id,
            self.selected_section_id,
            self.selected_page_id,
            title,
            content,
            formatting,
        )
        self.storage.save_ink_payload(
            self.selected_notebook_id,
            self.selected_section_id,
            self.selected_page_id,
            self.ink_strokes,
            self.ink_images,
            self._collect_canvas_texts(),
        )
        if write_preview_png and PIL_AVAILABLE:
            image = self._render_ink_image()
            self.storage.save_ink_image(
                self.selected_notebook_id,
                self.selected_section_id,
                self.selected_page_id,
                image,
            )
        elif write_preview_png and not self.pillow_warning_shown:
            self.pillow_warning_shown = True
            messagebox.showwarning(
                "PNG Export Disabled",
                "Ink is saved as strokes, but PNG export needs Pillow.\nRun: python -m pip install pillow",
            )
        if refresh_ui:
            self.refresh_pages()

    def save_as_page(self):
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            messagebox.showinfo("Info", "Select a page first.")
            return
        self.save_current_page()
        target = filedialog.asksaveasfilename(
            title="Save Page As",
            defaultextension=".wnote.json",
            filetypes=[("WindowsNote Page", "*.wnote.json"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return

        image_items = []
        for meta in self.ink_images:
            asset_name = meta.get("asset")
            if not asset_name:
                continue
            asset_path = self.storage.page_asset_path(
                self.selected_notebook_id, self.selected_section_id, self.selected_page_id, asset_name
            )
            if not asset_path.exists():
                continue
            encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
            image_items.append(
                {
                    "id": meta.get("id"),
                    "x": int(meta.get("x", 0)),
                    "y": int(meta.get("y", 0)),
                    "asset_name": asset_name,
                    "mime": self._guess_mime(asset_path.suffix.lower()),
                    "data_base64": encoded,
                }
            )

        payload = {
            "app_version": APP_VERSION,
            "exported_at": utc_now_iso(),
            "page": {
                "id": self.selected_page_id,
                "title": sanitize_title(self.page_title_var.get()),
                "content": "",
                "formatting": [],
            },
            "ink": {"strokes": self.ink_strokes, "images": image_items, "texts": self._collect_canvas_texts()},
        }
        with Path(target).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def print_to_pdf(self):
        if not REPORTLAB_AVAILABLE:
            messagebox.showwarning("PDF Disabled", "PDF print requires reportlab.\nRun: python -m pip install reportlab")
            return
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            messagebox.showinfo("Info", "Select a page first.")
            return

        paper = self._ask_paper_size()
        if not paper:
            return
        size_map = {"A4": A4, "LETTER": LETTER, "LEGAL": LEGAL, "A5": A5}

        target = filedialog.asksaveasfilename(
            title="Print to PDF",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not target:
            return

        self.save_current_page()
        page_size = size_map[paper]
        page_w, page_h = page_size
        margin = 36
        c = pdf_canvas.Canvas(target, pagesize=page_size)

        y = page_h - margin
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin, y, sanitize_title(self.page_title_var.get()))
        y -= 24

        usable_w = page_w - (margin * 2)

        if PIL_AVAILABLE:
            ink_img = self._render_ink_image()
            tmp_png = self.storage.ink_png_path(self.selected_notebook_id, self.selected_section_id, self.selected_page_id)
            ink_img.save(tmp_png, format="PNG")
            if tmp_png.exists():
                img_reader = ImageReader(str(tmp_png))
                iw, ih = ink_img.size
                scale = min(usable_w / max(1, iw), (page_h - (margin * 2)) / max(1, ih), 1.0)
                draw_w = iw * scale
                draw_h = ih * scale
                if y < draw_h + margin:
                    c.showPage()
                    y = page_h - margin
                c.drawImage(img_reader, margin, max(margin, y - draw_h), width=draw_w, height=draw_h, preserveAspectRatio=True)

        c.save()

    def _ask_paper_size(self):
        dialog = tk.Toplevel(self)
        dialog.title("Select Paper Size")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(dialog, text="Paper size:").grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")
        paper_var = tk.StringVar(value="A4")
        combo = ttk.Combobox(dialog, textvariable=paper_var, values=["A4", "LETTER", "LEGAL", "A5"], state="readonly")
        combo.grid(row=1, column=0, padx=10, pady=4, sticky="ew")
        combo.current(0)
        combo.focus_set()

        result = {"value": None}

        def on_ok():
            result["value"] = paper_var.get()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btns = ttk.Frame(dialog)
        btns.grid(row=2, column=0, padx=10, pady=(8, 10), sticky="e")
        ttk.Button(btns, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=4)

        dialog.columnconfigure(0, weight=1)
        dialog.wait_window()
        return result["value"]

    @staticmethod
    def _guess_mime(ext: str) -> str:
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }.get(ext, "application/octet-stream")

    def _collect_formatting_ranges(self) -> list[dict]:
        if not self.editor:
            return []
        spans = []
        for tag in TEXT_TAGS:
            ranges = self.editor.tag_ranges(tag)
            for i in range(0, len(ranges), 2):
                spans.append({"tag": tag, "start": str(ranges[i]), "end": str(ranges[i + 1])})
        return spans

    def _clear_editor(self):
        self.page_title_var.set("")
        if self.editor:
            self.editor.delete("1.0", tk.END)
        self.ink_canvas.delete("inkstroke")
        self.ink_canvas.delete("ink_image")
        self._clear_text_blocks()
        self.ink_strokes = []
        self.redo_strokes = []
        self.ink_images = []
        self.ink_image_cache = {}
        self.ink_image_items = {}
        self.current_stroke = None
        self.current_stroke_item = None
        self.current_raw_point = None
        self.current_eraser_point = None
        self.last_stroke_end_point = None
        self.last_stroke_end_time = 0.0
        self.dragging_image_id = None
        self._clear_image_selection()
        self._update_page_ready_state()

    def change_storage_folder(self):
        selected = filedialog.askdirectory(initialdir=str(self.storage_root), title="Choose note storage folder")
        if not selected:
            return
        self.storage_root = Path(selected).resolve()
        self.storage.set_root(self.storage_root)
        self.config_data["data_root"] = str(self.storage_root)
        self._save_config(self.config_data)
        self.storage_label_var.set(f"Storage: {self.storage_root}")

        self.selected_notebook_id = None
        self.selected_section_id = None
        self.selected_page_id = None
        self._clear_editor()
        self.refresh_notebooks()
        self.refresh_pages()


if __name__ == "__main__":
    os.makedirs(CONFIG_FILE.parent, exist_ok=True)
    app = WindowsNoteApp()
    app.mainloop()
