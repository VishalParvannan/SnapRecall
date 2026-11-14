"""The "Add screenshots" window on Windows: the system's own modern Explorer-style dialog.

One window covers everything: pick one screenshot, several (Ctrl or Shift), or press
"Add this whole folder" to add the folder being viewed (with its subfolders). Folders
selected together with files are added too.

It runs as its own process, like picker_dialog.py: `python windows_picker.py [start folder]`.
It prints the chosen paths, one per line, and nothing if cancelled. Only ctypes is used,
so no extra packages are needed. If the system dialog can't be created, the Tk window in
picker_dialog.py is shown instead.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as wt
from pathlib import Path

from config import SUPPORTED_EXTENSIONS

HRESULT = ctypes.c_long
S_OK = 0
E_NOTIMPL = -2147467263  # 0x80004001
E_NOINTERFACE = -2147467262  # 0x80004002
CANCELLED = -2147023673  # HRESULT_FROM_WIN32(ERROR_CANCELLED)

FOS_NOCHANGEDIR = 0x8
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
SIGDN_FILESYSPATH = 0x80058000
FOLDER_BUTTON = 601


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class FILTERSPEC(ctypes.Structure):
    _fields_ = [("pszName", wt.LPCWSTR), ("pszSpec", wt.LPCWSTR)]


def _guid(text: str) -> GUID:
    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(wt.LPCWSTR(text), ctypes.byref(g))
    return g


CLSID_FileOpenDialog = _guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
IID_IFileOpenDialog = _guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")
IID_IFileDialogCustomize = _guid("{E6FDD21A-163F-4975-9C8C-A69F1BA37034}")
IID_IFileDialogEvents = _guid("{973510DB-7D7F-452B-8975-74A85828D354}")
IID_IFileDialogControlEvents = _guid("{36116642-D713-4B97-9B83-7484A9D00433}")
IID_IUnknown = _guid("{00000000-0000-0000-C000-000000000046}")
IID_IShellItem = _guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")


def _method(ptr: int, index: int, *argtypes):
    """Bind vtable slot `index` of COM object `ptr` (returns the raw HRESULT)."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])
    return lambda *args: fn(ptr, *args)


def _check(hr: int) -> None:
    if hr < 0:
        raise OSError(f"Windows dialog call failed (0x{hr & 0xFFFFFFFF:08X})")


def _release(ptr: int | None) -> None:
    if ptr:
        _method(ptr, 2)()


