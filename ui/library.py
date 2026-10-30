"""Library header: folder status, indexing/backup results, and problem files."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from storage import ImageRecord
from ui.context import AppContext
from ui.formatting import fmt_scan_time, folder_label

state = st.session_state


def render_library_status(ctx: AppContext) -> list[ImageRecord]:
    """Render the status area and return the screenshots that can be shown (no hard errors)."""
    info = ctx.info
    records = ctx.storage.folder_images(info.path) if info else ctx.storage.all_images()
    visible = [r for r in records if r.status != "error"]
    errors = [r for r in records if r.status != "ok"]

    status = [f'<span class="sr-chip" title="{html.escape(info.path if info else "All folders")}">📁 '
              f"{html.escape(folder_label(state.folder))}</span>",
              f"{len(visible)} screenshots"]
    if info and info.last_scan_at:
        status.append(f"indexed {html.escape(fmt_scan_time(info.last_scan_at))}")
    if ctx.signed_in and info and info.backup:
        status.append("☁ backup on")
    st.markdown('<div class="sr-status">' + '<span class="sr-dot">•</span>'.join(status) + "</div>",
                unsafe_allow_html=True)

    shown_reports = [r for r in (state.report or []) if not info or r.folder == info.path]
    if shown_reports:
        totals = {
            "new": sum(len(r.plan.new) for r in shown_reports),
            "changed": sum(len(r.plan.changed) for r in shown_reports),
            "retried": sum(len(r.plan.retry) for r in shown_reports),
            "removed": sum(r.removed for r in shown_reports),
        }
        parts = [f"{n} {label}" for label, n in totals.items() if n]
        st.success("Indexing complete — " + (", ".join(parts) if parts else "everything was up to date") + ".",
                   icon="✅")
        scan_errors = [e for r in shown_reports for e in r.plan.errors]
        if scan_errors:
            st.warning(
                f"{len(scan_errors)} locations couldn't be read, so missing files weren't removed. "
                + "; ".join(f"{loc}: {msg}" for loc, msg in scan_errors[:3]), icon="⚠️"
            )
    elif info and info.last_scan_complete is False:
        st.warning("The last scan couldn't read everything in this folder. Try re-indexing.", icon="⚠️")

    for kind, sync_rep in state.sync_report or []:
        if kind == "backup":
            st.success(f"Backup of {folder_label(sync_rep.folder)} complete — {sync_rep.uploaded} uploaded, "
                       f"{sync_rep.already} already backed up.", icon="☁️")
        else:
            st.success(f"Downloaded {sync_rep.downloaded} screenshots to {sync_rep.folder} "
                       f"({sync_rep.already} were already there).", icon="⬇️")
        if sync_rep.failed:
            with st.expander(f"{len(sync_rep.failed)} screenshots couldn't be synced"):
                for path, msg in sync_rep.failed:
                    st.markdown(f"**{html.escape(Path(path).name)}** — {html.escape(msg)}")

    if errors:
        with st.expander(f"{len(errors)} files had problems"):
            for r in errors:
                st.markdown(f"**{html.escape(r.name)}** — {html.escape(r.error or '')}")
    return visible
