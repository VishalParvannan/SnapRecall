"""Generated labels: the likely source app and concrete objects or scenes.

Labels are uncertain metadata. They come from the pretrained image-text model already used for
visual search (no extra download) plus recognized text, are shown as "may be wrong", and only
supplement search: on their own they never make a result a strong match.

Source app
----------
An app is named only when there is evidence for it:
  * interface: the screenshot looks like the app. The image is compared with prompts that
    describe each app and with generic alternatives ("a website", "a photo", ...), and the
    similarities are turned into probabilities (softmax at CLIP's temperature).
  * text: recognized text contains interface wording specific to the app (strong, e.g.
    "Message @alex"), or merely mentions the app's name (weak: people mention apps anywhere).
The two are combined as independent evidence, 1 - (1 - visual)(1 - text). The source stays
unknown unless the best app reaches APP_MIN_CONFIDENCE and beats the runner-up by
APP_MIN_MARGIN. The filename and the app that was open when the screenshot was taken are never
used: neither proves where the content came from.

Tags
----
Concrete objects and scenes (fire, dog, beach, ...). The whole screenshot's similarities to every
tag and to generic "this is just text/an interface/shapes" prompts are turned into probabilities;
a tag is kept when it reaches TAG_MIN_SCORE. Tags never name people.

Tuning (samples/eval plus one real screenshot, see README): tags from small regions were often
confident nonsense ("train" for a chat message), so tags use the whole image only; "flag", "meme",
"logo", "chart", "calendar" and "rain" fired on plain text and shape screens and were removed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from models import Embedder, embed_texts, normalize

# Bump when the labelling logic changes. Prompt, vocabulary, and threshold changes are detected
# automatically (see label_model). Either way labels are recomputed cheaply from stored data.
LABELS_VERSION = "labels-1"
LOGIT_SCALE = 100.0  # CLIP's learned softmax temperature
APP_MIN_CONFIDENCE = 0.5
APP_MIN_MARGIN = 0.15
INTERFACE_EVIDENCE = 0.2  # visual probability needed to cite "interface" as evidence
NAME_MENTION = 0.3
UI_TEXT_ONE = 0.55
UI_TEXT_MORE = 0.75
TAG_MIN_SCORE = 0.6
MAX_TAGS = 3


@dataclass(frozen=True)
class App:
    name: str
    prompts: tuple[str, ...]
    ui_text: tuple[str, ...] = ()   # regexes for interface wording specific to the app
    aliases: tuple[str, ...] = ()   # extra words that find it in search
    mentions: tuple[str, ...] = ()  # words whose presence is weak evidence (default: the name)


APPS = (
    App("Discord", ("a screenshot of a Discord message", "a Discord chat message with a round profile picture"),
        (r"\bmessage @\w", r"\bmessage #[\w-]+", r"\bdirect messages\b", r"\bdiscord nitro\b",
         r"\bserver boost", r"\btext channels\b", r"\bvoice channels\b")),
    App("Slack", ("a screenshot of a Slack workspace", "the Slack app with channels and threads"),
        (r"\bmessage #[\w-]+", r"\bslackbot\b", r"\bhuddles?\b", r"\badd channels\b")),
    App("Microsoft Teams", ("a screenshot of Microsoft Teams", "a Microsoft Teams chat or meeting"),
        (r"\btype a (new )?message\b", r"\bjoin teams meeting\b"), ("teams",), ("microsoft teams",)),
    App("Zoom", ("a screenshot of a Zoom video call",), (r"\bleave meeting\b", r"\bstart video\b")),
    App("WhatsApp", ("a screenshot of a WhatsApp chat", "WhatsApp messages with green chat bubbles"),
        (r"\bend-to-end encrypted\b",)),
    App("Messages", ("a screenshot of an iPhone iMessage conversation", "a text message conversation"),
        (r"\bimessage\b",), ("imessage", "texts", "sms")),
    App("Telegram", ("a screenshot of a Telegram chat",)),
    App("Messenger", ("a screenshot of Facebook Messenger",)),
    App("Instagram", ("a screenshot of an Instagram post", "the Instagram app feed"),
        (r"\bliked by\b", r"\bview all \d+ comments\b")),
    App("X (Twitter)", ("a screenshot of a tweet on Twitter", "a post on X, formerly Twitter"),
        (r"\breposts?\b", r"\bretweets?\b", r"\bquote tweets?\b", r"\bwhat's happening\b",
         r"\bpost your reply\b"), ("twitter", "tweet"), ("twitter",)),
    App("Reddit", ("a screenshot of a Reddit thread", "a Reddit post with upvotes and comments"),
        (r"(?<![\w/])r/\w{3,}", r"(?<![\w/])u/\w{3,}", r"\bupvotes?\b", r"\bjoin the conversation\b")),
    App("Facebook", ("a screenshot of a Facebook post",), (r"\bwhat's on your mind\b",)),
    App("LinkedIn", ("a screenshot of LinkedIn",), (r"\bopen to work\b",)),
    App("TikTok", ("a screenshot of a TikTok video",)),
    App("YouTube", ("a screenshot of a YouTube video page", "the YouTube website with video thumbnails"),
        (r"\bsubscribers\b", r"\b[\d.,]+[km]? views\b")),
    App("Twitch", ("a screenshot of a Twitch live stream",), (r"\bstream chat\b",)),
    App("Netflix", ("a screenshot of Netflix",)),
    App("Spotify", ("a screenshot of the Spotify music app",), (r"\bliked songs\b",)),
    App("Gmail", ("a screenshot of the Gmail inbox", "an email open in Gmail"),
        (r"\bsnoozed\b", r"\bprimary\b.*\bpromotions\b"), ("email", "mail")),
    App("Outlook", ("a screenshot of Microsoft Outlook email",), (r"\bfocused\b\s+\bother\b",), ("email", "mail")),
    App("Google Search", ("a screenshot of Google search results",),
        (r"\babout [\d,]+ results\b", r"\bpeople also ask\b"), ("google",), ("google",)),
    App("Google Maps", ("a screenshot of Google Maps",), (), ("map",)),
    App("Wikipedia", ("a screenshot of a Wikipedia article",), (r"from wikipedia, the free encyclopedia",)),
    App("Amazon", ("a screenshot of an Amazon product page",), (r"\bamazon'?s choice\b", r"\bships from\b")),
    App("GitHub", ("a screenshot of a GitHub repository page",), (r"\bpull requests\b",)),
    App("Stack Overflow", ("a screenshot of a Stack Overflow question",),
        (r"\basked \d+ \w+ ago\b", r"\bviewed [\d,]+ times\b"), (), ("stack overflow", "stackoverflow")),
    App("ChatGPT", ("a screenshot of a ChatGPT conversation",), (r"\bmessage chatgpt\b", r"chatgpt can make mistakes")),
    App("Claude", ("a screenshot of a conversation with the Claude AI assistant",),
        (r"\bclaude can make mistakes\b", r"\breply to claude\b"), (), ("claude",)),
    App("Visual Studio Code", ("a screenshot of the VS Code code editor",),
        (r"\bdebug console\b", r"\bvisual studio code\b"), ("vscode", "editor"), ("vs code", "vscode")),
    App("PowerShell", ("a screenshot of a Windows PowerShell window",),
        # OCR often reads the backslash in "PS C:\" as I, l, or |.
        (r"(?<!\w)PS [A-Z]:[\\|Il/]", r"\bwindows powershell\b"), ("terminal", "console", "shell")),
    App("Command Prompt", ("a screenshot of the Windows Command Prompt",),
        (r"\bmicrosoft windows \[version", r"^\s*[A-Z]:\\[^>\n]*>"), ("cmd", "terminal", "console")),
    App("Terminal", ("a screenshot of a terminal window with a command line",),
        (r"\w+@[\w.-]+:[~/]\S*\$",), ("console", "shell", "bash")),
    App("Microsoft Excel", ("a screenshot of a Microsoft Excel spreadsheet",),
        (r"\bsheet\d+\b", r"\bformulas\b.*\bdata\b.*\breview\b"), ("excel", "spreadsheet"), ("excel",)),
    App("Google Sheets", ("a screenshot of a Google Sheets spreadsheet",), (), ("spreadsheet",)),
    App("Microsoft Word", ("a screenshot of a Microsoft Word document",),
        (r"\bpage \d+ of \d+\b",), ("word", "document"), ("microsoft word",)),
    App("PowerPoint", ("a screenshot of a PowerPoint slide",), (r"\bclick to add (title|text)\b",),
        ("slides", "presentation")),
    App("File Explorer", ("a screenshot of Windows File Explorer",), (r"\bthis pc\b", r"\bquick access\b"),
        ("files", "folder"), ("file explorer",)),
    App("Windows Settings", ("a screenshot of the Windows Settings app",),
        (r"\bwindows update\b", r"\bbluetooth & devices\b"), ("settings",), ()),
    App("Steam", ("a screenshot of the Steam game store",)),
    App("Minecraft", ("a screenshot of the game Minecraft",)),
)

# Alternatives an app has to beat: most screenshots are not from any particular known app.
GENERIC_SCREENS = (
    "a screenshot of a website", "a screenshot of a phone app", "a screenshot of a desktop program",
    "a screenshot of a chat conversation", "a screenshot of an email", "a screenshot of a document",
    "a screenshot of computer code", "a screenshot of a video game", "a screenshot of a social media post",
    "a photo", "a drawing or illustration", "a simple graphic with shapes and colors",
    "a screenshot of text on a plain background",
)

# Concrete objects and scenes. Each tag has one or more descriptions of what it looks like.
TAGS = {
    "fire": ("fire", "flames"), "smoke": ("smoke",), "sunset": ("a sunset", "a sunrise"),
    "night sky": ("a night sky with stars", "the moon at night"), "clouds": ("clouds in the sky",),
    "beach": ("a beach",), "ocean": ("the ocean", "waves on the sea"), "lake": ("a lake",),
    "mountain": ("mountains",), "forest": ("a forest with trees",), "grass field": ("a green grass field",),
    "flower": ("flowers",), "snow": ("snow",), "desert": ("a desert",),
    "city": ("a city skyline", "a city street"), "building": ("a building",), "room": ("the inside of a room",),
    "car": ("a car",), "bus": ("a bus",), "train": ("a train",), "airplane": ("an airplane",),
    "bicycle": ("a bicycle",), "boat": ("a boat",),
    "dog": ("a dog",), "cat": ("a cat",), "bird": ("a bird",), "horse": ("a horse",), "fish": ("a fish",),
    "person": ("a person",), "face": ("a close-up of a person's face",), "group of people": ("a group of people",),
    "baby": ("a baby",),
    "food": ("a plate of food",), "pizza": ("pizza",), "burger": ("a burger",), "cake": ("a cake",),
    "coffee": ("a cup of coffee",), "drink": ("a drink in a glass",), "fruit": ("fruit",),
    "money": ("money and cash",), "credit card": ("a credit card",), "receipt": ("a paper receipt",),
    "ticket": ("a ticket",), "map": ("a map",),
    "qr code": ("a QR code",), "barcode": ("a barcode",),
    "keyboard": ("a computer keyboard",), "phone": ("a smartphone",), "laptop": ("a laptop",),
    "television": ("a television",), "game controller": ("a video game controller",),
    "basketball": ("basketball", "a basketball player"), "soccer": ("a soccer match", "a soccer ball"),
    "american football": ("american football",), "baseball": ("baseball",), "trophy": ("a trophy",),
    "book": ("a book",), "painting": ("a painting",), "cartoon": ("a cartoon",), "anime": ("anime",),
    "stop sign": ("a stop sign",), "traffic light": ("a traffic light",),
    "checkerboard pattern": ("a checkerboard pattern",), "stripes": ("a striped pattern",),
}
# What a screenshot region usually is when it shows none of the tags.
TAG_BACKGROUNDS = (
    "text", "a screenshot of an app", "a website", "a document", "a user interface with buttons",
    "a plain color background", "an abstract shape", "colored rectangles and shapes",
    "a screenshot of words and sentences", "a chat message", "a list of items",
)


@dataclass
class Labels:
    source_app: str | None = None
    source_confidence: float | None = None
    source_evidence: str | None = None
    tags: list[tuple[str, float]] = field(default_factory=list)


def _settings_fingerprint() -> str:
    """Changes whenever a prompt, vocabulary entry, or threshold changes."""
    settings = [[(a.name, a.prompts, a.ui_text, a.aliases, a.mentions) for a in APPS], GENERIC_SCREENS,
                TAGS, TAG_BACKGROUNDS, LOGIT_SCALE, APP_MIN_CONFIDENCE, APP_MIN_MARGIN, INTERFACE_EVIDENCE,
                NAME_MENTION, UI_TEXT_ONE, UI_TEXT_MORE, TAG_MIN_SCORE, MAX_TAGS]
    return hashlib.sha1(json.dumps(settings).encode("utf-8")).hexdigest()[:8]


def label_model(embedder: Embedder | None) -> str:
    """Identity of the labelling setup; stored labels are recomputed when it changes."""
    model = embedder.name if embedder is not None else "text-only"
    return f"{LABELS_VERSION}-{_settings_fingerprint()}:{model}"


_CLASS_CACHE: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def _class_vectors(embedder: Embedder, cache_dir: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(app classes incl. generic screens, tag classes incl. backgrounds), one row per class.

    Embedding the ~200 prompts takes tens of seconds on a slow CPU, so the result is also saved
    in `cache_dir`, keyed by the model and the exact prompts.
    """
    app_prompts = [list(app.prompts) for app in APPS] + [[p] for p in GENERIC_SCREENS]
    tag_prompts = [[*descs, *(f"a screenshot showing {d}" for d in descs)] for descs in TAGS.values()]
    tag_prompts += [[p] for p in TAG_BACKGROUNDS]
    groups = app_prompts + tag_prompts
    key = hashlib.sha1(json.dumps([embedder.name, groups]).encode("utf-8")).hexdigest()[:16]
    if key in _CLASS_CACHE:
        return _CLASS_CACHE[key]
    cache_file = cache_dir / f"label_prompts_{key}.npz" if cache_dir is not None else None
    if cache_file is not None and cache_file.exists():
        try:
            with np.load(cache_file) as saved:
                apps, tags = saved["apps"], saved["tags"]
            if (len(apps), len(tags)) == (len(app_prompts), len(tag_prompts)):
                _CLASS_CACHE[key] = (apps, tags)
                return _CLASS_CACHE[key]
        except (OSError, ValueError, KeyError):
            pass  # unreadable cache: recompute
    vectors = embed_texts(embedder, [p for group in groups for p in group])  # batched
    means, start = [], 0
    for group in groups:
        means.append(normalize(vectors[start:start + len(group)].mean(axis=0)))
        start += len(group)
    _CLASS_CACHE[key] = (np.stack(means[:len(app_prompts)]), np.stack(means[len(app_prompts):]))
    if cache_file is not None:
        try:
            np.savez(cache_file, apps=_CLASS_CACHE[key][0], tags=_CLASS_CACHE[key][1])
        except OSError:
            pass  # the cache is only a speed-up
    return _CLASS_CACHE[key]


