import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_DATA_ROOT = "./local_notes"
TEXT_TAGS = ("bold", "italic", "underline", "highlight")


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

    def _page_path(self, notebook_id: str, section_id: str, page_id: str) -> Path:
        return self.notebooks_dir / notebook_id / "sections" / section_id / "pages" / f"{page_id}.json"

    @staticmethod
    def _read_json(path: Path, fallback):
        try:
            with path.open("r", encoding="utf-8") as f:
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
        self.title("WindowsNote - OneNote-style Local Notes")
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

        self._build_ui()
        self._bind_shortcuts()
        self.refresh_notebooks()

    def _load_config(self) -> dict:
        if not CONFIG_FILE.exists():
            data = {"data_root": DEFAULT_DATA_ROOT}
            self._save_config(data)
            return data
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
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

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(paned)
        center = ttk.Frame(paned)
        right = ttk.Frame(paned)

        paned.add(left, weight=3)
        paned.add(center, weight=2)
        paned.add(right, weight=7)

        ttk.Label(left, text="Notebooks / Sections").pack(anchor=tk.W)
        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        nb_btns = ttk.Frame(left)
        nb_btns.pack(fill=tk.X, pady=4)
        ttk.Button(nb_btns, text="+ Notebook", command=self.add_notebook).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="+ Section", command=self.add_section).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="Rename", command=self.rename_tree_item).pack(side=tk.LEFT, padx=2)
        ttk.Button(nb_btns, text="Delete", command=self.delete_tree_item).pack(side=tk.LEFT, padx=2)

        ttk.Label(center, text="Pages").pack(anchor=tk.W)
        self.pages_list = tk.Listbox(center)
        self.pages_list.pack(fill=tk.BOTH, expand=True)
        self.pages_list.bind("<<ListboxSelect>>", self.on_page_select)

        page_btns = ttk.Frame(center)
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

        self.editor = tk.Text(right, wrap=tk.WORD, undo=True)
        self.editor.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.editor.bind("<<Modified>>", self._on_text_modified)

        self._setup_text_tags()

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save", command=self.save_current_page, accelerator="Ctrl+S")
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
        self.refresh_pages()

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
