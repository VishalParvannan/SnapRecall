"""Small deterministic stand-ins for the OCR and image-text models."""
from __future__ import annotations

import numpy as np
from PIL import Image

from models import normalize

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

    def extract(self, image: Image.Image) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated OCR failure")
        return self.texts.get(dominant_color(image), "")


class FakeEmbedder:
    """Embeds images by mean color and text by the color words it mentions."""

    name = "fake-clip-1"

    def __init__(self, name: str | None = None):
        if name:
            self.name = name
        self.calls = 0

    def embed_image(self, image: Image.Image) -> np.ndarray:
        self.calls += 1
        mean = np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0)
        return normalize(mean - 127.5)

    def embed_text(self, text: str) -> np.ndarray:
        words = [w for w in text.lower().split() if w in COLORS]
        if not words:
            return normalize(np.array([0.01, 0.0, -0.01]))
        return normalize(np.mean([np.array(COLORS[w]) - 127.5 for w in words], axis=0))
