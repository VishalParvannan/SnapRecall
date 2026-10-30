import subprocess

import pytest

import folder_picker
from folder_picker import FolderPickerError, pick_folder


def fake_run(stdout="", returncode=0, exc=None):
    def run(*args, **kwargs):
        if exc:
            raise exc
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")
    return run


def test_returns_chosen_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run(stdout=tmp_path.as_posix()))
    assert pick_folder() == str(tmp_path)


def test_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run(stdout=""))
    assert pick_folder() is None


@pytest.mark.parametrize("kwargs", [dict(returncode=1), dict(exc=OSError("no display"))])
def test_failure_raises_friendly_error(monkeypatch, kwargs):
    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run(**kwargs))
    with pytest.raises(FolderPickerError):
        pick_folder()
