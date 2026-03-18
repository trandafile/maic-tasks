"""
views/dashboard.py
──────────────────
Dashboard grouped by deliverable.
Two tabs: "To Do" (owner) and "To Review" (supervisor, non owner).
Urgency is shown on each card and no longer used as the primary grouping.
"""

import datetime
import streamlit as st
from core.supabase_client import supabase
from utils.modals import task_details_modal, subtask_details_modal, person_pill_html
from utils.helpers import PRIORITY_ORDER

_STATUS_BADGE = {
    "Not started": ("⚪", "#888888"),
    "Working on": ("🔵", "#1a73e8"),
    "Blocked": ("🔴", "#d93025"),
    "Completed": ("🟢", "#188038"),
    "Cancelled": ("⚫", "#444444"),
}

_PRIORITY_BADGE = {
    "urgent": ("🔴", "Urgent"),
    "high": ("🟠", "High"),
    "medium": ("🔵", "Medium"),
    "low": ("🟢", "Low"),
    "none": ("⚪", "None"),
}

_DELIVERABLE_TYPE_COLOURS = {
    "paper": ("#1565C0", "#E3F2FD"),
    "layout": ("#6A1B9A", "#F3E5F5"),
    "prototype": ("#E65100", "#FFF3E0"),
}

_INACTIVE = {"Completed", "Cancelled"}


def _fetch_data(email: str):
    """Load everything needed by dashboard, including deliverables of relevant projects."""
    try:
        s_res = supabase.table("settings").select("expiring_threshold_days").limit(1).execute()
        threshold = s_res.data[0]["expiring_threshold_days"] if s_res.data else 7
    except Exception:
        threshold = 7

    proj_res = supabase.table("projects").select("*").eq("is_archived", False).execute()
    projects = {p["id"]: p for p in (proj_res.data or [])}

    t_res = supabase.table("tasks").select("*").eq("is_archived", False).execute()
    all_tasks = t_res.data or []
    task_map = {t["id"]: t for t in all_tasks}

    st_res = supabase.table("subtasks").select("*").eq("is_archived", False).execute()
    all_subtasks = st_res.data or []

    u_res = supabase.table("users").select("email, name, avatar_color").eq("is_approved", True).execute()
    users = u_res.data or []
    user_map = {u["email"]: u for u in users}

    proj_ids = {
        t.get("project_id")
        for t in all_tasks
        if t.get("project_id")
        and (t.get("owner_email") == email or t.get("supervisor_email") == email)
        and t.get("status") not in _INACTIVE
    }
    proj_ids.update(
        task_map.get(s.get("task_id"), {}).get("project_id")
        for s in all_subtasks
        if s.get("task_id")
        and (s.get("owner_email") == email or s.get("supervisor_email") == email)
        and s.get("status") not in _INACTIVE
        and task_map.get(s.get("task_id"), {}).get("project_id")
    )

    all_deliverables = []
    if proj_ids:
        d_res = (
            supabase.table("deliverables")
            .select("*")
            .in_("project_id", list(proj_ids))
            .eq("is_archived", False)
            .execute()
        )
        all_deliverables = d_res.data or []

    deliverables = {d["id"]: d for d in all_deliverables}
    return threshold, projects, deliverables, all_tasks, all_subtasks, user_map


def _build_flat_list(email, mode, all_tasks, all_subtasks):
    if mode == "todo":
        user_tasks = [
            t for t in all_tasks
            if t.get("owner_email") == email and t.get("status") not in _INACTIVE
        ]
        user_subtasks_active = [
            s for s in all_subtasks
            if s.get("owner_email") == email and s.get("status") not in _INACTIVE
        ]
        user_subtasks_all = [s for s in all_subtasks if s.get("owner_email") == email]
    else:
        user_tasks = [
            t for t in all_tasks
            if t.get("supervisor_email") == email
            and t.get("owner_email") != email
            and t.get("status") not in _INACTIVE
        ]
        user_subtasks_active = [
            s for s in all_subtasks
            if s.get("supervisor_email") == email
            and s.get("owner_email") != email
            and s.get("status") not in _INACTIVE
        ]
        user_subtasks_all = user_subtasks_active

    active_subs_by_task = {}
    for s in user_subtasks_active:
        active_subs_by_task.setdefault(s.get("task_id"), []).append(s)

    all_subs_by_task = {}
    for s in user_subtasks_all:
        all_subs_by_task.setdefault(s.get("task_id"), []).append(s)

    result = []
    for task in user_tasks:
        tid = task["id"]
        active_subs = active_subs_by_task.get(tid, [])
        if active_subs:
            for s in active_subs:
                result.append({
                    "kind": "subtask",
                    "item": s,
                    "parent_task": task,
                    "suggest_close": False,
                })
        else:
            suggest_close = False
            if mode == "todo":
                all_subs = all_subs_by_task.get(tid, [])
                if all_subs and all(s.get("status") == "Completed" for s in all_subs):
                    suggest_close = True
            result.append({
                "kind": "task",
                "item": task,
                "parent_task": None,
                "suggest_close": suggest_close,
            })
    return _sort_entries(result)


