"""Reusable widgets: empty states and the screenshot grid."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from search import excerpt
from storage import ImageRecord
from ui.formatting import fmt_time

state = st.session_state

COLS = 4


def empty_state(icon: str, title: str, text: str) -> None:
    st.markdown(
        f'<div class="sr-empty"><div class="icon">{icon}</div><h3>{html.escape(title)}</h3>'
        f"<div>{html.escape(text)}</div></div>",
        unsafe_allow_html=True,
    )


def excerpt_html(text: str | None, terms: list[str]) -> str:
    segments = excerpt(text or "", terms) if terms else None
    if not segments:
        return ""
    body = "".join(f"<mark>{html.escape(t)}</mark>" if hit else html.escape(t) for t, hit in segments)
    return f'<div class="sr-excerpt">{body}</div>'


def render_grid(items: list[ImageRecord], prefix: str = "", terms: list[str] | None = None) -> None:
    for start in range(0, len(items), COLS):
        cols = st.columns(COLS)
        for offset, (col, rec) in enumerate(zip(cols, items[start:start + COLS])):
            with col, st.container(border=True, key=f"{prefix}card_{start + offset}"):
                if rec.thumbnail and Path(rec.thumbnail).exists():
                    st.image(rec.thumbnail, width="stretch")
                else:
                    st.markdown('<div class="sr-noimg">Preview unavailable</div>', unsafe_allow_html=True)
                if st.button(rec.name, key=f"{prefix}open:{rec.path}", type="tertiary", width="stretch",
                             help="View larger"):
                    state.selected = rec.path
                    st.rerun()
                # Date and excerpt share one block so Streamlit's element spacing can't overlap them.
                st.markdown(f'<div class="sr-card-date">{fmt_time(rec.mtime_ns)}</div>'
                            + excerpt_html(rec.ocr_text, terms or []), unsafe_allow_html=True)
