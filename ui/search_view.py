"""Search bar, date filter, and result grid."""
from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

from search import BEST_MATCH, SORT_OPTIONS, filter_by_date, query_terms, search, sort_records
from storage import ImageRecord
from ui.components import empty_state, render_grid
from ui.context import AppContext

DATE_RANGES = ["Any time", "Today", "Past 7 days", "Past 30 days", "This year", "Custom range…"]


def render_search(ctx: AppContext, visible: list[ImageRecord]) -> None:
    col_query, col_when, col_sort = st.columns([4, 1.2, 1.4], vertical_alignment="center")
    with col_query:
        query = st.text_input("Search", placeholder="Describe what you remember — words, colors, apps…",
                              label_visibility="collapsed", key="search")
    with col_when:
        when = st.selectbox("When", DATE_RANGES, label_visibility="collapsed", key="when",
                            help="Filter by the date each screenshot file was last modified.")
    with col_sort:
        # "Best match" only applies to a search; when browsing it falls back to newest first.
        order = st.selectbox("Sort by", SORT_OPTIONS, label_visibility="collapsed", key="sort",
                             help="Order results like a file explorer. Best match ranks by relevance "
                                  "when searching.")

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
        empty_state("inbox", "No screenshots here yet",
                    "Add PNG or JPEG files to this folder, then re-index it from the sidebar.")
        st.stop()

    pool = filter_by_date(visible, start_day, end_day)
    if not pool:
        empty_state("calendar", "No screenshots from this time",
                    "Choose a wider date range, or Any time to see everything.")
        st.stop()

    range_note = "" if when == "Any time" else f" · {when.rstrip('…').lower()}"
    if query.strip():
        response = search(query, pool, ctx.embedder, visual_threshold=ctx.config.visual_threshold)
        if response.notice:
            st.warning(response.notice, icon=":material/warning:")
        if not response.results:
            empty_state("search", "No matching screenshots", "Try different or fewer words, or a wider date range.")
            st.stop()
        shown = sort_records([r.record for r in response.results], order)
        if response.weak:
            st.info("No strong matches. These are the closest screenshots, but they may not be what "
                    "you're looking for.", icon=":material/lightbulb:")
        st.markdown(f'<p class="sr-count"><b>{len(shown)}</b> result{"s" if len(shown) != 1 else ""} '
                    f"for “{html.escape(query.strip())}”{html.escape(range_note)}</p>", unsafe_allow_html=True)
        render_grid(shown, terms=query_terms(query))
    else:
        browse_order = "Date modified (newest)" if order == BEST_MATCH else order
        label = "Newest screenshots" if browse_order == "Date modified (newest)" else f"Sorted by {browse_order}"
        st.markdown(f'<p class="sr-count">{html.escape(label + range_note)}</p>', unsafe_allow_html=True)
        render_grid(sort_records(pool, browse_order)[:60])
