"""Adapters for the pretrained OCR and image-text models.

Both adapters expose a `name` that identifies the model and its settings.
The indexer stores that name with each result, so changing the model
causes affected images to be reprocessed.

Heavy libraries are imported lazily so the rest of the app (and the tests)
work without them installed.
"""
from __future__ import annotations

import atexit
import logging
import pickle
import subprocess
import sys
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

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


class SentenceEmbedder:
    """Compares meanings of short texts, used to match a query with a screenshot's recognized text.

    Unlike CLIP's text encoder, it is trained on sentence similarity, so words that go together
    ("plane", "departures", "baggage") land close together though they share no letters.
    Texts longer than the model's input limit (256 word pieces for the default model) are cut off.
    """

    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ModelLoadError(
                "Matching text by meaning needs sentence-transformers. Install it with "
                "`pip install -r requirements-models.txt`."
            ) from exc
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
                self._model = SentenceTransformer(model_name)
        except Exception as exc:
            raise ModelLoadError(
                f"Could not load the text meaning model ({exc.__class__.__name__}). "
                "The first run needs an internet connection to download it."
            ) from exc
        self.name = f"sentence-transformers:{model_name}"

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """One normalized row per text."""
        vectors = self._model.encode(list(texts), batch_size=32, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]


# ---- loading models without slowing the app down ----------------------------
def _load_problem(exc: Exception) -> str:
    if isinstance(exc, ModelLoadError):
        return str(exc)
    return f"A model failed to load ({exc.__class__.__name__})."


_WORKER = Path(__file__).resolve().parent / "model_worker.py"


class _Pipe:
    """Pickled messages over a helper process's stdin/stdout (the protocol in model_worker.py)."""

    def __init__(self, process: subprocess.Popen):
        self.process = process

    def send(self, message) -> None:
        pickle.dump(message, self.process.stdin, protocol=pickle.HIGHEST_PROTOCOL)
        self.process.stdin.flush()

    def recv(self):
        return pickle.load(self.process.stdout)  # waiting here releases the interpreter lock


class ModelProcess:
    """A model running in its own process, used like the model itself (same methods and `name`).

    Calls are serialized with a lock: one model process handles one request at a time."""

    def __init__(self, pipe: _Pipe, name: str, methods: list[str]):
        self._pipe, self._process, self.name = pipe, pipe.process, name
        self._methods = frozenset(methods)  # only what the real model has (embed_texts is optional)
        self._lock = threading.Lock()

    def _call(self, method: str, *args):
        with self._lock:
            try:
                self._pipe.send((method, args))
                status, value = self._pipe.recv()
            except (EOFError, OSError) as exc:
                raise RuntimeError("The model process stopped unexpectedly. Restart SnapRecall.") from exc
        if status != "ok":
            raise RuntimeError(value)
        return value

    def __getattr__(self, method: str):
        if method.startswith("_") or method not in self._methods:
            raise AttributeError(method)
        return lambda *args: self._call(method, *args)


_MODEL_METHODS = {"extract", "embed_image", "embed_images", "embed_text", "embed_texts"}
_helpers: list[subprocess.Popen] = []


@atexit.register
def _stop_helpers() -> None:
    """Closing stdin tells a helper to exit (it also does if this process is killed)."""
    for process in _helpers:
        try:
            process.stdin.close()
        except OSError:
            pass


class BackgroundModels:
    """Loads the models in the background so the app is usable meanwhile.

    Loading takes about 25 s on a laptop CPU, nearly all of it importing PyTorch/OpenCLIP/EasyOCR
    and building the models (not downloading). Loading them on a thread of the app's own process
    made pages about 5x slower while it ran (the work competes for Python's interpreter lock), so
    by default each model loads and runs in its own helper process; the visual model and text
    recognition load in parallel. Until a model is ready its attribute is None, which search already
    handles (text matches only); indexing waits for `done`. A helper process (model_worker.py) exits
    by itself when the app does (its stdin closes).

    `in_process=True` loads on threads of this process instead (used by tests).
    """

    def __init__(self, config: Config, start: bool = True, in_process: bool = False,
                 loaders: dict[str, Callable[[Config], object]] | None = None):
        self.config = config
        self.ocr: OcrEngine | None = None
        self.embedder: Embedder | None = None
        self.text_model: SentenceEmbedder | None = None  # compares a query's meaning with recognized text
        self._problems: dict[str, str] = {}
        self._loaders = loaders or {"embedder": load_embedder, "ocr": load_ocr, "text_model": load_text_model}
        self._in_process = in_process
        self._done = threading.Event()
        if start:
            threading.Thread(target=self._load_all, name="snaprecall-models", daemon=True).start()

    @property
    def problems(self) -> list[str]:
        return [self._problems[k] for k in self._loaders if k in self._problems]

    def _load_all(self) -> None:
        try:
            threads = [threading.Thread(target=self._load_one, args=item, daemon=True)
                       for item in self._loaders.items()]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            self._done.set()

    def _load_one(self, attr: str, loader: Callable[[Config], object]) -> None:
        if not getattr(self.config, _SWITCHES.get(loader, ""), True):
            return  # turned off in settings: no helper process needed
        try:
            setattr(self, attr, loader(self.config) if self._in_process else self._spawn(loader))
        except Exception as exc:  # never leave the app waiting forever
            self._problems[attr] = _load_problem(exc)

    def _spawn(self, loader: Callable[[Config], object]) -> ModelProcess | None:
        # A plain subprocess, not multiprocessing: under Streamlit, multiprocessing's spawn re-runs
        # the main script (app.py) in the child.
        process = subprocess.Popen(
            [sys.executable, str(_WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _helpers.append(process)
        pipe = _Pipe(process)
        try:
            pipe.send(list(sys.path))
            pipe.send((loader, self.config))
            status, value = pipe.recv()
        except (EOFError, OSError):
            raise ModelLoadError("The model process stopped while loading.") from None
        if status != "ok":
            raise ModelLoadError(value)
        return None if value is None else ModelProcess(pipe, *value)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until every model has loaded or failed; True when finished."""
        return self._done.wait(timeout)


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


def load_text_model(config: Config) -> SentenceEmbedder | None:
    """Return the text meaning model, None if disabled, or raise ModelLoadError."""
    if not config.use_text_meaning:
        return None
    return SentenceEmbedder(config.text_model)


_SWITCHES = {load_embedder: "enable_visual", load_ocr: "enable_ocr",
             load_text_model: "use_text_meaning"}  # Config flag per loader
