import subprocess
from pathlib import Path

import pytest

import folder_picker
import picker_dialog
from folder_picker import FolderPickerError, pick_screenshots


def fake_run(stdout="", returncode=0, exc=None):
    def run(*args, **kwargs):
        if exc:
            raise exc
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")
    return run


def test_returns_chosen_folders_and_files_together(monkeypatch, tmp_path):
    folder, shot = tmp_path / "shots", tmp_path / "a.png"
    monkeypatch.setattr(folder_picker.subprocess, "run",
                        fake_run(stdout=f"{folder.as_posix()}\n{shot.as_posix()}\n"))
    assert pick_screenshots() == [str(folder), str(shot)]


def test_cancel_returns_nothing(monkeypatch):
    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run(stdout=""))
    assert pick_screenshots() == []


@pytest.mark.parametrize("kwargs", [{"returncode": 1}, {"exc": OSError("no display")},
                                    {"exc": subprocess.TimeoutExpired("x", 1)}])
def test_picker_failure_raises(monkeypatch, kwargs):
    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run(**kwargs))
    with pytest.raises(FolderPickerError, match="picker"):
        pick_screenshots()


def test_window_lists_folders_first_then_only_screenshots(tmp_path):
    (tmp_path / "zeta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    for name in ("b.PNG", "a.jpg", "c.jpeg", "notes.txt", "clip.gif"):
        (tmp_path / name).write_bytes(b"")
    names = [(p.name, is_folder) for p, is_folder in picker_dialog.list_entries(tmp_path)]
    assert names == [("Alpha", True), ("zeta", True), ("a.jpg", False), ("b.PNG", False), ("c.jpeg", False)]


def test_unreadable_folder_raises(tmp_path):
    with pytest.raises(OSError):
        picker_dialog.list_entries(tmp_path / "missing")


def test_selection_summary():
    folder, shot = (Path("f"), True), (Path("a.png"), False)
    assert picker_dialog.summary([]) == "Nothing selected"
    assert picker_dialog.summary([folder, shot, shot]) == "1 folder and 2 screenshots selected"
