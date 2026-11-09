"""Global CSS, branding, and small markup helpers for the SnapRecall interface.

Colors are defined once as CSS variables (see :root below) and match .streamlit/config.toml.
"""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = str(ASSETS / "logo.svg")
MARK_PATH = str(ASSETS / "mark.svg")

# Line icons (24×24, stroke = currentColor) for empty states and feature lists.
_ICON_PATHS = {
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "inbox": '<path d="M3 13h5l1.5 2.5h5L16 13h5"/><path d="M5 5h14l2 8v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5z"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/>'
             '<path d="m21 16-5-5-8 9"/>',
    "text": '<path d="M5 6h14M5 11h14M5 16h9"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
}


def icon_svg(name: str, size: int = 24) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f"{_ICON_PATHS[name]}</svg>")


def section_label(text: str) -> None:
    """Small uppercase heading used to group controls (sidebar sections, detail panels)."""
    st.markdown(f'<div class="sr-label">{html.escape(text)}</div>', unsafe_allow_html=True)


_SEARCH_ICON = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' "
                "viewBox='0 0 24 24' fill='none' stroke='%238b91a5' stroke-width='2' stroke-linecap='round'%3E"
                "%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='m20 20-3.5-3.5'/%3E%3C/svg%3E\")")

_CSS = """<style>
    :root {
        --sr-bg: #0b0d12;
        --sr-surface: #12151c;
        --sr-card: #161a23;
        --sr-raised: #1c2130;
        --sr-border: #262b38;
        --sr-border-strong: #353b4c;
        --sr-text: #eceef4;
        --sr-muted: #9aa0b2;
        --sr-subtle: #6b7286;
        --sr-accent: #8b5cf6;
        --sr-accent-hover: #7c4ff0;
        --sr-accent-soft: rgba(139, 92, 246, .14);
        --sr-accent-text: #c4b5fd;
        --sr-ring: 0 0 0 3px rgba(139, 92, 246, .28);
        --sr-shadow: 0 1px 2px rgba(0, 0, 0, .3), 0 8px 24px rgba(0, 0, 0, .28);
    }

    /* ---- page frame ------------------------------------------------------ */
    .stApp { background: radial-gradient(1200px 500px at 70% -10%, rgba(139, 92, 246, .07), transparent 60%),
                         var(--sr-bg); }
    header[data-testid="stHeader"] { background: transparent; }
    .block-container { max-width: 1240px; padding-top: 3.2rem; padding-bottom: 4rem; }
    h1, h2, h3 { letter-spacing: -0.02em; }
    ::selection { background: rgba(139, 92, 246, .35); }

    .sr-brand { font-size: 1.9rem; font-weight: 750; letter-spacing: -0.03em; margin: 0; line-height: 1.2; }
    .sr-brand span { color: var(--sr-accent-text); }
    .sr-muted { color: var(--sr-muted); font-size: 0.9rem; margin: 0; }
    .sr-label { color: var(--sr-subtle); font-size: 0.72rem; font-weight: 650; letter-spacing: .08em;
                text-transform: uppercase; margin: 0.4rem 0 0.1rem; }

    /* ---- buttons ----------------------------------------------------------- */
    button[data-testid^="stBaseButton"] { font-weight: 550; transition: background .15s, border-color .15s,
        box-shadow .15s, color .15s; }
    button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
        border: 1px solid rgba(255, 255, 255, .08);
        box-shadow: 0 1px 2px rgba(0, 0, 0, .35), inset 0 1px 0 rgba(255, 255, 255, .12); }
    button[data-testid="stBaseButton-primary"]:hover,
    button[data-testid="stBaseButton-primaryFormSubmit"]:hover { background: var(--sr-accent-hover); }
    button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"] {
        background: var(--sr-raised); border-color: var(--sr-border); }
    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
        border-color: var(--sr-border-strong); background: #222838; color: var(--sr-text); }
    button[data-testid^="stBaseButton"]:focus-visible { box-shadow: var(--sr-ring); outline: none; }
    [data-testid="stPopover"] button { background: var(--sr-raised); border-color: var(--sr-border); }

    /* ---- inputs, selects, expanders, alerts -------------------------------- */
    [data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
        border-color: var(--sr-border) !important; background: var(--sr-card); }
    [data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {
        border-color: var(--sr-accent) !important; box-shadow: var(--sr-ring); }
    [data-testid="stExpander"] details { border-color: var(--sr-border); border-radius: 0.6rem;
        background: rgba(255, 255, 255, .015); }
    [data-testid="stExpander"] summary { font-weight: 550; }
    [data-testid="stExpander"] summary:hover { color: var(--sr-text); }
    [data-testid="stAlert"] > div { border-radius: 0.6rem; border: 1px solid rgba(255, 255, 255, .06); }
    [data-testid="stCaptionContainer"] { color: var(--sr-subtle); }
    hr { border-color: var(--sr-border) !important; margin: 1rem 0 !important; }
    [data-testid="stCode"] pre { background: var(--sr-bg); border: 1px solid var(--sr-border); }

    /* ---- sidebar ------------------------------------------------------------ */
    section[data-testid="stSidebar"] { border-right-color: var(--sr-border); }
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }
    section[data-testid="stSidebar"] .stButton button { justify-content: flex-start; }
    section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] {
        justify-content: center; }
    .sr-user { display: flex; align-items: center; gap: 0.7rem; padding: 0.65rem 0.75rem;
               background: var(--sr-card); border: 1px solid var(--sr-border); border-radius: 0.7rem; }
    .sr-avatar { flex: none; width: 2.1rem; height: 2.1rem; border-radius: 50%; display: grid;
                 place-items: center; font-weight: 700; color: #fff;
                 background: linear-gradient(135deg, #a78bfa, #6d28d9); }
    .sr-avatar.guest { background: var(--sr-raised); color: var(--sr-muted); border: 1px dashed var(--sr-border-strong); }
    .sr-user-name { font-weight: 600; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sr-user-kind { color: var(--sr-subtle); font-size: 0.78rem; }
    .sr-badge { display: inline-block; font-size: 0.68rem; font-weight: 650; letter-spacing: .04em;
                text-transform: uppercase; padding: 0.05rem 0.45rem; border-radius: 999px;
                background: rgba(251, 191, 36, .14); color: #fcd34d; margin-left: 0.3rem; vertical-align: 1px; }
    .sr-path { color: var(--sr-subtle); font-size: 0.76rem; overflow-wrap: anywhere; margin-top: -0.3rem; }

    /* ---- library header ----------------------------------------------------- */
    .sr-status { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
                 color: var(--sr-muted); font-size: 0.88rem; margin: 0 0 1.1rem; }
    .sr-chip { display: inline-flex; align-items: center; gap: 0.35rem; background: var(--sr-accent-soft);
               color: var(--sr-accent-text); font-weight: 600; border: 1px solid rgba(139, 92, 246, .28);
               border-radius: 999px; padding: 0.15rem 0.7rem; max-width: 100%; overflow: hidden;
               text-overflow: ellipsis; white-space: nowrap; }
    .sr-chip svg { flex: none; }
    .sr-dot { color: var(--sr-border-strong); }
    .sr-page-title { font-size: 1.55rem; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 0.35rem; }

    /* ---- search bar --------------------------------------------------------- */
    .st-key-search [data-baseweb="input"] { border-radius: 12px; box-shadow: var(--sr-shadow); }
    .st-key-search [data-baseweb="input"]:focus-within { box-shadow: var(--sr-ring), var(--sr-shadow); }
    .st-key-search [data-baseweb="base-input"], .st-key-search input { background-color: var(--sr-card); }
    .st-key-search input { font-size: 1.05rem; padding: 0.95rem 1rem 0.95rem 2.9rem;
        background-image: __SEARCH_ICON__; background-repeat: no-repeat; background-position: 1rem center; }
    .st-key-search input::placeholder { color: var(--sr-subtle); }
    .st-key-when [data-baseweb="select"] > div, .st-key-sort [data-baseweb="select"] > div {
        min-height: 3.3rem; border-radius: 12px; box-shadow: var(--sr-shadow); }
    .sr-count { color: var(--sr-muted); font-size: 0.86rem; margin: 0.2rem 0 0.6rem; }
    .sr-count b { color: var(--sr-text); font-weight: 600; }

    /* ---- result grid -------------------------------------------------------- */
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-card_"]) { flex-wrap: wrap; gap: 1rem; }
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-card_"]) > div[data-testid="stColumn"] {
        flex: 1 1 210px; min-width: 210px; }
    [class*="st-key-card_"] { background: var(--sr-card); gap: 0.3rem; padding: 0.55rem 0.55rem 0.7rem;
        border-color: var(--sr-border); border-radius: 0.8rem;
        transition: box-shadow .18s ease, transform .18s ease, border-color .18s ease; }
    [class*="st-key-card_"]:hover { border-color: rgba(139, 92, 246, .55); transform: translateY(-2px);
        box-shadow: 0 10px 28px rgba(0, 0, 0, .45), 0 0 0 1px rgba(139, 92, 246, .25); }
    [class*="st-key-card_"] img { aspect-ratio: 16 / 10; object-fit: cover; object-position: top;
        border-radius: 0.5rem; background: var(--sr-raised); }
    [class*="st-key-card_"] button { padding: 0 0.15rem; min-height: 0; max-width: 100%; justify-content: flex-start; }
    /* Clicking anywhere on a card (thumbnail included) presses its filename button: the button's
       invisible ::after is stretched over the card. Pure CSS, so nothing extra reruns. */
    [class*="st-key-card_"] { position: relative; cursor: pointer; }
    [class*="st-key-card_"] div:has(button), [class*="st-key-card_"] button { position: static; }
    [class*="st-key-card_"] button::after { content: ""; position: absolute; inset: 0; z-index: 1; }
    [class*="st-key-card_"] button:focus-visible::after { border-radius: 0.8rem; box-shadow: var(--sr-ring); }
    [class*="st-key-card_"] [data-testid="stElementToolbar"] { display: none; }
    [class*="st-key-card_"] button p { font-weight: 600; font-size: 0.9rem; color: var(--sr-text);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
    [class*="st-key-card_"]:hover button p { color: #fff; }
    /* Streamlit pulls markdown blocks up with a negative bottom margin, which let the date and
       excerpt spill past the card's border. */
    [class*="st-key-card_"] [data-testid="stMarkdown"], [class*="st-key-card_"] [data-testid="stMarkdownContainer"] {
        margin-bottom: 0 !important; }
    [class*="st-key-card_"] button > div { width: 100%; justify-content: flex-start; }
    .sr-card-date { color: var(--sr-subtle); font-size: 0.78rem; margin-top: -0.2rem; padding: 0 0.15rem; }
    .sr-excerpt { color: #b4bacb; font-size: 0.79rem; line-height: 1.4; margin-top: 0.4rem; padding: 0.4rem 0.5rem;
        background: rgba(255, 255, 255, .025); border-left: 2px solid var(--sr-border-strong); border-radius: 0 4px 4px 0;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
        overflow-wrap: anywhere; }
    .sr-excerpt mark { background: rgba(250, 204, 21, .22); color: #fde68a; padding: 0 2px; border-radius: 3px; }
    .sr-noimg { aspect-ratio: 16 / 10; border-radius: 0.5rem; background: var(--sr-raised); color: var(--sr-subtle);
        display: flex; align-items: center; justify-content: center; font-size: 0.82rem; }
    .sr-section { font-size: 1.05rem; font-weight: 650; margin: 2rem 0 0.5rem; padding-top: 1.4rem;
        border-top: 1px solid var(--sr-border); }

    /* ---- empty states ------------------------------------------------------- */
    .sr-empty { text-align: center; padding: 4rem 1rem 1.5rem; color: var(--sr-muted); max-width: 30rem; margin: 0 auto; }
    .sr-empty .icon { display: inline-grid; place-items: center; width: 3.6rem; height: 3.6rem; border-radius: 1rem;
        color: var(--sr-accent-text); background: var(--sr-accent-soft); border: 1px solid rgba(139, 92, 246, .25); }
    .sr-empty h3 { color: var(--sr-text); margin: 1rem 0 0.35rem; font-weight: 650; font-size: 1.25rem; }
    .sr-empty div:last-child { line-height: 1.5; }

    /* ---- detail view -------------------------------------------------------- */
    .st-key-detail_image { background: repeating-conic-gradient(#151922 0% 25%, #11141b 0% 50%) 50% / 20px 20px;
        border-color: var(--sr-border); border-radius: 0.8rem; }
    .st-key-detail_panel { background: var(--sr-card); border-color: var(--sr-border); border-radius: 0.8rem; }
    .sr-detail-title { font-size: 1.2rem; font-weight: 700; overflow-wrap: anywhere; line-height: 1.3;
                       letter-spacing: -0.01em; }
    .sr-meta { display: grid; grid-template-columns: auto 1fr; gap: 0.45rem 1rem;
               font-size: 0.86rem; margin: 0.2rem 0 0.4rem; }
    .sr-meta dt { color: var(--sr-subtle); }
    .sr-meta dd { margin: 0; color: var(--sr-text); overflow-wrap: anywhere; }
    .sr-guess { display: inline-block; font-size: 0.66rem; font-weight: 650; letter-spacing: .05em;
                text-transform: uppercase; padding: 0 0.4rem; border-radius: 999px; margin-left: 0.35rem;
                color: var(--sr-muted); border: 1px solid var(--sr-border-strong); vertical-align: 1px; }

    /* ---- sign-in screen ----------------------------------------------------- */
    .sr-hero { padding: 3.5rem 0 1rem; }
    .sr-hero h1 { font-size: 2.6rem; line-height: 1.12; font-weight: 750; letter-spacing: -0.035em;
                  margin: 1.4rem 0 0.9rem; padding: 0; }
    .sr-hero h1 .sr-grad { background: linear-gradient(90deg, #c4b5fd, #8b5cf6); -webkit-background-clip: text;
                       background-clip: text; color: transparent; }
    .sr-hero p { color: var(--sr-muted); font-size: 1.05rem; line-height: 1.55; max-width: 30rem; }
    .sr-features { list-style: none; padding: 0; margin: 1.8rem 0 0; display: grid; gap: 1rem; }
    .sr-features li { display: flex; gap: 0.85rem; align-items: flex-start; margin: 0; }
    .sr-features .ic { flex: none; display: grid; place-items: center; width: 2.2rem; height: 2.2rem;
        border-radius: 0.6rem; color: var(--sr-accent-text); background: var(--sr-accent-soft); }
    .sr-features b { display: block; color: var(--sr-text); font-weight: 600; font-size: 0.95rem; }
    .sr-features span { color: var(--sr-muted); font-size: 0.86rem; line-height: 1.45; }
    .st-key-login_card { background: var(--sr-surface); border-color: var(--sr-border); border-radius: 1rem;
        padding: 1.8rem 1.8rem 1.4rem; box-shadow: 0 24px 60px rgba(0, 0, 0, .45); margin-top: 2.5rem; }
    .sr-card-title { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.02em; margin: 0; }
    .sr-card-sub { margin-bottom: 0.6rem; }
    /* Sign in / Create account as a segmented control instead of underlined tabs. */
    .st-key-login_card [role="tablist"] { gap: 4px; padding: 4px; border-radius: 0.6rem; width: 100%;
        background: var(--sr-bg); border: 1px solid var(--sr-border); }
    .st-key-login_card [role="tab"] { flex: 1; justify-content: center; height: 2.2rem; padding: 0 0.75rem;
        border-radius: 0.45rem; margin: 0; color: var(--sr-muted); }
    .st-key-login_card [role="tab"][aria-selected="true"] { background: var(--sr-raised); color: var(--sr-text);
        box-shadow: 0 1px 2px rgba(0, 0, 0, .4); }
    .st-key-login_card [role="tab"] p { font-weight: 600; }
    .st-key-login_card [role="tab"] .react-aria-SelectionIndicator { display: none; }
    .st-key-login_card [role="tablist"] { border-bottom: 1px solid var(--sr-border); }
    .sr-or { display: flex; align-items: center; gap: 0.75rem; color: var(--sr-subtle); font-size: 0.78rem;
             text-transform: uppercase; letter-spacing: .08em; margin: 0.3rem 0; }
    .sr-or::before, .sr-or::after { content: ""; flex: 1; height: 1px; background: var(--sr-border); }

    @media (max-width: 800px) {
        .block-container { padding-top: 2.5rem; }
        .sr-hero { padding-top: 0.5rem; }
        .sr-hero h1 { font-size: 2rem; }
        .sr-features { display: none; }  /* keep the sign-in form above the fold on phones */
        .st-key-login_card { margin-top: 0.5rem; padding: 1.3rem; }
    }
    @media (prefers-reduced-motion: reduce) {
        [class*="st-key-card_"], [class*="st-key-card_"]:hover { transition: none; transform: none; }
    }
    </style>""".replace("__SEARCH_ICON__", _SEARCH_ICON)


def apply_branding() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def show_logo() -> None:
    """The logo in the sidebar header. Not on the sign-in screen, which has its own."""
    st.logo(LOGO_PATH, icon_image=MARK_PATH, size="large")
