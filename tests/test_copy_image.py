import base64
import io
import re

import pytest
from PIL import Image

from conftest import make_image
from copy_image import MESSAGES, CopyImageError, clipboard_png, copy_button_html


def decode(png: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(png))
    img.load()
    return img


def test_png_keeps_full_resolution_and_pixels(tmp_path):
    src = make_image(tmp_path / "shot.png", (10, 120, 200), size=(1920, 1080))
    out = decode(clipboard_png(src))
    assert out.format == "PNG" and out.size == (1920, 1080)
    assert out.getpixel((5, 5)) == (10, 120, 200)


def test_jpeg_is_converted_to_png(tmp_path):
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (640, 480), (200, 30, 30)).save(src, quality=95)
    out = decode(clipboard_png(src))
    assert out.format == "PNG" and out.size == (640, 480) and out.mode == "RGB"


def test_transparency_is_preserved(tmp_path):
    src = tmp_path / "alpha.png"
    img = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
    img.putpixel((10, 10), (0, 255, 0, 128))
    img.save(src)
    out = decode(clipboard_png(src))
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((10, 10)) == (0, 255, 0, 128)


def test_palette_transparency_is_preserved(tmp_path):
    src = tmp_path / "palette.png"
    img = Image.new("P", (20, 20), 0)
    img.putpalette([255, 255, 255, 0, 0, 0] + [0] * 762)
    img.info["transparency"] = 0
    img.save(src, transparency=0)
    assert decode(clipboard_png(src)).mode == "RGBA"


def test_original_is_not_modified(tmp_path):
    src = make_image(tmp_path / "shot.png")
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    clipboard_png(src)
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before


def test_missing_file_error(tmp_path):
    with pytest.raises(CopyImageError, match="missing"):
        clipboard_png(tmp_path / "gone.png")


def test_corrupt_file_error(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(CopyImageError, match="can't be read"):
        clipboard_png(bad)


def test_too_large_error(tmp_path, monkeypatch):
    import copy_image
    monkeypatch.setattr(copy_image, "MAX_PNG_BYTES", 10)
    with pytest.raises(CopyImageError, match="too large"):
        clipboard_png(make_image(tmp_path / "a.png"))


def test_button_embeds_exact_png_and_messages(tmp_path):
    png = clipboard_png(make_image(tmp_path / "a.png"))
    page = copy_button_html(png, label="Copy <image>")
    data = re.search(r'const DATA = "([^"]+)"', page).group(1)
    assert base64.b64decode(data) == png
    assert "Copy &lt;image&gt;" in page
    assert '"image/png"' in page and "NotAllowedError" in page
    for text in MESSAGES.values():
        assert text.split("{")[0][:20] in page
