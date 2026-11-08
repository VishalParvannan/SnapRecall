"""Adapters for the pretrained OCR and image-text models.

Both adapters expose a `name` that identifies the model and its settings.
The indexer stores that name with each result, so changing the model
causes affected images to be reprocessed.

Heavy libraries are imported lazily so the rest of the app (and the tests)
work without them installed.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

from config import Config


class ModelLoadError(RuntimeError):
    """A model could not be loaded; the message is safe to show to users."""


@dataclass
class OcrResult:
    text: str
    confidence: float | None = None  # recognizer confidence 0-1, weighted by text length


class OcrEngine(Protocol):
    name: str

    def extract(self, image: Image.Image) -> OcrResult: ...


class Embedder(Protocol):
    name: str

    def embed_image(self, image: Image.Image) -> np.ndarray: ...

    def embed_images(self, images: list[Image.Image]) -> np.ndarray: ...

    def embed_text(self, text: str) -> np.ndarray: ...


def embed_texts(embedder: Embedder, texts: list[str], batch_size: int = 64) -> np.ndarray:
    """One row per text, batched when the embedder supports it."""
    batch = getattr(embedder, "embed_texts", None)
    if batch is None:
        return np.stack([embedder.embed_text(t) for t in texts])
    return np.vstack([batch(texts[i:i + batch_size]) for i in range(0, len(texts), batch_size)])


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
            # EasyOCR quantizes its CPU model with a deprecated torch API; the
            # resulting warning is harmless noise.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*quantiz.*", category=UserWarning)
                warnings.filterwarnings("ignore", category=DeprecationWarning)
                self._reader = easyocr.Reader(list(languages), gpu=gpu, verbose=False)
        except Exception as exc:  # download or weight-loading problems
            raise ModelLoadError(
                f"Could not load the text recognition model ({exc.__class__.__name__}). "
                "The first run needs an internet connection to download it."
            ) from exc
        self.name = f"easyocr-{easyocr.__version__}:{'+'.join(languages)}"

    def extract(self, image: Image.Image) -> OcrResult:
        from easyocr.utils import get_paragraph

        # Paragraph mode drops per-line confidences, so read lines with their confidence and
        # group them with EasyOCR's own paragraph step (same text as readtext(paragraph=True)).
        lines = self._reader.readtext(np.asarray(image.convert("RGB")), detail=1, paragraph=False)
        if not lines:
            return OcrResult("", None)
        weights = [max(len(text.strip()), 1) for _, text, _ in lines]
        confidence = sum(w * float(c) for w, (_, _, c) in zip(weights, lines)) / sum(weights)
        paragraphs = get_paragraph(lines, x_ths=1.0, y_ths=0.5, mode="ltr")
        return OcrResult("\n".join(text for _, text in paragraphs), round(confidence, 4))


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
        # Public weights need no Hugging Face token; silence the reminder.
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
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

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        """Embed several images in one batch; returns one normalized row per image."""
        batch = self._torch.stack([self._preprocess(im.convert("RGB")) for im in images]).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_image(batch).float().cpu().numpy()
        return features / np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-12)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Embed several texts in one batch (much faster than one at a time on a CPU)."""
        tokens = self._tokenizer(list(texts)).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_text(tokens).float().cpu().numpy()
        return features / np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-12)

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
