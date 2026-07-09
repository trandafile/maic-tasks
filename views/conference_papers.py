"""views/conference_papers.py — Conference paper drafts.

A paper we aim to submit to a conference is modelled as an ordinary task of a
dedicated "Conference Papers" project (identifier CONF) — no task-schema change.
This reuses the whole task machinery: the notes editor, RBAC, status history
and the shared Task Details modal. Optionally a paper targets a conference from
the Conference Calendar; that link is a lightweight deliverable projecting the
conference (so the paper inherits the submission deadline and shows up in the
existing Calendar/Reports views).

Editing follows the app-wide rule: admins, owners and supervisors can edit;
everyone can see the board (collaborative planning), like Active Tasks.
"""

from __future__ import annotations

import datetime
import html

import streamlit as st

from core.supabase_client import supabase
from db import (
    get_or_create_conference_project,
    get_conferences,
    ensure_conference_deliverable,
    log_status_change,
    get_comment_counts,
)
from utils.helpers import fmt_date, sort_tasks_by_deadline, comment_badge_html
from utils.modals import task_details_modal, person_pill_html
from utils.notifications import send_task_assigned


_STATUS_COLOURS = {
    "Not started": ("#888888", "#f0f0f0"),
    "Working on":  ("#1565C0", "#E3F2FD"),
    "Blocked":     ("#E65100", "#FFF3E0"),
    "Completed":   ("#2E7D32", "#E8F5E9"),
    "Cancelled":   ("#B71C1C", "#FFEBEE"),
}


def _badge(text: str, fg: str, bg: str) -> str:
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 8px;border-radius:4px;"
        f"font-size:0.78rem;font-weight:600;white-space:nowrap'>{html.escape(text)}</span>"
    )


def _deadline_html(deadline: str | None) -> str:
    if not deadline:
        return "<span style='color:#aaa;font-size:12px'>no deadline</span>"
    try:
        dl = datetime.date.fromisoformat(str(deadline)[:10])
    except Exception:
        return html.escape(str(deadline))
    days = (dl - datetime.date.today()).days
    if days < 0:
        col, extra = "#C62828", f"overdue {abs(days)}d"
    elif days <= 21:
        col, extra = "#E65100", f"in {days}d"
    else:
        col, extra = "#666", f"in {days}d"
    return (
        f"<span style='color:{col};font-size:12px;font-weight:600'>📅 {fmt_date(deadline)}</span>"
        f" <span style='color:{col};font-size:11px'>· {extra}</span>"
    )


def _people_pills(owner: str | None, sup: str | None, user_map: dict) -> str:
    pills = ""
    if owner:
        u = user_map.get(owner, {"name": owner, "avatar_color": "#534AB7"})
        pills += person_pill_html(u.get("name", owner), u.get("avatar_color", "#534AB7"), role="owner", compact=True)
    if sup and sup != owner:
        u = user_map.get(sup, {"name": sup, "avatar_color": "#BA7517"})
        pills += person_pill_html(u.get("name", sup), u.get("avatar_color", "#BA7517"), role="sup", compact=True)
    return pills


@st.dialog("Add conference paper", width="large")
def _add_paper_modal(project_id: int, users: list[dict], conferences: list[dict]):
    """Create a paper task, optionally targeting a conference (→ deliverable)."""
    user_opts = {f"{u['name']} ({u['email']})": u["email"] for u in users}
    me = st.session_state.get("user_email")

    # Map a target conference to its submission deadline for auto-fill.
    conf_opts = {"None (no target yet)": None}
    conf_map: dict[str, dict] = {}
    for c in conferences or []:
        label = c.get("acronym") or c.get("name") or f"Conference {c.get('id')}"
        if c.get("year"):
            label = f"{label} {c['year']}"
        conf_opts[label] = c.get("id")
        conf_map[label] = c

    with st.form("new_conf_paper_form"):
        title = st.text_input("Paper working title*")
        sel_conf_label = st.selectbox("Target conference", list(conf_opts.keys()))
        target_conf = conf_map.get(sel_conf_label)

        c1, c2 = st.columns(2)
        with c1:
            owner = st.selectbox(
                "Owner*", list(user_opts.keys()),
                index=list(user_opts.values()).index(me) if me in user_opts.values() else 0,
            )
            priority = st.selectbox("Priority", ["none", "low", "medium", "high", "urgent"], index=2)
        with c2:
            supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
            default_dl = None
            if target_conf and target_conf.get("submission_deadline"):
                try:
                    default_dl = datetime.date.fromisoformat(str(target_conf["submission_deadline"])[:10])
                except Exception:
                    default_dl = None
            deadline = st.date_input(
                "Deadline (defaults to submission)", value=default_dl, format="DD/MM/YYYY"
            )

        st.caption(
            "Notes are edited afterwards from the paper's **Details** dialog — like any task."
        )
        if st.form_submit_button("Create paper", type="primary"):
            if not title:
                st.error("A working title is required.")
                return

            deliverable_id = None
            if target_conf:
                deliverable_id = ensure_conference_deliverable(project_id, target_conf)

            owner_email = user_opts[owner]
            sup_email = user_opts[supervisor] if supervisor != "None" else None
            new_task = {
                "project_id":       project_id,
                "deliverable_id":   deliverable_id,
                "name":             title,
                "owner_email":      owner_email,
                "supervisor_email": sup_email,
                "status":           "Not started",
                "priority":         priority,
                "deadline":         deadline.isoformat() if deadline else None,
                "notes":            "",
                "sort_order":       999,
            }
            try:
                res = supabase.table("tasks").insert(new_task).execute()
                t_id = res.data[0]["id"]
                seq_id = f"CONF-{t_id}"
                supabase.table("tasks").update({"sequence_id": seq_id}).eq("id", t_id).execute()
                log_status_change("task", t_id, project_id, None, "Not started", me)

                assigner = st.session_state.get("user_name", me or "")
                enriched = {**new_task, "id": t_id, "sequence_id": seq_id, "project_name": "Conference Papers"}
                send_task_assigned(enriched, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(enriched, sup_email, assigner)

                st.success("Paper added.")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


def _render_paper_row(t: dict, user_map: dict, can_edit: bool, key_prefix: str, comment_counts: dict):
    status = t.get("status", "Not started")
    s_fg, s_bg = _STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
    seq = t.get("sequence_id") or f"CONF-{t['id']}"
    pills = _people_pills(t.get("owner_email"), t.get("supervisor_email"), user_map)
    cc_html = comment_badge_html(comment_counts.get(t.get("id"), 0))

    col_l, col_r = st.columns([8, 1.6])
    with col_l:
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:3px 0'>"
            f"<span style='font-family:monospace;color:#aaa;font-size:11px'>{html.escape(seq)}</span>"
            f"<span style='font-size:13px;font-weight:600'>{html.escape(t.get('name',''))}</span>"
            f"{_badge(status, s_fg, s_bg)}"
            f"{cc_html}"
            f"<span style='margin-left:6px'>{_deadline_html(t.get('deadline'))}</span>"
            f"</div>"
            f"<div style='padding-bottom:3px'>{pills or ''}</div>",
            unsafe_allow_html=True,
        )
    with col_r:
        if st.button("Details", key=f"{key_prefix}_{t['id']}", use_container_width=True):
            task_details_modal(t, can_edit=can_edit)