def _sort_entries(entries: list) -> list:
    today = datetime.date.today()

    def key(e):
        t = e["item"]
        dl_str = t.get("deadline")
        prio = PRIORITY_ORDER.get((t.get("priority") or "none").lower(), 4)
        if not dl_str:
            return (1, datetime.date(9999, 12, 31), prio)
        try:
            dl = datetime.date.fromisoformat(dl_str)
        except Exception:
            return (1, datetime.date(9999, 12, 31), prio)
        # overdue or future — we only need consistent ASC by date;
        # grouping (overdue vs future) is handled by the date itself
        return (0, dl, prio)

    return sorted(entries, key=key)


def _deadline_group(deadline_str, today, threshold):
    if not deadline_str:
        return "future", ""
    try:
        dl = datetime.date.fromisoformat(deadline_str)
    except ValueError:
        return "future", ""

    delta = (dl - today).days
    if delta < 0:
        days_str = f"{abs(delta)} day{'s' if abs(delta) != 1 else ''}"
        html = f"<span style='color:#d93025;font-size:12px;'>Overdue by {days_str}</span>"
        return "overdue", html
    if delta <= threshold:
        days_str = f"{delta} day{'s' if delta != 1 else ''}"
        html = f"<span style='color:#e37400;font-size:12px;'>Due in {days_str}</span>"
        return "soon", html
    html = f"<span style='color:#888;font-size:12px;'>Due on {dl.strftime('%Y/%m/%d')}</span>"
    return "future", html


def _deliverable_deadline_html(deadline_str, threshold):
    if not deadline_str:
        return "<span style='color:#888'>—</span>"
    try:
        dl = datetime.date.fromisoformat(deadline_str)
    except ValueError:
        return f"<span style='color:#888'>{deadline_str}</span>"
    delta = (dl - datetime.date.today()).days
    color = "#d93025" if delta < 0 else "#e37400" if delta <= threshold else "#555"
    weight = "700" if delta <= threshold else "500"
    return f"<span style='color:{color};font-weight:{weight}'>{dl.strftime('%Y/%m/%d')}</span>"


def _deliverable_status_badge(status):
    icon, color = _STATUS_BADGE.get(status or "Not started", ("⚪", "#888888"))
    return (
        f"<span style='background:{color}22;color:{color};border-radius:3px;padding:2px 8px;font-size:11px;'>"
        f"{icon} {status or 'Not started'}</span>"
    )


def _deliverable_type_badge(type_value):
    fg, bg = _DELIVERABLE_TYPE_COLOURS.get((type_value or "").lower(), ("#555", "#F2F2F2"))
    label = type_value or "deliverable"
    return (
        f"<span style='background:{bg};color:{fg};border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;'>"
        f"{label}</span>"
    )


def _people_pills(owner_email, sup_email, user_map, compact=True):
    pills = ""
    if owner_email:
        u = user_map.get(owner_email, {"name": owner_email, "avatar_color": "#534AB7"})
        pills += person_pill_html(
            u.get("name", owner_email),
            u.get("avatar_color", "#534AB7"),
            role="owner",
            compact=compact,
        )
    if sup_email and sup_email != owner_email:
        u = user_map.get(sup_email, {"name": sup_email, "avatar_color": "#BA7517"})
        pills += person_pill_html(
            u.get("name", sup_email),
            u.get("avatar_color", "#BA7517"),
            role="sup",
            compact=compact,
        )
    return pills