def _softmax(logits: np.ndarray) -> np.ndarray:
    exp = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return exp / exp.sum(axis=-1, keepdims=True)


def text_evidence(app: App, text: str) -> float:
    """How strongly recognized text points to `app` (0 when it doesn't)."""
    hits = sum(1 for pattern in app.ui_text if re.search(pattern, text, re.IGNORECASE | re.MULTILINE))
    if hits:
        return UI_TEXT_MORE if hits > 1 else UI_TEXT_ONE
    words = app.mentions or (app.name.lower(),)
    if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE) for w in words):
        return NAME_MENTION
    return 0.0


def compute_labels(text: str | None, embedder: Embedder | None = None, embedding: np.ndarray | None = None,
                   cache_dir: Path | None = None) -> Labels:
    """Labels for one screenshot from its recognized text and (optionally) its image embedding."""
    text = text or ""
    visual = np.zeros(len(APPS))
    tags: list[tuple[str, float]] = []
    if embedder is not None and embedding is not None:
        app_classes, tag_classes = _class_vectors(embedder, cache_dir)
        visual = _softmax(LOGIT_SCALE * (app_classes @ embedding))[:len(APPS)]
        probs = _softmax(LOGIT_SCALE * (tag_classes @ embedding))[:len(TAGS)]
        ranked = sorted(zip(TAGS, probs), key=lambda kv: -kv[1])
        tags = [(name, round(float(p), 3)) for name, p in ranked[:MAX_TAGS] if p >= TAG_MIN_SCORE]

    textual = np.array([text_evidence(app, text) for app in APPS]) if text else np.zeros(len(APPS))
    combined = 1 - (1 - visual) * (1 - textual)
    labels = Labels(tags=tags)
    order = np.argsort(-combined)
    best = int(order[0])
    runner_up = float(combined[order[1]]) if len(order) > 1 else 0.0
    if combined[best] >= APP_MIN_CONFIDENCE and combined[best] - runner_up >= APP_MIN_MARGIN:
        evidence = [kind for kind, value in (("interface", visual[best] >= INTERFACE_EVIDENCE),
                                             ("text", textual[best] > 0)) if value]
        labels.source_app = APPS[best].name
        labels.source_confidence = round(float(combined[best]), 3)
        labels.source_evidence = ", ".join(evidence)
    return labels


_APPS_BY_NAME = {app.name: app for app in APPS}


def searchable_labels(source_app: str | None, source_confidence: float | None,
                      tags: list[tuple[str, float]] | None) -> list[tuple[str, float]]:
    """(phrase, confidence) pairs that search can match: the app's name and aliases, and tags."""
    phrases: list[tuple[str, float]] = []
    if source_app:
        app = _APPS_BY_NAME.get(source_app)
        words = [source_app, *(app.aliases if app else ())]
        phrases += [(w, float(source_confidence or 0.0)) for w in words]
    phrases += [(label, float(score)) for label, score in tags or []]
    return phrases


def describe_confidence(confidence: float) -> str:
    return "very likely" if confidence >= 0.8 else "likely" if confidence >= 0.6 else "possibly"
