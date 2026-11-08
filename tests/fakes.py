"""Small deterministic stand-ins for the OCR and image-text models."""
from __future__ import annotations

import numpy as np
from PIL import Image

from models import OcrResult, normalize

COLORS = {
    "red": (220, 30, 30),
    "green": (30, 180, 60),
    "blue": (30, 60, 220),
    "yellow": (240, 220, 40),
    "black": (10, 10, 10),
    "white": (245, 245, 245),
}


def dominant_color(image: Image.Image) -> str:
    mean = np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0)
    return min(COLORS, key=lambda c: float(np.sum((np.array(COLORS[c]) - mean) ** 2)))


class FakeOcr:
    """Returns a fixed text for each dominant image color."""

    def __init__(self, texts: dict[str, str], name: str = "fake-ocr-1", fail: bool = False):
        self.texts, self.name, self.fail = texts, name, fail
        self.calls = 0

    def extract(self, image: Image.Image) -> OcrResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated OCR failure")
        text = self.texts.get(dominant_color(image), "")
        return OcrResult(text, 0.9 if text else None)


def color_vector(color) -> np.ndarray:
    """Embedding for a mean color. The 4th dimension is reserved for text with no color words,
    so such a query is unrelated to every image, as with a real model."""
    return normalize(np.append(np.asarray(color, dtype=np.float32) - 127.5, 0.0))


class FakeEmbedder:
    """Embeds images by mean color and text by the color words it mentions."""

    name = "fake-clip-1"

    def __init__(self, name: str | None = None):
        if name:
            self.name = name
        self.calls = 0

    def embed_image(self, image: Image.Image) -> np.ndarray:
        self.calls += 1
        return color_vector(np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0))

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        return np.stack([self.embed_image(im) for im in images])

    def embed_text(self, text: str) -> np.ndarray:
        words = [w for w in text.lower().split() if w in COLORS]
        if not words:
            return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        return color_vector(np.mean([COLORS[w] for w in words], axis=0))
