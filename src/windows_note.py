import json
import os
import shutil
import uuid
import base64
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont
try:
    from PIL import Image, ImageDraw, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = Any
    ImageDraw = Any
    ImageTk = Any

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
APP_VERSION = "1.2.0"


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
                items.append({"id": nb_dir.name, "title": meta.get("title", "Untitled Notebook")})
        return items

    def create_notebook(self, title: str) -> str:
        nb_id = uuid.uuid4().hex[:12]
        nb_dir = self.notebooks_dir / nb_id
        (nb_dir / "sections").mkdir(parents=True, exist_ok=True)
        self._write_json(nb_dir / "meta.json", {"id": nb_id, "title": sanitize_title(title), "created_at": utc_now_iso()})
        return nb_id

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
                out.append({"id": section_dir.name, "title": meta.get("title", "Untitled Section")})
        return out

    def create_section(self, notebook_id: str, title: str) -> str:
        section_id = uuid.uuid4().hex[:12]
        section_dir = self.notebooks_dir / notebook_id / "sections" / section_id
        (section_dir / "pages").mkdir(parents=True, exist_ok=True)
        self._write_json(
            section_dir / "meta.json",
            {"id": section_id, "title": sanitize_title(title), "created_at": utc_now_iso()},
        )
        return section_id

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
                }
            )
        pages.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
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
        }
        page_path = self._page_path(notebook_id, section_id, page_id)
        page_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(page_path, page)
        return page_id

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
        }
        self._write_json(path, data)

    def load_ink_payload(self, notebook_id: str, section_id: str, page_id: str) -> dict:
        path = self._ink_json_path(notebook_id, section_id, page_id)
        payload = self._read_json(path, {})
        strokes = payload.get("strokes", [])
        images = payload.get("images", [])
        return {
            "strokes": strokes if isinstance(strokes, list) else [],
            "images": images if isinstance(images, list) else [],
        }

    def load_ink_strokes(self, notebook_id: str, section_id: str, page_id: str) -> list[dict]:
        return self.load_ink_payload(notebook_id, section_id, page_id).get("strokes", [])

    def save_ink_payload(
        self, notebook_id: str, section_id: str, page_id: str, strokes: list[dict], images: list[dict]
    ) -> None:
        path = self._ink_json_path(notebook_id, section_id, page_id)
        data = {"page_id": page_id, "updated_at": utc_now_iso(), "strokes": strokes, "images": images}
        self._write_json(path, data)

    def save_ink_strokes(self, notebook_id: str, section_id: str, page_id: str, strokes: list[dict]) -> None:
        payload = self.load_ink_payload(notebook_id, section_id, page_id)
        self.save_ink_payload(notebook_id, section_id, page_id, strokes, payload.get("images", []))

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

    def _page_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}.json"

    def _ink_json_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}_ink.json"

    def _ink_png_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}_ink.png"

    def _page_assets_dir(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}_assets"

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

        self.selected_notebook_id = None
        self.selected_section_id = None
        self.selected_page_id = None
        self.page_cache = []
        self.is_loading_page = False
        self.autosave_job = None
        self.ink_strokes = []
        self.ink_images = []
        self.ink_image_cache = {}
        self.dragging_image_id = None
        self.dragging_offset = (0, 0)
        self.current_stroke = None
        self.current_tool = tk.StringVar(value="pen")
        self.pen_size_var = tk.IntVar(value=4)
        self.pen_color = DEFAULT_INK_COLOR
        self.pillow_warning_shown = False

        self._build_ui()
        self._bind_shortcuts()
        self.refresh_notebooks()
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

        self.storage_label_var = tk.StringVar(value=f"Storage: {self.storage_root}")
        ttk.Label(top, textvariable=self.storage_label_var).pack(side=tk.LEFT, padx=(8, 0))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Button(toolbar, text="B", command=lambda: self.apply_text_tag("bold")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="I", command=lambda: self.apply_text_tag("italic")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="U", command=lambda: self.apply_text_tag("underline")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Highlight", command=lambda: self.apply_text_tag("highlight")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Save", command=self.save_current_page).pack(side=tk.LEFT, padx=8)
        ttk.Button(toolbar, text="Save As", command=self.save_as_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Print PDF", command=self.print_to_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)
        ttk.Label(toolbar, text="Ink:").pack(side=tk.LEFT)
        ttk.Radiobutton(toolbar, text="Pen", value="pen", variable=self.current_tool).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(toolbar, text="Eraser", value="eraser", variable=self.current_tool).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Pick Color", command=self.pick_ink_color).pack(side=tk.LEFT, padx=2)
        for color in ("#111827", "#2563eb", "#dc2626", "#15803d"):
            tk.Button(
                toolbar,
                width=2,
                bg=color,
                relief=tk.GROOVE,
                command=lambda c=color: self.set_ink_color(c),
            ).pack(side=tk.LEFT, padx=1)
        ttk.Label(toolbar, text="Size").pack(side=tk.LEFT, padx=(8, 2))
        self.pen_size_spin = ttk.Spinbox(toolbar, from_=1, to=24, width=4, textvariable=self.pen_size_var)
        self.pen_size_spin.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Insert Image", command=self.insert_image_at_cursor).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Clear Ink", command=self.clear_ink).pack(side=tk.LEFT, padx=6)
        ttk.Label(toolbar, text=f"Version {APP_VERSION}").pack(side=tk.RIGHT, padx=4)

        main_paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        nav_paned = ttk.Panedwindow(main_paned, orient=tk.HORIZONTAL)
        right = ttk.Frame(main_paned)

        notebook_frame = ttk.Frame(nav_paned)
        pages_frame = ttk.Frame(nav_paned)
        nav_paned.add(notebook_frame, weight=3)
        nav_paned.add(pages_frame, weight=2)

        main_paned.add(nav_paned, weight=4)
        main_paned.add(right, weight=8)

        ttk.Label(notebook_frame, text="Notebooks / Sections").pack(anchor=tk.W)
        self.tree = ttk.Treeview(notebook_frame, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        nb_btns = ttk.Frame(notebook_frame)
        nb_btns.pack(fill=tk.X, pady=4)
        ttk.Button(nb_btns, text="+ Notebook", command=self.add_notebook).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="+ Section", command=self.add_section).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="Rename", command=self.rename_tree_item).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="Delete", command=self.delete_tree_item).pack(side=tk.LEFT, padx=2)

        ttk.Label(pages_frame, text="Pages").pack(anchor=tk.W)
        self.pages_list = tk.Listbox(pages_frame)
        self.pages_list.pack(fill=tk.BOTH, expand=True)
        self.pages_list.bind("<<ListboxSelect>>", self.on_page_select)

        page_btns = ttk.Frame(pages_frame)
        page_btns.pack(fill=tk.X, pady=4)
        ttk.Button(page_btns, text="+ Page", command=self.add_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(page_btns, text="Rename", command=self.rename_page).pack(side=tk.LEFT, padx=2)
        ttk.Button(page_btns, text="Delete", command=self.delete_page).pack(side=tk.LEFT, padx=2)

        title_frame = ttk.Frame(right)
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text="Page Title:").pack(side=tk.LEFT)
        self.page_title_var = tk.StringVar(value="")
        self.page_title_entry = ttk.Entry(title_frame, textvariable=self.page_title_var)
        self.page_title_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.page_title_entry.bind("<KeyRelease>", self._on_page_text_change)

        page_frame = ttk.Frame(right)
        page_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        ttk.Label(page_frame, text="Page (Text + Ink + Images)").grid(row=0, column=0, sticky="w")

        self.page_canvas = tk.Canvas(page_frame, bg="#f7f7f7", cursor="pencil")
        page_y = ttk.Scrollbar(page_frame, orient=tk.VERTICAL, command=self.page_canvas.yview)
        page_x = ttk.Scrollbar(page_frame, orient=tk.HORIZONTAL, command=self.page_canvas.xview)
        self.page_canvas.configure(yscrollcommand=page_y.set, xscrollcommand=page_x.set, scrollregion=(0, 0, 4200, 6200))
        self.page_canvas.grid(row=1, column=0, sticky="nsew")
        page_y.grid(row=1, column=1, sticky="ns")
        page_x.grid(row=2, column=0, sticky="ew")
        page_frame.rowconfigure(1, weight=1)
        page_frame.columnconfigure(0, weight=1)

        self.text_area_height = 1400
        self.ink_start_y = self.text_area_height + 40
        self.page_canvas.create_rectangle(10, 10, 4010, self.text_area_height, fill="white", outline="#d1d5db", tags=("pagebg",))
        self.page_canvas.create_rectangle(
            10, self.ink_start_y, 4010, 6100, fill="white", outline="#d1d5db", tags=("inkbg",)
        )

        self.editor = tk.Text(self.page_canvas, wrap=tk.NONE, undo=True)
        self.editor_window_id = self.page_canvas.create_window(20, 20, anchor=tk.NW, width=3980, height=1360, window=self.editor)
        self.editor.bind("<<Modified>>", self._on_text_modified)

        self.ink_canvas = self.page_canvas
        self.canvas_cursor = (80, self.ink_start_y + 80)
        self.ink_canvas.bind("<ButtonPress-1>", self.on_ink_press)
        self.ink_canvas.bind("<B1-Motion>", self.on_ink_drag)
        self.ink_canvas.bind("<ButtonRelease-1>", self.on_ink_release)
        self.ink_canvas.bind("<Motion>", self._on_canvas_motion)
        self.ink_canvas.bind("<MouseWheel>", self._on_ink_mousewheel)

        self._setup_text_tags()

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save", command=self.save_current_page, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as_page)
        file_menu.add_command(label="Print to PDF...", command=self.print_to_pdf)
        file_menu.add_command(label="Change Local Storage Folder", command=self.change_storage_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        create_menu = tk.Menu(menubar, tearoff=0)
        create_menu.add_command(label="New Notebook", command=self.add_notebook)
        create_menu.add_command(label="New Section", command=self.add_section)
        create_menu.add_command(label="New Page", command=self.add_page)
        menubar.add_cascade(label="Create", menu=create_menu)

        self.config(menu=menubar)

    def _bind_shortcuts(self):
        self.bind("<Control-s>", lambda _e: self.save_current_page())

    def _setup_text_tags(self):
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
        try:
            start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
        except tk.TclError:
            return

        if tag_name in self.editor.tag_names("sel.first"):
            self.editor.tag_remove(tag_name, start, end)
        else:
            self.editor.tag_add(tag_name, start, end)
        self._queue_autosave()

    def set_ink_color(self, color: str):
        self.pen_color = color
        self.current_tool.set("pen")

    def pick_ink_color(self):
        chosen = colorchooser.askcolor(color=self.pen_color, title="Choose Ink Color", parent=self)
        if chosen and chosen[1]:
            self.set_ink_color(chosen[1])

    def clear_ink(self):
        self.ink_strokes = []
        self.ink_images = []
        self.ink_image_cache = {}
        self.ink_canvas.delete("inkstroke")
        self.ink_canvas.delete("ink_image")
        self._queue_autosave()

    def on_ink_press(self, event):
        if self.is_loading_page:
            return
        x = int(self.ink_canvas.canvasx(event.x))
        y = int(self.ink_canvas.canvasy(event.y))
        self.canvas_cursor = (x, y)
        hit_image_id = self._image_id_at(x, y)
        if hit_image_id:
            self.dragging_image_id = hit_image_id
            item_x, item_y = self.ink_canvas.coords(f"inkimg:{hit_image_id}")
            self.dragging_offset = (x - int(item_x), y - int(item_y))
            return
        if y < self.ink_start_y:
            return
        if self.current_tool.get() == "eraser":
            self.current_stroke = None
            self._erase_strokes_at(x, y)
            return
        width = int(self.pen_size_var.get())
        self.current_stroke = {"tool": "pen", "color": self.pen_color, "width": width, "points": [[x, y]]}

    def on_ink_drag(self, event):
        x = int(self.ink_canvas.canvasx(event.x))
        y = int(self.ink_canvas.canvasy(event.y))
        self.canvas_cursor = (x, y)
        if self.dragging_image_id:
            self._move_image(self.dragging_image_id, x - self.dragging_offset[0], y - self.dragging_offset[1])
            return
        if y < self.ink_start_y:
            return
        if self.current_tool.get() == "eraser":
            self._erase_strokes_at(x, y)
            return
        if not self.current_stroke:
            return
        points = self.current_stroke["points"]
        last_x, last_y = points[-1]
        points.append([x, y])
        self.ink_canvas.create_line(
            last_x,
            last_y,
            x,
            y,
            fill=self.current_stroke["color"],
            width=self.current_stroke["width"],
            capstyle=tk.ROUND,
            smooth=True,
            tags=("inkstroke",),
        )

    def on_ink_release(self, event):
        x = int(self.ink_canvas.canvasx(event.x))
        y = int(self.ink_canvas.canvasy(event.y))
        self.canvas_cursor = (x, y)
        if self.dragging_image_id:
            self.dragging_image_id = None
            self._queue_autosave()
            return
        if self.current_tool.get() == "eraser":
            self.current_stroke = None
            return
        if not self.current_stroke:
            return
        points = self.current_stroke["points"]
        if len(points) == 1:
            x, y = points[0]
            half = max(1, self.current_stroke["width"] // 2)
            self.ink_canvas.create_oval(
                x - half,
                y - half,
                x + half,
                y + half,
                outline=self.current_stroke["color"],
                fill=self.current_stroke["color"],
                tags=("inkstroke",),
            )
        self.ink_strokes.append(self.current_stroke)
        self.current_stroke = None
        self._queue_autosave()

    def _image_id_at(self, x: int, y: int):
        hits = self.ink_canvas.find_overlapping(x, y, x, y)
        for item in reversed(hits):
            for tag in self.ink_canvas.gettags(item):
                if tag.startswith("inkimg:"):
                    return tag.split(":", 1)[1]
        return None

    def _move_image(self, image_id: str, x: int, y: int):
        self.ink_canvas.coords(f"inkimg:{image_id}", x, y)
        self._raise_ink_layers()
        for img in self.ink_images:
            if img.get("id") == image_id:
                img["x"] = x
                img["y"] = y
                break

    def _erase_strokes_at(self, x: int, y: int):
        radius = max(8, int(self.pen_size_var.get()) * 2)
        radius_sq = radius * radius
        original_count = len(self.ink_strokes)
        kept = []
        for stroke in self.ink_strokes:
            points = stroke.get("points", [])
            if len(points) < 2:
                if points:
                    px, py = points[0]
                    if (px - x) * (px - x) + (py - y) * (py - y) <= radius_sq:
                        continue
                kept.append(stroke)
                continue

            hit = False
            for i in range(1, len(points)):
                x1, y1 = points[i - 1]
                x2, y2 = points[i]
                if self._distance_sq_point_to_segment(x, y, x1, y1, x2, y2) <= radius_sq:
                    hit = True
                    break
            if not hit:
                kept.append(stroke)

        if len(kept) != original_count:
            self.ink_strokes = kept
            self.ink_canvas.delete("inkstroke")
            for stroke in self.ink_strokes:
                self._draw_stroke(stroke)
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
        if self.focus_get() == self.editor:
            try:
                box = self.editor.bbox("insert")
            except tk.TclError:
                box = None
            if box:
                ex, ey, _w, h = box
                wx, wy = self.ink_canvas.coords(self.editor_window_id)
                return int(wx + ex), int(wy + ey + h)
        return self.canvas_cursor

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
        if y < self.ink_start_y:
            y = self.ink_start_y + 20
        image_meta = {"id": uuid.uuid4().hex[:10], "asset": asset, "x": x, "y": y}
        self.ink_images.append(image_meta)
        self._draw_canvas_image(image_meta)
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
        self.ink_canvas.create_image(x, y, image=tk_image, anchor=tk.NW, tags=("ink_image", f"inkimg:{image_id}"))
        self._raise_ink_layers()

    def _draw_stroke(self, stroke: dict):
        points = stroke.get("points", [])
        color = stroke.get("color", DEFAULT_INK_COLOR)
        width = max(1, int(stroke.get("width", 2)))
        if len(points) == 1:
            x, y = points[0]
            half = max(1, width // 2)
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
            *flattened, fill=color, width=width, capstyle=tk.ROUND, smooth=True, tags=("inkstroke",)
        )
        self._raise_ink_layers()

    def _raise_ink_layers(self):
        self.ink_canvas.tag_raise("inkstroke")
        self.ink_canvas.tag_raise("ink_image")

    def _load_ink_for_current_page(self):
        self.ink_canvas.delete("inkstroke")
        self.ink_canvas.delete("ink_image")
        self.ink_strokes = []
        self.ink_images = []
        self.ink_image_cache = {}
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            return
        payload = self.storage.load_ink_payload(self.selected_notebook_id, self.selected_section_id, self.selected_page_id)
        self.ink_strokes = payload.get("strokes", [])
        self.ink_images = payload.get("images", [])
        for stroke in self.ink_strokes:
            self._draw_stroke(stroke)
        for image_meta in self.ink_images:
            self._draw_canvas_image(image_meta)

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
            color = stroke.get("color", DEFAULT_INK_COLOR)
            line_width = max(1, int(stroke.get("width", 2)))
            if len(points) == 1:
                x, y = points[0]
                half = max(1, line_width // 2)
                draw.ellipse((x - half, y - half, x + half, y + half), fill=color, outline=color)
            elif len(points) > 1:
                draw.line(points, fill=color, width=line_width, joint="curve")
        return image

    def refresh_notebooks(self):
        self.tree.delete(*self.tree.get_children())
        for notebook in self.storage.list_notebooks():
            nb_node = self.tree.insert("", tk.END, iid=f"nb:{notebook['id']}", text=notebook["title"])
            for section in self.storage.list_sections(notebook["id"]):
                self.tree.insert(nb_node, tk.END, iid=f"sec:{notebook['id']}:{section['id']}", text=section["title"])
            self.tree.item(nb_node, open=True)

    def on_tree_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        token = selected[0]
        parts = token.split(":")

        if parts[0] == "nb":
            self.selected_notebook_id = parts[1]
            self.selected_section_id = None
        elif parts[0] == "sec":
            self.selected_notebook_id = parts[1]
            self.selected_section_id = parts[2]

        self.refresh_pages()

    def refresh_pages(self):
        self.pages_list.delete(0, tk.END)
        self.page_cache = []
        if not (self.selected_notebook_id and self.selected_section_id):
            return
        pages = self.storage.list_pages(self.selected_notebook_id, self.selected_section_id)
        query = self.search_var.get().strip().lower()
        if query:
            pages = [p for p in pages if query in p["title"].lower() or query in p.get("content", "").lower()]
        self.page_cache = pages
        for page in pages:
            self.pages_list.insert(tk.END, page["title"])

    def add_notebook(self):
        title = simpledialog.askstring("New Notebook", "Notebook title:", parent=self)
        if not title:
            return
        self.storage.create_notebook(title)
        self.refresh_notebooks()

    def add_section(self):
        if not self.selected_notebook_id:
            messagebox.showinfo("Info", "Select a notebook first.")
            return
        title = simpledialog.askstring("New Section", "Section title:", parent=self)
        if not title:
            return
        self.storage.create_section(self.selected_notebook_id, title)
        self.refresh_notebooks()

    def add_page(self):
        if not (self.selected_notebook_id and self.selected_section_id):
            messagebox.showinfo("Info", "Select a section first.")
            return
        title = simpledialog.askstring("New Page", "Page title:", parent=self)
        if not title:
            return
        page_id = self.storage.create_page(self.selected_notebook_id, self.selected_section_id, title)
        self.refresh_pages()
        self.selected_page_id = page_id

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
        if self.autosave_job:
            self.after_cancel(self.autosave_job)
            self.autosave_job = None
        if self.selected_page_id:
            self.save_current_page()

        sel = self.pages_list.curselection()
        if not sel:
            return

        page = self.page_cache[sel[0]]
        self.selected_page_id = page["id"]
        self.load_current_page()

    def load_current_page(self):
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            return
        page = self.storage.load_page(self.selected_notebook_id, self.selected_section_id, self.selected_page_id)

        self.is_loading_page = True
        try:
            self.page_title_var.set(page.title)
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", page.content)
            for tag in TEXT_TAGS:
                self.editor.tag_remove(tag, "1.0", tk.END)
            for span in page.formatting:
                tag = span.get("tag")
                start = span.get("start")
                end = span.get("end")
                if tag in TEXT_TAGS and start and end:
                    try:
                        self.editor.tag_add(tag, start, end)
                    except tk.TclError:
                        pass
            self.editor.edit_modified(False)
            self._load_ink_for_current_page()
        finally:
            self.is_loading_page = False

    def rename_page(self):
        if not (self.selected_notebook_id and self.selected_section_id):
            return
        sel = self.pages_list.curselection()
        if not sel:
            return
        page = self.page_cache[sel[0]]
        new_title = simpledialog.askstring("Rename Page", "New title:", initialvalue=page["title"], parent=self)
        if not new_title:
            return
        self.storage.rename_page(self.selected_notebook_id, self.selected_section_id, page["id"], new_title)
        self.refresh_pages()

    def delete_page(self):
        if not (self.selected_notebook_id and self.selected_section_id):
            return
        sel = self.pages_list.curselection()
        if not sel:
            return
        page = self.page_cache[sel[0]]
        if not messagebox.askyesno("Confirm Delete", f"Delete page '{page['title']}'?"):
            return
        self.storage.delete_page(self.selected_notebook_id, self.selected_section_id, page["id"])
        if self.selected_page_id == page["id"]:
            self.selected_page_id = None
            self._clear_editor()
        self.refresh_pages()

    def _on_page_text_change(self, _event=None):
        if not self.is_loading_page:
            self._queue_autosave()

    def _on_text_modified(self, _event=None):
        if self.is_loading_page:
            self.editor.edit_modified(False)
            return
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            self._queue_autosave()

    def _queue_autosave(self):
        if self.autosave_job:
            self.after_cancel(self.autosave_job)
        self.autosave_job = self.after(900, self.save_current_page)

    def save_current_page(self):
        if self.autosave_job:
            self.after_cancel(self.autosave_job)
            self.autosave_job = None
        if not (self.selected_notebook_id and self.selected_section_id and self.selected_page_id):
            return

        title = sanitize_title(self.page_title_var.get())
        content = self.editor.get("1.0", "end-1c")
        formatting = self._collect_formatting_ranges()
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
        )
        if PIL_AVAILABLE:
            image = self._render_ink_image()
            self.storage.save_ink_image(
                self.selected_notebook_id,
                self.selected_section_id,
                self.selected_page_id,
                image,
            )
        elif not self.pillow_warning_shown:
            self.pillow_warning_shown = True
            messagebox.showwarning(
                "PNG Export Disabled",
                "Ink is saved as strokes, but PNG export needs Pillow.\nRun: python -m pip install pillow",
            )
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
                "content": self.editor.get("1.0", "end-1c"),
                "formatting": self._collect_formatting_ranges(),
            },
            "ink": {"strokes": self.ink_strokes, "images": image_items},
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

        paper = simpledialog.askstring("Paper Size", "Choose paper size: A4, LETTER, LEGAL, A5", parent=self)
        if not paper:
            return
        paper = paper.strip().upper()
        size_map = {"A4": A4, "LETTER": LETTER, "LEGAL": LEGAL, "A5": A5}
        if paper not in size_map:
            messagebox.showerror("Invalid Size", "Supported sizes: A4, LETTER, LEGAL, A5")
            return

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

        c.setFont("Helvetica", 10)
        usable_w = page_w - (margin * 2)
        wrap_chars = max(40, int(usable_w / 5.2))
        for raw_line in self.editor.get("1.0", "end-1c").splitlines() or [""]:
            lines = textwrap.wrap(raw_line, width=wrap_chars) or [""]
            for line in lines:
                if y < margin + 120:
                    c.showPage()
                    y = page_h - margin
                    c.setFont("Helvetica", 10)
                c.drawString(margin, y, line)
                y -= 14

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
        spans = []
        for tag in TEXT_TAGS:
            ranges = self.editor.tag_ranges(tag)
            for i in range(0, len(ranges), 2):
                spans.append({"tag": tag, "start": str(ranges[i]), "end": str(ranges[i + 1])})
        return spans

    def _clear_editor(self):
        self.page_title_var.set("")
        self.editor.delete("1.0", tk.END)
        self.ink_canvas.delete("inkstroke")
        self.ink_canvas.delete("ink_image")
        self.ink_strokes = []
        self.ink_images = []
        self.ink_image_cache = {}
        self.dragging_image_id = None

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
