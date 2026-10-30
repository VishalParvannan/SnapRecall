import os
from pathlib import Path

import pytest
from PIL import Image

from config import load_config
from storage import Storage


@pytest.fixture
def env(tmp_path):
    shots = (tmp_path / "shots").resolve()
    shots.mkdir()
    config = load_config(tmp_path / "index")
    return shots, config, Storage(config.db_path)


def make_image(path: Path, color=(220, 30, 30), size=(64, 48)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def bump_mtime(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
