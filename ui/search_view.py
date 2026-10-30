"""Search bar, date filter, and result grid."""
from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

from search import filter_by_date, query_terms, search
from storage import ImageRecord
from ui.components import empty_state, render_grid
from ui.context import AppContext

DATE_RANGES = ["Any time", "Today", "Past 7 days", "Past 30 days", "This year", "Custom range…"]


def render_search(ctx: AppContext, visible: list[ImageRecord]) -> None:
    col_query, col_when = st.columns([4, 1.2], vertical_alignment="center")
    with col_query:
        query = st.text_input("Search", placeholder="🔎  Describe what you remember…",
                              label_visibility="collapsed", key="search")
    with col_when:
        when = st.selectbox("When", DATE_RANGES, label_visibility="collapsed", key="when",
                            help="Filter by the date each screenshot file was last modified.")

    today = date.today()
    start_day = end_day = None
    if when == "Today":
        start_day = today
    elif when == "Past 7 days":
        start_day = today - timedelta(days=6)
    elif when == "Past 30 days":
        start_day = today - timedelta(days=29)
    elif when == "This year":
        start_day = date(today.year, 1, 1)
    elif when == "Custom range…":
        picked = st.date_input("Between", value=(today - timedelta(days=30), today), max_value=today,
                               format="MM/DD/YYYY", key="date_range")
        if isinstance(picked, (tuple, list)):
            start_day = picked[0] if len(picked) > 0 else None
            end_day = picked[1] if len(picked) > 1 else None
        else:
            start_day = end_day = picked

    if not visible:
        empty_state("📭", "No screenshots here yet",
                    "Add PNG or JPEG files to this folder, then re-index it from the sidebar.")
        st.stop()

    pool = filter_by_date(visible, start_day, end_day)
    if not pool:
        empty_state("📅", "No screenshots from this time",
                    "Choose a wider date range, or Any time to see everything.")
        st.stop()

    range_note = "" if when == "Any time" else f" · {when.rstrip('…').lower()}"
    if query.strip():
        response = search(query, pool, ctx.embedder, visual_threshold=ctx.config.visual_threshold)
        if response.notice:
            st.warning(response.notice, icon="⚠️")
        if not response.results:
            empty_state("🤔", "No matching screenshots", "Try different or fewer words, or a wider date range.")
            st.stop()
        shown = [r.record for r in response.results]
        count = f"{len(shown)} result{'s' if len(shown) != 1 else ''}{range_note}"
        if response.weak:
            st.info("No strong matches. These are the closest screenshots, but they may not be what "
                    "you're looking for.", icon="💡")
        st.markdown(f'<p class="sr-muted">{html.escape(count)}</p>', unsafe_allow_html=True)
        render_grid(shown, terms=query_terms(query))
    else:
        st.markdown(f'<p class="sr-muted">Newest screenshots{html.escape(range_note)}</p>',
                    unsafe_allow_html=True)
        render_grid(pool[:60])
