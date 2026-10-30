"""Copy a screenshot to the clipboard of the device running the browser.

Python runs on the host, but the user's clipboard belongs to whatever device
the browser is on, so copying happens in the browser with the asynchronous
Clipboard API. Python prepares the original image as PNG (the one image
format every supporting browser accepts) and embeds it in a small button;
clicking the button writes it to the clipboard.

- The original file is only read, never changed.
- Full resolution is kept; transparency is kept for images that have it.
- Success is shown only after the browser confirms the write.
- Browsers allow this only on secure pages (https or localhost) and only
  in response to a click.
"""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Larger images make the page slow to load and may be rejected by browsers.
MAX_PNG_BYTES = 40 * 1024 * 1024


class CopyImageError(RuntimeError):
    """A copy can't be prepared; the message is safe to show to users."""


def clipboard_png(path: str | Path) -> bytes:
    """Read the original image and encode it as PNG at full resolution."""
    path = Path(path)
    try:
        with Image.open(path) as img:
            img.load()
            has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
            image = img.convert("RGBA" if has_alpha else "RGB")
    except FileNotFoundError:
        raise CopyImageError("The original file is missing. It may have been moved or deleted.") from None
    except PermissionError:
        raise CopyImageError("The original file can't be read (permission denied).") from None
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise CopyImageError("The original file can't be read as an image.") from None
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    data = buffer.getvalue()
    if len(data) > MAX_PNG_BYTES:
        raise CopyImageError("This image is too large to copy from the browser. Use Open original instead.")
    return data


MESSAGES = {
    "ok": "Copied. Paste it anywhere with {shortcut}.",
    "unsupported": "This browser can't copy images. Try a current version of Chrome, Edge, "
                   "Safari, or Firefox.",
    "insecure": "Copying images only works when SnapRecall is opened at localhost or over https.",
    "denied": "The browser blocked clipboard access. Allow clipboard access for this page and try again.",
    "failed": "Couldn't copy the image ({error}). Try again, or use Open original.",
}

_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin: 0; font-family: "Source Sans 3", "Source Sans Pro", system-ui, -apple-system, "Segoe UI", sans-serif; }
  button { width: 100%; height: 40px; border-radius: 0.6rem; border: 1px solid #4f46e5; cursor: pointer;
           background: #4f46e5; color: #fff; font: inherit; font-size: 1rem; font-weight: 500;
           transition: background .15s; }
  button:hover { background: #4338ca; }
  button:focus-visible { outline: 3px solid rgba(79,70,229,.3); outline-offset: 1px; }
  button:disabled { opacity: .6; cursor: progress; }
  #msg { font-size: 0.85rem; margin-top: 6px; min-height: 1.1em; line-height: 1.3; }
  .ok { color: #15803d; } .error { color: #b42318; }
</style></head><body>
<button id="copy" type="button">📋&nbsp; __LABEL__</button>
<div id="msg" role="status" aria-live="polite"></div>
<script>
const DATA = "__DATA__";
const MESSAGES = __MESSAGES__;
const button = document.getElementById("copy");
const msg = document.getElementById("msg");
const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
function show(kind, key, error) {
  msg.className = kind === "ok" ? "ok" : "error";
  msg.textContent = MESSAGES[key].replace("{shortcut}", isMac ? "\\u2318V" : "Ctrl+V")
                                  .replace("{error}", error || "");
  document.body.dataset.result = key;
}
function pngBlob() {
  const bytes = atob(DATA);
  const array = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) array[i] = bytes.charCodeAt(i);
  return new Blob([array], { type: "image/png" });
}
button.addEventListener("click", async () => {
  if (!window.isSecureContext) return show("error", "insecure");
  if (!navigator.clipboard || !navigator.clipboard.write || typeof ClipboardItem === "undefined")
    return show("error", "unsupported");
  button.disabled = true;
  msg.textContent = "";
  try {
    // Build the item synchronously so the click still counts as the user's gesture.
    await navigator.clipboard.write([new ClipboardItem({ "image/png": pngBlob() })]);
    show("ok", "ok");
  } catch (err) {
    if (err && err.name === "NotAllowedError") show("error", "denied");
    else show("error", "failed", (err && err.name) || "unknown error");
  } finally {
    button.disabled = false;
  }
});
</script></body></html>"""


def copy_button_html(png: bytes, label: str = "Copy image") -> str:
    """A self-contained page with a button that copies `png` to the clipboard."""
    return (
        _TEMPLATE.replace("__LABEL__", html.escape(label))
        .replace("__MESSAGES__", json.dumps(MESSAGES))
        .replace("__DATA__", base64.b64encode(png).decode("ascii"))
    )
