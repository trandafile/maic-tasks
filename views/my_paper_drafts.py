"""views/my_paper_drafts.py — Personal paper drafts.

Lists deliverables of type "paper" where the current user is owner or
supervisor (admin sees all of them) and lets them edit a markdown working
copy stored in the ``deliverable_drafts`` table. The default content for a
new draft comes from ``MPC_Template.md`` in the project root.

The view internally toggles between a ``list`` mode and a ``detail`` mode
using ``st.session_state['_paper_draft_selected_id']``.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import re

import streamlit as st

from db import (
    get_user_paper_deliverables,
    get_paper_draft,
    save_paper_draft,
)
from utils.helpers import fmt_date
from utils.md_editor import markdown_editor
from utils.modals import deliverable_details_modal
from utils.doc_converters import md_to_pdf, md_to_docx


_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "MPC_Template.md"
_SELECTED_KEY = "_paper_draft_selected_id"


# ─── Helpers ──────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_template() -> str:
    """Load the MPC template, cached for the session."""
    try:
        return _TEMPLATE_PATH.read_text(encoding="utf-8")
    except Exception:
        return "# Paper Draft\n\nStart writing here...\n"


def _slugify(text: str) -> str:
    text = (text or "paper").strip().lower()
    text = re.sub(r"[^a-z0-9\-_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "paper"


def _fmt_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        # Supabase returns ISO with optional timezone; normalise.
        clean = value.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean)
        return dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        return value


def _user_role_for_paper(deliverable: dict, email: str | None) -> str:
    if not email:
        return "—"
    if deliverable.get("owner_email") == email and deliverable.get("supervisor_email") == email:
        return "Owner & Supervisor"
    if deliverable.get("owner_email") == email:
        return "Owner"
    if deliverable.get("supervisor_email") == email:
        return "Supervisor"
    return "—"


def _can_edit(deliverable: dict, email: str | None, is_admin: bool) -> bool:
    if is_admin:
        return True
    if not email:
        return False
    return (
        deliverable.get("owner_email") == email
        or deliverable.get("supervisor_email") == email
    )


# ─── List mode ────────────────────────────────────────────────────────────────

def _render_list(papers: list[dict], email: str | None) -> None:
    st.title("📝 My Paper Drafts")
    st.caption(
        "Paper deliverables where you are owner or supervisor. "
        "Click *Open* to edit the markdown draft."
    )

    if not papers:
        st.info(
            "No paper deliverables assigned to you. "
            "Ask an administrator to mark a deliverable as type *paper* "
            "with you as owner or supervisor."
        )
        return

    # Sort by deadline ascending (None last).
    def _key(d):
        return d.get("deadline") or "9999-12-31"
    papers = sorted(papers, key=_key)

    # Header
    h1, h2, h3, h4, h5, h6, h7 = st.columns([2, 3, 1.3, 1.4, 1.4, 1.6, 1.1])
    h1.markdown("**Project**")
    h2.markdown("**Paper**")
    h3.markdown("**Status**")
    h4.markdown("**Deadline**")
    h5.markdown("**Role**")
    h6.markdown("**Last edit**")
    h7.markdown("**Action**")
    st.divider()

    today = datetime.date.today().isoformat()

    for d in papers:
        proj = d.get("_project") or {}
        proj_label = proj.get("acronym") or proj.get("name") or "—"
        if proj.get("acronym") and proj.get("name"):
            proj_label = f"{proj['acronym']}"
        deadline = d.get("deadline")
        deadline_overdue = (
            deadline
            and d.get("status") not in ("Completed", "Cancelled")
            and deadline < today
        )

        c1, c2, c3, c4, c5, c6, c7 = st.columns([2, 3, 1.3, 1.4, 1.4, 1.6, 1.1])
        with c1:
            st.write(proj_label)
            if proj.get("name") and proj.get("acronym"):
                st.caption(proj["name"])
        with c2:
            st.write(d.get("name") or "(untitled)")
        with c3:
            st.write(d.get("status") or "Not started")
        with c4:
            if deadline_overdue:
                st.markdown(f"🔴 **{fmt_date(deadline)}**")
            else:
                st.write(fmt_date(deadline))
        with c5:
            st.write(_user_role_for_paper(d, email))
        with c6:
            st.write(_fmt_timestamp(d.get("draft_updated_at")))
        with c7:
            if st.button("Open ↗", key=f"open_paper_{d['id']}", use_container_width=True, type="primary"):
                st.session_state[_SELECTED_KEY] = d["id"]
                # Clear any per-draft editor state from a previous session
                st.session_state.pop(f"__mde_paper_draft_{d['id']}", None)
                st.session_state.pop(f"paper_draft_{d['id']}_ta", None)
                st.rerun()


# ─── Detail mode ──────────────────────────────────────────────────────────────

def _render_detail(deliverable: dict, email: str | None, is_admin: bool) -> None:
    d_id = deliverable["id"]
    proj = deliverable.get("_project") or {}
    proj_label = proj.get("acronym") or proj.get("name") or ""

    top_l, top_r = st.columns([1, 1])
    with top_l:
        if st.button("← Back to list", use_container_width=True):
            st.session_state.pop(_SELECTED_KEY, None)
            st.rerun()
    with top_r:
        if st.button("📋 Deliverable Details", use_container_width=True):
            # We cannot nest @st.dialog inside @st.dialog; the existing
            # deliverable_details_modal IS already a dialog, so just call it.
            deliverable_details_modal(deliverable, can_edit=is_admin)

    breadcrumb_bits = []
    if proj_label:
        breadcrumb_bits.append(f"📁 {proj_label}")
    breadcrumb_bits.append("📝 Paper Draft")
    st.caption("  ·  ".join(breadcrumb_bits))

    st.title(deliverable.get("name") or "(untitled)")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Status", deliverable.get("status") or "Not started")
    m2.metric("Deadline", fmt_date(deliverable.get("deadline")))
    m3.metric("Your role", _user_role_for_paper(deliverable, email))
    m4.metric("Last draft edit", _fmt_timestamp(deliverable.get("draft_updated_at")))

    st.divider()

    # ── Load draft (or template) ──────────────────────────────────────────────
    draft_row = get_paper_draft(d_id)
    if draft_row and (draft_row.get("content") or "").strip():
        initial_content = draft_row["content"]
        is_new_draft = False
        st.caption(
            f"Last saved: {_fmt_timestamp(draft_row.get('updated_at'))} "
            f"by {draft_row.get('updated_by_email') or 'unknown'}"
        )
    else:
        initial_content = _load_template()
        is_new_draft = True
        st.info(
            "🆕 No draft yet — pre-loaded with the MPC template. "
            "Edit it and click **💾 Save Draft** to persist your changes."
        )

    can_edit = _can_edit(deliverable, email, is_admin)

    # Markdown editor (or read-only render if user has no edit rights)
    editor_key = f"paper_draft_{d_id}"
    if can_edit:
        current_md = markdown_editor(
            value=initial_content,
            key=editor_key,
            height=520,
            label="📝 Paper draft (Markdown)",
        )
    else:
        st.caption("📝 Paper draft (read-only — you are not owner or supervisor of this paper)")
        st.markdown(initial_content)
        current_md = initial_content

    st.divider()

    # ── Action bar ────────────────────────────────────────────────────────────
    a1, a2, a3, a4 = st.columns(4)

    with a1:
        save_disabled = not can_edit
        if st.button(
            "💾 Save Draft",
            type="primary",
            use_container_width=True,
            disabled=save_disabled,
            key=f"save_paper_{d_id}",
        ):
            ok, err = save_paper_draft(d_id, current_md, email)
            if ok:
                st.success("Draft saved." + (" (created)" if is_new_draft else ""))
                st.rerun()
            else:
                st.error(f"Save failed: {err}")

    base_name = _slugify(f"{proj_label}_{deliverable.get('name', 'paper')}") or f"paper_{d_id}"
    title_for_export = deliverable.get("name") or "Paper Draft"

    with a2:
        st.download_button(
            "⬇ Download .md",
            data=current_md.encode("utf-8"),
            file_name=f"{base_name}.md",
            mime="text/markdown",
            use_container_width=True,
            key=f"dl_md_{d_id}",
        )

    with a3:
        try:
            pdf_buf = md_to_pdf(current_md, title=title_for_export)
            st.download_button(
                "⬇ Download .pdf",
                data=pdf_buf,
                file_name=f"{base_name}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key=f"dl_pdf_{d_id}",
            )
        except Exception as ex:
            st.button("⬇ Download .pdf", disabled=True, use_container_width=True, key=f"dl_pdf_dis_{d_id}")
            st.caption(f"PDF unavailable: {ex}")

    with a4:
        try:
            docx_buf = md_to_docx(current_md, title=title_for_export)
            st.download_button(
                "⬇ Download .docx",
                data=docx_buf,
                file_name=f"{base_name}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                key=f"dl_docx_{d_id}",
            )
        except Exception as ex:
            st.button("⬇ Download .docx", disabled=True, use_container_width=True, key=f"dl_docx_dis_{d_id}")
            st.caption(f"DOCX unavailable: {ex}")


# ─── Entry point ──────────────────────────────────────────────────────────────

def show_my_paper_drafts() -> None:
    email = st.session_state.get("user_email")
    is_admin = st.session_state.get("user_role") == "admin"

    if not email:
        st.error("You must be logged in to view this page.")
        return

    papers = get_user_paper_deliverables(email, is_admin)
    selected_id = st.session_state.get(_SELECTED_KEY)

    if selected_id is not None:
        selected = next((d for d in papers if d["id"] == selected_id), None)
        if selected is None:
            # The selection is stale (deliverable archived, deleted, or no longer
            # accessible to this user) — fall back to the list.
            st.session_state.pop(_SELECTED_KEY, None)
            _render_list(papers, email)
            return
        _render_detail(selected, email, is_admin)
    else:
        _render_list(papers, email)