def show_conference_papers() -> None:
    st.title("🎤 Conference Papers")
    st.caption(
        "Papers we aim to submit, one per row. Each is a task — open **Details** to "
        "track notes, status and deadline. Group headers are the target conferences."
    )

    email = st.session_state.get("user_email")
    is_admin = st.session_state.get("user_role") == "admin"
    if not email:
        st.error("You must be logged in to view this page.")
        return

    project = get_or_create_conference_project(create=True)
    if not project:
        st.error(
            "Could not access the 'Conference Papers' project. If the database is "
            "read-only, ask an administrator to create a project named 'Conference Papers'."
        )
        return
    pid = project["id"]

    # Supporting data
    try:
        users = supabase.table("users").select("email, name, avatar_color").eq(
            "is_approved", True
        ).order("name").execute().data or []
        deliverables = supabase.table("deliverables").select("id, name, deadline").eq(
            "project_id", pid
        ).eq("is_archived", False).execute().data or []
        tasks = supabase.table("tasks").select("*").eq("project_id", pid).eq(
            "is_archived", False
        ).execute().data or []
    except Exception as e:
        st.error(f"Error loading conference papers: {e}")
        return

    user_map = {u["email"]: u for u in users}
    conferences = get_conferences(show_archived=False) or []
    comment_counts = get_comment_counts([t["id"] for t in tasks]) if tasks else {}

    top_l, top_r = st.columns([3, 1.4])
    with top_l:
        active = [t for t in tasks if t.get("status") not in ("Completed", "Cancelled")]
        st.markdown(f"**{len(active)}** active · **{len(tasks)}** total")
    with top_r:
        if st.button("➕ Add paper", type="primary", use_container_width=True):
            _add_paper_modal(pid, users, conferences)

    if not tasks:
        st.info("No conference papers yet. Click **Add paper** to start tracking one.")
        return

    st.divider()

    deliv_map = {d["id"]: d for d in deliverables}

    def _can_edit(t: dict) -> bool:
        return is_admin or t.get("owner_email") == email or t.get("supervisor_email") == email

    # Group by target conference (deliverable); generic papers last.
    grouped: dict = {}
    for t in tasks:
        grouped.setdefault(t.get("deliverable_id"), []).append(t)

    def _group_sort_key(item):
        did, _ = item
        if did is None:
            return (1, "9999-12-31", "")
        d = deliv_map.get(did, {})
        return (0, d.get("deadline") or "9999-12-31", d.get("name") or "")

    for did, group_tasks in sorted(grouped.items(), key=_group_sort_key):
        if did is None:
            header = "🗂️ No target conference"
            sub = ""
        else:
            d = deliv_map.get(did, {})
            header = f"🎯 {d.get('name', 'Conference')}"
            sub = f" · submission {fmt_date(d.get('deadline'))}" if d.get("deadline") else ""
        done = len([t for t in group_tasks if t.get("status") == "Completed"])
        st.markdown(
            f"<div style='background:#EEF3FF;border-radius:6px;padding:6px 12px;margin:8px 0 2px 0;"
            f"display:flex;align-items:center;gap:10px'>"
            f"<span style='font-weight:700;color:#1A3E8B'>{html.escape(header)}</span>"
            f"<span style='color:#5B6B8C;font-size:12px'>{done}/{len(group_tasks)} completed{sub}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        for t in sort_tasks_by_deadline(group_tasks):
            _render_paper_row(t, user_map, can_edit=_can_edit(t), key_prefix=f"confp_{did}", comment_counts=comment_counts)