def _render_item(entry, projects, deliverables, mode, today, threshold, user_map):
    kind = entry["kind"]
    item = entry["item"]
    parent_task = entry.get("parent_task")
    suggest_close = entry.get("suggest_close", False)
    item_id = item["id"]
    unique_key = f"{mode}_{kind}_{item_id}"

    if kind == "task":
        proj_id = item.get("project_id")
        deliv_id = item.get("deliverable_id")
    else:
        proj_id = parent_task.get("project_id") if parent_task else None
        deliv_id = parent_task.get("deliverable_id") if parent_task else None

    proj = projects.get(proj_id, {})
    proj_acronym = proj.get("acronym") or proj.get("name", "?")
    deliv = deliverables.get(deliv_id)
    deliv_name = deliv["name"] if deliv else "<em>generic task</em>"

    if kind == "subtask" and parent_task:
        breadcrumb = (
            f"<span style='color:#888;font-size:11px;'>"
            f"{proj_acronym} &rsaquo; {deliv_name} &rsaquo; {parent_task.get('name','')}</span>"
        )
    else:
        breadcrumb = (
            f"<span style='color:#888;font-size:11px;'>"
            f"{proj_acronym} &rsaquo; {deliv_name}</span>"
        )

    type_color = "#7c4dff" if kind == "subtask" else "#1a73e8"
    type_label = "subtask" if kind == "subtask" else "task"
    type_badge = (
        f"<span style='background:{type_color};color:white;border-radius:3px;"
        f"padding:1px 7px;font-size:10px;font-weight:600;margin-right:7px;'>{type_label}</span>"
    )

    status = item.get("status", "Not started")
    st_icon, st_color = _STATUS_BADGE.get(status, ("⚪", "#888"))
    status_badge = (
        f"<span style='background:{st_color}22;color:{st_color};"
        f"border-radius:3px;padding:2px 8px;font-size:11px;'>{st_icon} {status}</span>"
    )

    prio_badge = ""
    if kind == "task":
        prio = (item.get("priority") or "none").lower()
        prio_icon, prio_lbl = _PRIORITY_BADGE.get(prio, ("⚪", prio.capitalize()))
        prio_badge = (
            f"<span style='background:#f5f5f5;color:#555;border-radius:3px;padding:2px 8px;"
            f"font-size:11px;border:1px solid #ddd;'>{prio_icon} {prio_lbl}</span>"
        )

    close_badge = ""
    if suggest_close:
        close_badge = (
            "<span style='background:#fff3e0;color:#e65100;border-radius:3px;"
            "padding:2px 9px;font-size:11px;border:1px solid #ffcc80;margin-left:6px;'>"
            "✅ Subtask completati — chiudi il task?</span>"
        )

    persons_html = _people_pills(item.get("owner_email"), item.get("supervisor_email"), user_map, compact=True)
    persons_row = (
        persons_html
        if persons_html
        else "<span style='color:#888;font-size:11px;'>Owner/Supervisor: —</span>"
    )

    group_key, deadline_html = _deadline_group(item.get("deadline"), today, threshold)
    border_color = {"overdue": "#d93025", "soon": "#e37400", "future": "#cccccc"}[group_key]
    opacity = "0.78" if group_key == "future" else "1"

    # Compact two-row layout, similar to Active Tasks
    card_html = f"""
    <div style='border-left:3px solid {border_color};padding:8px 12px;
                margin-bottom:6px;background:#ffffff;border-radius:0 6px 6px 0;
                box-shadow:0 1px 3px rgba(0,0,0,.07);opacity:{opacity};'>
      <div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;'>
        {type_badge}
        <strong style='font-size:13px;'>{item.get('name', '')}</strong>
        {status_badge}
        {prio_badge}
        <span style='margin-left:auto;'>{deadline_html}</span>
      </div>
      <div style='display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;'>
        <span style='color:#888;font-size:11px;'>{breadcrumb}</span>
        <span>{persons_row}</span>
      </div>
      {close_badge}
    </div>
    """

    col_card, col_actions = st.columns([7, 2])
    with col_card:
        st.markdown(card_html, unsafe_allow_html=True)
    with col_actions:
        confirm_key = f"_confirm_complete_{unique_key}"

        if mode == "todo" and status != "Completed":
            if not st.session_state.get(confirm_key):
                if st.button("✓ Mark complete", key=f"done_{unique_key}", use_container_width=True, type="secondary"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(
                    f"Mark **{item.get('name','')}** as completed? "
                    "This will update its status to 'Completed'."
                )
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("Yes, complete", key=f"yes_done_{unique_key}", type="primary", use_container_width=True):
                        try:
                            update = {"status": "Completed"}
                            if kind == "task":
                                update["completion_date"] = today.isoformat()
                                supabase.table("tasks").update(update).eq("id", item_id).execute()
                            else:
                                supabase.table("subtasks").update(update).eq("id", item_id).execute()
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                with bc2:
                    if st.button("Cancel", key=f"no_done_{unique_key}", use_container_width=True):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()

        # On the dashboard, the user always sees items they own or supervise,
        # so allow editing in both To Do and To Review.
        can_edit = True
        if st.button("🔍 Details", key=f"det_{unique_key}", use_container_width=True):
            if kind == "task":
                task_details_modal(item, can_edit=can_edit)
            else:
                subtask_details_modal(item, can_edit=can_edit)


def _render_deliverable_header(deliverable, project, threshold, user_map):
    type_badge = _deliverable_type_badge(deliverable.get("type"))
    deadline_html = _deliverable_deadline_html(deliverable.get("deadline"), threshold)
    status_badge = _deliverable_status_badge(deliverable.get("status", "Not started"))
    pills = _people_pills(deliverable.get("owner_email"), deliverable.get("supervisor_email"), user_map, compact=True)
    project_label = project.get("acronym") or project.get("name", "")

    st.html(
        f"<div style='background:#F8F8F8;border-radius:6px;padding:8px 12px;margin:10px 0 4px 0;border:1px solid #EEE;'>"
        f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
        f"{type_badge}"
        f"<span style='font-weight:700;font-size:14px'>{deliverable.get('name', '')}</span>"
        f"<span style='color:#888;font-size:11px'>{project_label}</span>"
        f"<span style='margin-left:auto'>{status_badge}</span>"
        f"</div>"
        f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:4px'>"
        f"<span style='font-size:12px;color:#666'>Deadline: {deadline_html}</span>"
        f"{pills if pills else '<span style=\'color:#888;font-size:12px\'>Owner/Supervisor: —</span>'}"
        f"</div>"
        f"</div>",
    )


def _render_tab(entries, projects, deliverables, mode, today, threshold, user_map):
    grouped = {}
    generic_entries = []
    relevant_project_ids = set()

    for entry in entries:
        item = entry["item"]
        parent_task = entry.get("parent_task") or {}
        proj_id = item.get("project_id") or parent_task.get("project_id")
        deliv_id = item.get("deliverable_id") or parent_task.get("deliverable_id")
        if proj_id:
            relevant_project_ids.add(proj_id)
        if deliv_id:
            grouped.setdefault(deliv_id, []).append(entry)
        else:
            generic_entries.append(entry)

    deliverables_in_scope = [
        d for d in deliverables.values()
        if d.get("project_id") in relevant_project_ids
    ]
    deliverables_in_scope.sort(key=lambda d: (d.get("deadline") or "9999-12-31", d.get("name") or ""))

    if not deliverables_in_scope and not generic_entries:
        st.info("No active items. ✅")
        return

    for deliverable in deliverables_in_scope:
        project = projects.get(deliverable.get("project_id"), {})
        _render_deliverable_header(deliverable, project, threshold, user_map)
        entries_for_deliverable = grouped.get(deliverable.get("id"), [])
        if entries_for_deliverable:
            for entry in entries_for_deliverable:
                _render_item(entry, projects, deliverables, mode, today, threshold, user_map)
        else:
            st.caption("No tasks assigned to you in this deliverable")

    if generic_entries:
        st.html(
            "<div style='border:2px dashed #cccccc;border-radius:6px;padding:10px 16px;margin:16px 0 8px 0;'>"
            "<span style='font-weight:700;color:#888;font-size:0.95rem'>GENERIC TASKS (NO DELIVERABLE)</span></div>"
        )
        for entry in generic_entries:
            _render_item(entry, projects, deliverables, mode, today, threshold, user_map)


def show_dashboard():
    st.title("Dashboard")

    email = st.session_state.get("user_email")
    if not email:
        st.error("Utente non trovato in sessione.")
        return

    try:
        threshold, projects, deliverables, all_tasks, all_subtasks, user_map = _fetch_data(email)
    except Exception as e:
        st.error(f"Errore nel caricamento dei dati: {e}")
        return

    today = datetime.date.today()
    todo_entries = _build_flat_list(email, "todo", all_tasks, all_subtasks)
    review_entries = _build_flat_list(email, "review", all_tasks, all_subtasks)

    tab1, tab2 = st.tabs([f"To Do ({len(todo_entries)})", f"To Review ({len(review_entries)})"])

    with tab1:
        _render_tab(todo_entries, projects, deliverables, "todo", today, threshold, user_map)

    with tab2:
        st.caption("These tasks are assigned to others. Your role is to monitor, unblock, or approve.")
        _render_tab(review_entries, projects, deliverables, "review", today, threshold, user_map)