def _item_path(item: int) -> str:
    out = ctypes.c_void_p()
    _check(_method(item, 5, wt.DWORD, ctypes.POINTER(ctypes.c_void_p))(SIGDN_FILESYSPATH, ctypes.byref(out)))
    try:
        return ctypes.wstring_at(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


class _Events:
    """A tiny COM object implementing IFileDialogEvents + IFileDialogControlEvents,
    so the "Add this whole folder" button can close the dialog with the current folder."""

    def __init__(self, dialog: int) -> None:
        self.dialog = dialog
        self.folder: str | None = None
        P = ctypes.c_void_p
        QI = ctypes.WINFUNCTYPE(HRESULT, P, ctypes.POINTER(GUID), ctypes.POINTER(P))
        REF = ctypes.WINFUNCTYPE(wt.ULONG, P)
        ARG1 = ctypes.WINFUNCTYPE(HRESULT, P, P)
        ARG2 = ctypes.WINFUNCTYPE(HRESULT, P, P, P)
        ARG3 = ctypes.WINFUNCTYPE(HRESULT, P, P, P, ctypes.POINTER(ctypes.c_int))
        ID1 = ctypes.WINFUNCTYPE(HRESULT, P, P, wt.DWORD)
        ID2 = ctypes.WINFUNCTYPE(HRESULT, P, P, wt.DWORD, wt.DWORD)

        ok1, ok2 = ARG1(lambda *_: S_OK), ARG2(lambda *_: S_OK)
        not3 = ARG3(lambda *_: E_NOTIMPL)
        self._funcs = [QI(self._query), REF(lambda _: 1), REF(lambda _: 1)]
        events = self._funcs + [ok1, ok2, ok1, ok1, not3, ok1, not3]  # OnFileOk .. OnOverwrite
        controls = self._funcs + [ID2(lambda *_: S_OK), ID1(self._clicked),
                                  ID2(lambda *_: S_OK), ID1(lambda *_: S_OK)]
        self._keep = [events, controls, ok1, ok2, not3]
        self._vtbls = [(ctypes.c_void_p * len(v))(*[ctypes.cast(f, ctypes.c_void_p) for f in v])
                       for v in (events, controls)]
        self._objs = [ctypes.c_void_p(ctypes.addressof(v)) for v in self._vtbls]
        self.events_ptr, self.controls_ptr = (ctypes.addressof(o) for o in self._objs)

    def _query(self, _this, riid, ppv) -> int:
        iid = bytes(riid.contents)
        if iid in (bytes(IID_IUnknown), bytes(IID_IFileDialogEvents)):
            ppv[0] = self.events_ptr
        elif iid == bytes(IID_IFileDialogControlEvents):
            ppv[0] = self.controls_ptr
        else:
            ppv[0] = None
            return E_NOINTERFACE
        return S_OK

    def _clicked(self, _this, _customize, control_id) -> int:
        if control_id == FOLDER_BUTTON:
            try:
                item = ctypes.c_void_p()
                _check(_method(self.dialog, 13, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(item)))  # GetFolder
                try:
                    self.folder = _item_path(item.value)
                finally:
                    _release(item.value)
                _method(self.dialog, 23, HRESULT)(S_OK)  # Close: Show() returns now
            except OSError:
                pass  # e.g. a virtual location like "This PC": nothing to add, stay open
        return S_OK


def _owner_window() -> int:
    """A hidden, always-on-top owner so the dialog opens in front of the browser."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    _owner_window.root = root  # keep it alive while the dialog is open
    return int(root.wm_frame(), 16)


def run(start: Path) -> list[str]:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 2)  # apartment-threaded, as the dialog requires

    dialog = ctypes.c_void_p()
    _check(ole32.CoCreateInstance(ctypes.byref(CLSID_FileOpenDialog), None, 1,  # CLSCTX_INPROC_SERVER
                                  ctypes.byref(IID_IFileOpenDialog), ctypes.byref(dialog)))
    d = dialog.value
    customize = ctypes.c_void_p()
    events = _Events(d)
    cookie = wt.DWORD()
    try:
        spec = ";".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        filters = (FILTERSPEC * 2)(FILTERSPEC("Screenshots (PNG, JPEG)", spec), FILTERSPEC("All files", "*.*"))
        _check(_method(d, 4, wt.UINT, ctypes.POINTER(FILTERSPEC))(2, filters))  # SetFileTypes
        options = wt.DWORD()
        _check(_method(d, 10, ctypes.POINTER(wt.DWORD))(ctypes.byref(options)))  # GetOptions
        _check(_method(d, 9, wt.DWORD)(options.value | FOS_ALLOWMULTISELECT | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR))
        _check(_method(d, 17, wt.LPCWSTR)("Add Screenshots"))
        _check(_method(d, 18, wt.LPCWSTR)("Add selected"))  # SetOkButtonLabel

        if start.is_dir():
            folder = ctypes.c_void_p()
            make = ctypes.windll.shell32.SHCreateItemFromParsingName
            make.argtypes = [wt.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
            if make(str(start), None, ctypes.byref(IID_IShellItem), ctypes.byref(folder)) == S_OK:
                _method(d, 12, ctypes.c_void_p)(folder.value)  # SetFolder
                _release(folder.value)

        _check(_method(d, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
            ctypes.byref(IID_IFileDialogCustomize), ctypes.byref(customize)))
        _check(_method(customize.value, 5, wt.DWORD, wt.LPCWSTR)(FOLDER_BUTTON, "Add this whole folder"))
        _check(_method(d, 7, ctypes.c_void_p, ctypes.POINTER(wt.DWORD))(events.events_ptr, ctypes.byref(cookie)))

        hr = _method(d, 3, wt.HWND)(_owner_window())  # Show
        if events.folder:
            return [events.folder]
        if hr == CANCELLED:
            return []
        _check(hr)

        results = ctypes.c_void_p()
        _check(_method(d, 27, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(results)))  # GetResults
        try:
            count = wt.DWORD()
            _check(_method(results.value, 7, ctypes.POINTER(wt.DWORD))(ctypes.byref(count)))
            paths = []
            for i in range(count.value):
                item = ctypes.c_void_p()
                _check(_method(results.value, 8, wt.DWORD, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(item)))
                try:
                    paths.append(_item_path(item.value))
                finally:
                    _release(item.value)
            return paths
        finally:
            _release(results.value)
    finally:
        if cookie.value:
            _method(d, 8, wt.DWORD)(cookie.value)  # Unadvise
        _release(customize.value)
        _release(d)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # paths with non-ASCII names survive the pipe
    try:  # crisp, full-resolution dialog on high-DPI screens
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001 - cosmetic only
        pass
    start_arg = Path(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else str(Path.home()))
    try:
        chosen = run(start_arg)
    except OSError:
        import picker_dialog
        chosen = picker_dialog.run(start_arg)
    sys.stdout.write("\n".join(chosen))
