"""Adapters for the pretrained OCR and image-text models.

Both adapters expose a `name` that identifies the model and its settings.
The indexer stores that name with each result, so changing the model
causes affected images to be reprocessed.

Heavy libraries are imported lazily so the rest of the app (and the tests)
work without them installed.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np
from PIL import Image

from config import Config


class ModelLoadError(RuntimeError):
    """A model could not be loaded; the message is safe to show to users."""


class OcrEngine(Protocol):
    name: str

    def extract(self, image: Image.Image) -> str: ...


class Embedder(Protocol):
    name: str

    def embed_image(self, image: Image.Image) -> np.ndarray: ...

    def embed_text(self, text: str) -> np.ndarray: ...


def normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


class EasyOcrEngine:
    def __init__(self, languages: tuple[str, ...], gpu: bool = False):
        try:
            import easyocr
        except ImportError as exc:
            raise ModelLoadError(
                "Text recognition needs EasyOCR. Install it with "
                "`pip install -r requirements-models.txt`."
            ) from exc
        try:
            self._reader = easyocr.Reader(list(languages), gpu=gpu, verbose=False)
        except Exception as exc:  # download or weight-loading problems
            raise ModelLoadError(
                f"Could not load the text recognition model ({exc.__class__.__name__}). "
                "The first run needs an internet connection to download it."
            ) from exc
        self.name = f"easyocr-{easyocr.__version__}:{'+'.join(languages)}"

    def extract(self, image: Image.Image) -> str:
        lines = self._reader.readtext(np.asarray(image.convert("RGB")), detail=0, paragraph=True)
        return "\n".join(lines)


class OpenClipEmbedder:
    def __init__(self, model_name: str, pretrained: str):
        try:
            import open_clip
            import torch
        except ImportError as exc:
            raise ModelLoadError(
                "Visual search needs OpenCLIP and PyTorch. Install them with "
                "`pip install -r requirements-models.txt`."
            ) from exc
        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=pretrained, device=self._device
            )
        except Exception as exc:
            raise ModelLoadError(
                f"Could not load the visual search model ({exc.__class__.__name__}). "
                "The first run needs an internet connection to download it."
            ) from exc
        model.eval()
        self._model = model
        self._preprocess = preprocess
        self._tokenizer = open_clip.get_tokenizer(model_name)
        self.name = f"open_clip:{model_name}:{pretrained}"

    def embed_image(self, image: Image.Image) -> np.ndarray:
        batch = self._preprocess(image.convert("RGB")).unsqueeze(0).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_image(batch)[0]
        return normalize(features.float().cpu().numpy())

    def embed_text(self, text: str) -> np.ndarray:
        tokens = self._tokenizer([text]).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_text(tokens)[0]
        return normalize(features.float().cpu().numpy())


def load_ocr(config: Config) -> OcrEngine | None:
    """Return the configured OCR engine, None if disabled, or raise ModelLoadError."""
    if not config.enable_ocr:
        return None
    return EasyOcrEngine(config.ocr_languages)


def load_embedder(config: Config) -> Embedder | None:
    """Return the configured embedder, None if disabled, or raise ModelLoadError."""
    if not config.enable_visual:
        return None
    return OpenClipEmbedder(config.clip_model, config.clip_pretrained)
