"""Detail view for a single screenshot: preview, copy/open actions, and similar screenshots."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

from copy_image import CopyImageError, clipboard_png, copy_button_html
from indexer import RenameError, remove_screenshots, rename_screenshot
from labels import describe_confidence
from search import similar
from storage import ImageRecord
from ui.components import empty_state, render_grid
from ui.context import AppContext
from ui.folders import open_original
from ui.formatting import fmt_time
from ui.styles import section_label

state = st.session_state


def show_detail(ctx: AppContext, rec: ImageRecord, visible: list[ImageRecord]) -> None:
    embedder = ctx.embedder
    if st.button("Back to results", icon=":material/arrow_back:", type="tertiary"):
        state.selected = None
        st.rerun()
    col_img, col_info = st.columns([3, 1.3], gap="medium")
    with col_img:
        with st.container(border=True, key="detail_image"):
            try:
                with Image.open(rec.path) as img:
                    img.load()
                    st.image(ImageOps.exif_transpose(img), width="stretch")
            except OSError:
                empty_state("image", "This image can't be opened",
                            "It may have been moved or deleted. Try re-indexing the folder.")
    with col_info, st.container(border=True, key="detail_panel"):
        st.markdown(f'<div class="sr-detail-title">{html.escape(rec.name)}</div>', unsafe_allow_html=True)
        try:
            components.html(copy_button_html(clipboard_png(rec.path)), height=72)
        except CopyImageError as exc:
            st.error(str(exc))
        if st.button("Open original", icon=":material/open_in_new:", width="stretch"):
            try:
                open_original(rec.path)
            except OSError as exc:
                st.error(f"Could not open the file: {exc}")
        col_rename, col_delete = st.columns(2, gap="small")
        with col_rename, st.popover("Rename", icon=":material/edit:", width="stretch"):
            stem, suffix = Path(rec.path).stem, Path(rec.path).suffix
            with st.form(f"rename:{rec.path}", border=False):
                new_stem = st.text_input(f"New name (keeps {suffix})", value=stem)
                submitted = st.form_submit_button("Rename file", type="primary")
            if submitted:
                try:
                    state.selected = rename_screenshot(rec.path, new_stem, ctx.storage, ctx.config)
                    st.rerun()
                except RenameError as exc:
                    st.error(str(exc))
            st.caption("Renames the file on your computer. The image itself isn't changed.")
        with col_delete, st.popover("Delete", icon=":material/delete:", width="stretch",
                                    help="Delete screenshot from SnapRecall"):
            st.markdown("**Delete this screenshot from SnapRecall?** It disappears from your library "
                        "and search. The image file stays on your computer, and re-indexing won't "
                        "bring it back.")
            if st.button("Delete screenshot", key="del_one", type="primary"):
                remove_screenshots([rec.path], ctx.storage, ctx.config)
                state.selected = None
                st.rerun()
        st.caption("Copy image puts the full-size picture on your clipboard. "
                   "Open original opens it in your default image viewer.")

        section_label("Details")
        rows = [("Folder", html.escape(str(Path(rec.path).parent)))]
        if rec.width:
            rows.append(("Size", f"{rec.width} × {rec.height} px · {rec.size / 1024:.0f} KB"))
        rows.append(("Modified", html.escape(fmt_time(rec.mtime_ns))))
        guess = '<span class="sr-guess">Guess</span>'  # generated automatically, never shown as fact
        if rec.source_app:
            rows.append((f"From{guess}", html.escape(
                f"{rec.source_app} ({describe_confidence(rec.source_confidence or 0)})")))
        if rec.tags:
            rows.append((f"Might show{guess}", html.escape(", ".join(label for label, _ in rec.tags))))
        st.markdown('<dl class="sr-meta">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>",
                    unsafe_allow_html=True)
        if rec.source_app or rec.tags:
            st.caption("“From” and “Might show” are guessed automatically from the picture and its text, "
                       "and may be wrong.")
        if rec.ocr_text:
            with st.expander("Text found in this screenshot", icon=":material/notes:"):
                st.text(rec.ocr_text)
                if rec.ocr_confidence is not None:
                    quality = ("clear" if rec.ocr_confidence >= 0.8 else
                               "mostly clear" if rec.ocr_confidence >= 0.5 else "hard to read; may contain mistakes")
                    st.caption(f"Recognition quality: {quality}.")

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
