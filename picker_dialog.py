"""The "Add screenshots" window: pick folders, screenshots, or both at once.

The system's own file window can pick folders *or* files, never a mix, so this is a
small Tk browser instead. It runs as its own process (Tk must own its main thread,
which Streamlit's script thread is not): `python picker_dialog.py [start folder]`.
It prints the chosen paths, one per line, and nothing if cancelled.
"""
from __future__ import annotations

import os
import string
import sys
from datetime import datetime
from pathlib import Path

from config import SUPPORTED_EXTENSIONS


def list_entries(folder: Path) -> list[tuple[Path, bool]]:
    """Subfolders, then screenshots (PNG/JPEG), each sorted by name; (path, is_folder).
    Hidden and system entries are left out. Raises OSError if the folder can't be read."""
    folders, images = [], []
    with os.scandir(folder) as it:
        for entry in it:
            if entry.name.startswith((".", "$")):
                continue
            try:
                if entry.is_dir():
                    folders.append(Path(entry.path))
                elif Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                    images.append(Path(entry.path))
            except OSError:
                continue
    key = lambda p: p.name.casefold()  # noqa: E731
    return [(p, True) for p in sorted(folders, key=key)] + [(p, False) for p in sorted(images, key=key)]


def places() -> list[tuple[str, Path]]:
    """Shortcuts shown on the left: common screenshot locations, then drives."""
    home = Path.home()
    found = [(label, path) for label, path in (
        ("Screenshots", home / "Pictures" / "Screenshots"), ("Pictures", home / "Pictures"),
        ("Desktop", home / "Desktop"), ("Downloads", home / "Downloads"),
        ("Documents", home / "Documents"), ("Home", home),
    ) if path.is_dir()]
    if sys.platform.startswith("win"):
        found += [(f"Drive {d}:", Path(f"{d}:\\")) for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
    else:
        found.append(("Computer", Path("/")))
    return found


def summary(chosen: list[tuple[Path, bool]]) -> str:
    folders = sum(1 for _, is_folder in chosen if is_folder)
    images = len(chosen) - folders
    parts = ([f"{folders} folder{'s' * (folders != 1)}"] if folders else []) + \
            ([f"{images} screenshot{'s' * (images != 1)}"] if images else [])
    return (" and ".join(parts) + " selected") if parts else "Nothing selected"


def run(start: Path) -> list[str]:
    import tkinter as tk
    from tkinter import ttk

    if sys.platform.startswith("win"):
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    result: list[str] = []
    root = tk.Tk()
    root.title("Add screenshots")
    root.geometry("860x540")
    root.minsize(560, 360)
    root.attributes("-topmost", True)
    root.after(400, lambda: root.attributes("-topmost", False))  # in front, but not stuck there

    current = {"folder": start, "entries": {}}

    # ---- top bar: up + location -------------------------------------------------
    top = ttk.Frame(root, padding=(8, 8, 8, 4))
    top.pack(fill="x")
    up = ttk.Button(top, text="↑ Up", width=6)
    up.pack(side="left")
    location = tk.StringVar()
    loc_entry = ttk.Entry(top, textvariable=location)
    loc_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

    # ---- body: places | entries ------------------------------------------------
    body = ttk.Frame(root, padding=(8, 0, 8, 0))
    body.pack(fill="both", expand=True)
    place_list = tk.Listbox(body, width=18, activestyle="none", exportselection=False, borderwidth=1)
    place_list.pack(side="left", fill="y", padx=(0, 6))
    shortcuts = places()
    for label, _ in shortcuts:
        place_list.insert("end", label)

    table_frame = ttk.Frame(body)
    table_frame.pack(side="left", fill="both", expand=True)
    tree = ttk.Treeview(table_frame, columns=("kind", "modified"), selectmode="extended")
    tree.heading("#0", text="Name", anchor="w")
    tree.heading("kind", text="Type", anchor="w")
    tree.heading("modified", text="Modified", anchor="w")
    tree.column("#0", width=420, stretch=True)
    tree.column("kind", width=110, stretch=False)
    tree.column("modified", width=150, stretch=False)
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="left", fill="y")

    # ---- bottom: status + buttons ---------------------------------------------
    bottom = ttk.Frame(root, padding=8)
    bottom.pack(fill="x")
    status = tk.StringVar(value="Nothing selected")
    ttk.Label(bottom, textvariable=status).pack(side="left")
    ttk.Label(bottom, text="  ·  Ctrl or Shift picks several. Folders include their subfolders.",
              foreground="gray40").pack(side="left")
    cancel = ttk.Button(bottom, text="Cancel", command=root.destroy)
    cancel.pack(side="right")
    add = ttk.Button(bottom, text="Add", state="disabled")
    add.pack(side="right", padx=(0, 6))
    add_here = ttk.Button(bottom, text="Add this whole folder")
    add_here.pack(side="right", padx=(0, 6))

    def chosen() -> list[tuple[Path, bool]]:
        return [current["entries"][iid] for iid in tree.selection() if iid in current["entries"]]

    def on_select(_event=None) -> None:
        picked = chosen()
        status.set(summary(picked))
        add.configure(state="normal" if picked else "disabled")

    def open_folder(folder: Path) -> None:
        try:
            entries = list_entries(folder)
        except OSError:
            status.set(f"Can't open {folder}")
            return
        current["folder"], current["entries"] = folder, {}
        location.set(str(folder))
        tree.delete(*tree.get_children())
        for path, is_folder in entries:
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                modified = ""
            kind = "Folder" if is_folder else path.suffix[1:].upper() + " image"
            iid = tree.insert("", "end", text=("📁  " if is_folder else "🖼  ") + path.name,
                              values=(kind, modified))
            current["entries"][iid] = (path, is_folder)
        if not entries:
            iid = tree.insert("", "end", text="No folders or screenshots here", values=("", ""))
        up.configure(state="normal" if folder.parent != folder else "disabled")
        add_here.configure(text=f"Add this whole folder ({folder.name or folder})")
        on_select()

    def finish(paths: list[Path]) -> None:
        result.extend(str(p) for p in paths)
        root.destroy()

    def on_double(_event=None) -> None:
        focus = tree.focus()
        if focus in current["entries"]:
            path, is_folder = current["entries"][focus]
            open_folder(path) if is_folder else finish([path])

    def go_to_typed(_event=None) -> None:
        typed = Path(location.get().strip().strip('"')).expanduser()
        if typed.is_dir():
            open_folder(typed)
        elif typed.is_file() and typed.suffix.lower() in SUPPORTED_EXTENSIONS:
            finish([typed])
        else:
            status.set("That folder doesn't exist")

    def on_place(_event=None) -> None:
        sel = place_list.curselection()
        if sel:
            open_folder(shortcuts[sel[0]][1])

    def select_all(_event=None) -> str:
        tree.selection_set([iid for iid in tree.get_children() if iid in current["entries"]])
        return "break"

    up.configure(command=lambda: open_folder(current["folder"].parent))
    add.configure(command=lambda: finish([p for p, _ in chosen()]))
    add_here.configure(command=lambda: finish([current["folder"]]))
    tree.bind("<<TreeviewSelect>>", on_select)
    tree.bind("<Double-1>", on_double)
    tree.bind("<Return>", lambda e: finish([p for p, _ in chosen()]) if chosen() else None)
    tree.bind("<BackSpace>", lambda e: open_folder(current["folder"].parent))
    tree.bind("<Control-a>", select_all)
    loc_entry.bind("<Return>", go_to_typed)
    place_list.bind("<<ListboxSelect>>", on_place)
    root.bind("<Escape>", lambda e: root.destroy())

    open_folder(start if start.is_dir() else Path.home())
    root.lift()
    root.focus_force()
    tree.focus_set()
    root.mainloop()
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # paths with non-ASCII names survive the pipe
    start_arg = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else str(Path.home())
    sys.stdout.write("\n".join(run(Path(start_arg))))
