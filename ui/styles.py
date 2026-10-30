"""Global CSS and branding for the SnapRecall interface."""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

LOGO_PATH = str(Path(__file__).resolve().parent.parent / "assets" / "logo.svg")

_CSS = """<style>
    .block-container { max-width: 1180px; padding-top: 4.5rem; padding-bottom: 4rem; }

    .sr-brand { font-size: 1.9rem; font-weight: 750; letter-spacing: -0.03em; margin: 0; line-height: 1.2; }
    .sr-brand span { color: #a78bfa; }
    .sr-muted { color: #9aa1b5; font-size: 0.92rem; }
    .sr-status { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
                 color: #9aa1b5; font-size: 0.9rem; margin: 0.35rem 0 1.1rem; }
    .sr-chip { background: #262046; color: #c4b5fd; font-weight: 600; border-radius: 999px;
               padding: 0.15rem 0.7rem; max-width: 100%; overflow: hidden; text-overflow: ellipsis;
               white-space: nowrap; }
    .sr-dot { color: #4a5063; }

    /* Prominent search bar */
    .st-key-search [data-baseweb="input"] { border-radius: 14px; border: 1px solid #2a2f3d;
        box-shadow: 0 1px 2px rgba(0,0,0,.35), 0 4px 14px rgba(0,0,0,.35); }
    .st-key-search [data-baseweb="input"]:focus-within { border-color: #a78bfa;
        box-shadow: 0 0 0 4px rgba(167,139,250,.22); }
    .st-key-search [data-baseweb="base-input"], .st-key-search input { background: #1b1f2b; }
    .st-key-search input { font-size: 1.08rem; padding: 1rem 1.1rem; }

    /* Result grid: cards wrap onto new rows on narrow screens */
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-card_"]) { flex-wrap: wrap; gap: 1rem; }
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-card_"]) > div[data-testid="stColumn"] {
        flex: 1 1 210px; min-width: 210px; }
    [class*="st-key-card_"] { background: #1b1f2b; gap: 0.35rem;
        transition: box-shadow .15s ease, transform .15s ease; }
    [class*="st-key-card_"]:hover { box-shadow: 0 8px 24px rgba(0,0,0,.5); transform: translateY(-2px); }
    [class*="st-key-card_"] img { aspect-ratio: 16 / 10; object-fit: cover; object-position: top;
        border-radius: 8px; background: #232838; }
    /* Clicking the thumbnail opens the detail view (see _CARD_CLICK_JS); the tiny built-in
       image fullscreen control is hidden. */
    [class*="st-key-card_"] img, [class*="st-key-card_"] .sr-noimg { cursor: pointer; }
    [class*="st-key-card_"] [data-testid="stElementToolbar"] { display: none; }
    [class*="st-key-card_"] button { padding: 0; min-height: 0; max-width: 100%; }
    [class*="st-key-card_"] button p { font-weight: 600; overflow: hidden; text-overflow: ellipsis;
        white-space: nowrap; }
    .st-key-when [data-baseweb="select"] > div { min-height: 3.4rem; border-radius: 14px; background: #1b1f2b;
        border-color: #2a2f3d; box-shadow: 0 1px 2px rgba(0,0,0,.35), 0 4px 14px rgba(0,0,0,.35); }
    .sr-excerpt { color: #b4bacb; font-size: 0.8rem; line-height: 1.35; margin-top: 0.35rem; text-align: left;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
        overflow-wrap: anywhere; }
    .sr-excerpt mark { background: #6d5a12; color: #fff4c2; padding: 0 1px; border-radius: 3px; }
    .sr-section { font-size: 1.1rem; font-weight: 650; margin: 1.6rem 0 0.2rem; }
    .sr-card-date { color: #7d8499; font-size: 0.8rem; margin-top: -0.4rem; text-align: center; }
    .sr-noimg { aspect-ratio: 16 / 10; border-radius: 8px; background: #232838; color: #7d8499;
        display: flex; align-items: center; justify-content: center; font-size: 0.85rem; }

    /* Empty states */
    .sr-empty { text-align: center; padding: 3.5rem 1rem 1.5rem; color: #9aa1b5; }
    .sr-empty .icon { font-size: 2.6rem; line-height: 1; }
    .sr-empty h3 { color: #e8eaf2; margin: 0.8rem 0 0.3rem; font-weight: 650; }

    /* Detail view */
    .sr-detail-title { font-size: 1.3rem; font-weight: 700; overflow-wrap: anywhere; line-height: 1.3;
                       margin-top: 0.2rem; }
    .sr-meta { display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 1rem;
               font-size: 0.9rem; margin: 0.6rem 0 1.2rem; }
    .sr-meta dt { color: #7d8499; }
    .sr-meta dd { margin: 0; color: #e8eaf2; overflow-wrap: anywhere; }

    section[data-testid="stSidebar"] h4 { margin-bottom: 0.2rem; }
    </style>"""

# Streamlit can't make an image clickable, so one delegated listener on the page forwards a click
# on a card's thumbnail to that card's filename button.
_CARD_CLICK_JS = """<script>
const doc = window.parent.document;
if (!doc.__srCardClick) {
  doc.__srCardClick = true;
  doc.addEventListener("click", (e) => {
    const thumb = e.target.closest('[class*="st-key-card_"] img, [class*="st-key-card_"] .sr-noimg');
    if (!thumb) return;
    const button = thumb.closest('[class*="st-key-card_"]').querySelector("button");
    if (button) button.click();
  });
}
</script>"""


def apply_branding() -> None:
    st.logo(LOGO_PATH, icon_image=LOGO_PATH, size="large")
    st.markdown(_CSS, unsafe_allow_html=True)
    components.html(_CARD_CLICK_JS, height=0)
