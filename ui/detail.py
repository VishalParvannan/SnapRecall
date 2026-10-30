"""Detail view for a single screenshot: preview, copy/open actions, and similar screenshots."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

from copy_image import CopyImageError, clipboard_png, copy_button_html
from search import similar
from storage import ImageRecord
from ui.components import empty_state, render_grid
from ui.context import AppContext
from ui.folders import open_original
from ui.formatting import fmt_time

state = st.session_state


def show_detail(ctx: AppContext, rec: ImageRecord, visible: list[ImageRecord]) -> None:
    embedder = ctx.embedder
    if st.button("← Back to results", type="tertiary"):
        state.selected = None
        st.rerun()
    col_img, col_info = st.columns([3, 1.3], gap="large")
    with col_img:
        with st.container(border=True):
            try:
                with Image.open(rec.path) as img:
                    img.load()
                    st.image(img.copy(), width="stretch")
            except OSError:
                empty_state("🖼️", "This image can't be opened",
                            "It may have been moved or deleted. Try re-indexing the folder.")
    with col_info:
        st.markdown(f'<div class="sr-detail-title">{html.escape(rec.name)}</div>', unsafe_allow_html=True)
        rows = [("Folder", str(Path(rec.path).parent))]
        if rec.width:
            rows.append(("Size", f"{rec.width} × {rec.height} px · {rec.size / 1024:.0f} KB"))
        rows.append(("Modified", fmt_time(rec.mtime_ns)))
        st.markdown(
            '<dl class="sr-meta">'
            + "".join(f"<dt>{k}</dt><dd>{html.escape(v)}</dd>" for k, v in rows)
            + "</dl>",
            unsafe_allow_html=True,
        )
        try:
            components.html(copy_button_html(clipboard_png(rec.path)), height=72)
        except CopyImageError as exc:
            st.error(str(exc))
        if st.button("Open original", width="stretch"):
            try:
                open_original(rec.path)
            except OSError as exc:
                st.error(f"Could not open the file: {exc}")
        st.caption("Copy image puts the full-size picture on your clipboard. "
                   "Open original opens it in your default image viewer.")
        if rec.ocr_text:
            with st.expander("Text found in this screenshot"):
                st.text(rec.ocr_text)

    st.markdown('<div class="sr-section">Similar screenshots</div>', unsafe_allow_html=True)
    if embedder is None:
        st.caption("Finding similar screenshots needs visual search, which isn't available right now.")
        return
    matches = similar(rec, visible, embedder.name)
    if matches:
        render_grid([m.record for m in matches], prefix="sim")
    elif rec.embed_model != embedder.name:
        st.caption("This screenshot hasn't been analysed yet. Re-index the folder to find similar ones.")
    else:
        scope = "this folder" if ctx.info else "your folders"
        st.caption(f"Nothing in {scope} looks much like this screenshot.")
