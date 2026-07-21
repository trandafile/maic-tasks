import streamlit as st
import datetime as _dt
import json
from core.supabase_client import supabase
from utils.modals import get_status_color_map, render_priority_badge, task_details_modal, subtask_details_modal, person_pill_html, deliverable_details_modal
from db import delete_task_cascade, log_status_change
from utils.pdf_generator import generate_projects_pdf
from utils.notifications import send_task_assigned
from utils.helpers import (
    fmt_date, sort_tasks_by_deadline, parse_deliverable_tag_styles, deliverable_chip_html,
    TASK_NAME_STYLE, SUBTASK_NAME_STYLE, SUBTASK_PREFIX, TASK_ROW_CLASS, SUBTASK_ROW_CLASS,
)
from utils.md_editor import markdown_editor
from db import get_settings

# ─── Status / Priority badge helpers ───────────────────────────────────────────
STATUS_COLOURS = {
    "Not started": ("#888888", "#f0f0f0"),
    "Working on":  ("#1565C0", "#E3F2FD"),
    "Blocked":     ("#E65100", "#FFF3E0"),
    "Completed":   ("#2E7D32", "#E8F5E9"),
    "Cancelled":   ("#B71C1C", "#FFEBEE"),
}

PRIORITY_COLOURS = {
    "none":   ("#888888", "#f0f0f0"),
    "low":    ("#1565C0", "#E3F2FD"),
    "medium": ("#E65100", "#FFF3E0"),
    "high":   ("#B71C1C", "#FFEBEE"),
    "urgent": ("#6A1B9A", "#F3E5F5"),
}

def _badge(text, fg, bg):
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 8px;"
        f"border-radius:4px;font-size:0.78rem;font-weight:600;"
        f"white-space:nowrap;display:inline-block'>{text}</span>"
    )

def _status_badge(status):
    fg, bg = STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
    return _badge(status, fg, bg)

def _priority_badge(priority):
    p = (priority or "none").lower()
    fg, bg = PRIORITY_COLOURS.get(p, ("#888", "#f0f0f0"))
    return _badge(p, fg, bg)


# ─── Data fetching ──────────────────────────────────────────────────────────────

def fetch_hierarchy(show_archived=False, user_email=None, is_admin=False, only_mine=False):
    """Load the project → deliverable → task → subtask hierarchy.

    only_mine: keep only tasks/subtasks where ``user_email`` is owner or
    supervisor, then prune the deliverables and projects left without any
    visible item. Used by the admin "my tasks" default scope.
    """
    try:
        pq = supabase.table("projects").select("*")
        if not show_archived:
            pq = pq.eq("is_archived", False)
        projects = pq.execute().data

        dq = supabase.table("deliverables").select("*")
        if not show_archived:
            dq = dq.eq("is_archived", False)
        deliverables = dq.execute().data

        tq = supabase.table("tasks").select("*").order("sort_order", desc=False)
        if not show_archived:
            tq = tq.eq("is_archived", False)
        tasks = tq.execute().data

        sq = supabase.table("subtasks").select("*").order("sort_order", desc=False)
        if not show_archived:
            sq = sq.eq("is_archived", False)
        subtasks = sq.execute().data

        users = supabase.table("users").select("email, name, avatar_color").eq("is_approved", True).execute().data
        user_map = {u["email"]: u for u in (users or [])}

        # RBAC: for non-admin users, only keep projects where they are involved.
        if not is_admin and user_email:
            tasks_by_id = {t["id"]: t for t in (tasks or [])}
            involved_project_ids = {
                t.get("project_id")
                for t in (tasks or [])
                if t.get("project_id")
                and (
                    t.get("owner_email") == user_email
                    or t.get("supervisor_email") == user_email
                )
            }
            involved_project_ids.update(
                tasks_by_id.get(s.get("task_id"), {}).get("project_id")
                for s in (subtasks or [])
                if (s.get("owner_email") == user_email or s.get("supervisor_email") == user_email)
                and tasks_by_id.get(s.get("task_id"), {}).get("project_id")
            )
            projects = [p for p in (projects or []) if p.get("id") in involved_project_ids]

        # "My tasks" scope: narrow tasks/subtasks to the ones I own or supervise,
        # then drop the deliverables and projects that end up with nothing to show.
        if only_mine and user_email:
            def _mine(item: dict) -> bool:
                return (
                    item.get("owner_email") == user_email
                    or item.get("supervisor_email") == user_email
                )

            all_tasks = tasks or []
            all_subtasks = subtasks or []

            # A task is visible when it is mine, or when it carries a subtask of mine.
            my_subtask_parent_ids = {s.get("task_id") for s in all_subtasks if _mine(s)}
            tasks = [t for t in all_tasks if _mine(t) or t.get("id") in my_subtask_parent_ids]

            visible_tasks_by_id = {t["id"]: t for t in tasks}
            # Show my subtasks, plus every subtask of a task that is mine (context).
            subtasks = [
                s for s in all_subtasks
                if s.get("task_id") in visible_tasks_by_id
                and (_mine(s) or _mine(visible_tasks_by_id[s["task_id"]]))
            ]

            task_deliv_ids = {t.get("deliverable_id") for t in tasks if t.get("deliverable_id")}
            deliverables = [
                d for d in (deliverables or [])
                if d.get("id") in task_deliv_ids or _mine(d)
            ]

            visible_project_ids = {t.get("project_id") for t in tasks if t.get("project_id")}
            visible_project_ids.update(
                d.get("project_id") for d in deliverables if d.get("project_id")
            )
            projects = [p for p in (projects or []) if p.get("id") in visible_project_ids]

        return projects, deliverables, tasks, subtasks, users, user_map
    except Exception as e:
        st.error(f"Errore nel caricamento dati: {e}")
        return [], [], [], [], [], {}


# ─── Modals ─────────────────────────────────────────────────────────────────────

@st.dialog("Add New Deliverable")
def add_deliverable_modal(project_id, users):
    cfg = get_settings()
    type_options = [
        s["name"].strip()
        for s in parse_deliverable_tag_styles(cfg.get("deliverable_tag_styles"), fallback_to_default=False)
        if str(s.get("name", "")).strip()
    ]
    if not type_options:
        raw_types = cfg.get("deliverable_types")
        if isinstance(raw_types, str):
            try:
                parsed = json.loads(raw_types)
                if isinstance(parsed, list):
                    type_options = [str(v).strip() for v in parsed if str(v).strip()]
            except Exception:
                type_options = []
    if not type_options:
        type_options = ["paper", "layout", "prototype"]

    with st.form("new_deliv_form"):
        name     = st.text_input("Deliverable Name*")
        type_val = st.selectbox("Type", type_options)
        deadline = st.date_input("Deadline", value=None, format="DD/MM/YYYY")
        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me = st.session_state.get('user_email')
        owner = st.selectbox(
            "Owner*",
            list(user_opts.keys()),
            index=list(user_opts.values()).index(me) if me in user_opts.values() else 0,
        )
        supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
        description = markdown_editor(
            value="",
            key=f"new_deliv_notes_{project_id}",
            height=220,
            label="📝 Deliverable Description",
        )
        if st.form_submit_button("Create Deliverable", type="primary"):
            if not name:
                st.error("Name is required.")
                return
            try:
                supabase.table("deliverables").insert({
                    "project_id": project_id, "name": name, "type": type_val,
                    "status": "Not started",
                    "deadline": str(deadline) if deadline else None,
                    "owner_email": user_opts[owner],
                    "supervisor_email": user_opts[supervisor] if supervisor != "None" else None,
                    "description": description or None,
                }).execute()
                # reset editor state for next open
                st.session_state.pop(f"__mde_new_deliv_notes_{project_id}", None)
                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Add New Task")
def add_task_modal(project_id, deliverables, users, prefill_deliverable_id=None):
    """Generic add-task modal; if prefill_deliverable_id is set that deliverable
    is pre-selected in the dropdown."""
    with st.form("new_task_form"):
        name = st.text_input("Task Title*")

        deliv_options = {"None": None}
        deliv_options.update({d["name"]: d["id"] for d in deliverables if d["project_id"] == project_id})

        # Pre-select deliverable if requested
        prefill_name = "None"
        if prefill_deliverable_id:
            for k, v in deliv_options.items():
                if v == prefill_deliverable_id:
                    prefill_name = k
                    break

        sel_deliv = st.selectbox(
            "Link to Deliverable",
            list(deliv_options.keys()),
            index=list(deliv_options.keys()).index(prefill_name)
        )

        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner    = st.selectbox("Owner*", list(user_opts.keys()),
                                     index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
            priority = st.selectbox("Priority", ["none", "low", "medium", "high", "urgent"], index=2)
        with c2:
            supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
            deadline   = st.date_input("Deadline", value=None, format="DD/MM/YYYY")

        notes = markdown_editor(
            value="",
            key=f"new_task_notes_{project_id}",
            height=280,
            label="📝 Notes / Description",
        )

        if st.form_submit_button("Create Task", type="primary"):
            if not name:
                st.error("Title is required.")
                return
            new_task = {
                "project_id":     project_id,
                "deliverable_id": deliv_options[sel_deliv],
                "name":           name,
                "owner_email":    user_opts[owner],
                "supervisor_email": user_opts[supervisor] if supervisor != "None" else None,
                "status":         "Not started",
                "priority":       priority,
                "deadline":       str(deadline) if deadline else None,
                "notes":          notes,
                "sort_order":     999,
            }
            try:
                res   = supabase.table("tasks").insert(new_task).execute()
                t_id  = res.data[0]['id']
                p_res = supabase.table("projects").select("identifier, name").eq("id", project_id).execute()
                ident = (p_res.data[0]['identifier'] if p_res.data and p_res.data[0]['identifier'] else "TSK")
                seq_id = f"{ident}-{t_id}"
                supabase.table("tasks").update({"sequence_id": seq_id}).eq("id", t_id).execute()

                log_status_change(
                    "task", t_id, project_id, None, "Not started",
                    st.session_state.get("user_email"),
                )

                # Notify owner and supervisor
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                proj_name = p_res.data[0].get("name", "") if p_res.data else ""
                enriched_task = {**new_task, "id": t_id, "sequence_id": seq_id, "project_name": proj_name}
                owner_email = user_opts[owner]
                sup_email   = user_opts[supervisor] if supervisor != "None" else None
                send_task_assigned(enriched_task, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(enriched_task, sup_email, assigner)

                # clear task notes editor after successful creation
                st.session_state.pop(f"__mde_new_task_notes_{project_id}", None)
                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Add Subtask")
def add_subtask_modal(task_id, users):
    with st.form("new_subtask_form"):
        name      = st.text_input("Subtask Title*")
        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me        = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner      = st.selectbox("Owner*", list(user_opts.keys()),
                                       index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
        with c2:
            supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
        deadline = st.date_input("Deadline", value=None, format="DD/MM/YYYY")

        notes = markdown_editor(
            value="",
            key=f"new_subtask_notes_{task_id}",
            height=280,
            label="📝 Notes / Description",
        )

        if st.form_submit_button("Create Subtask", type="primary"):
            if not name:
                st.error("Title is required.")
                return
            try:
                owner_email = user_opts[owner]
                sup_email   = user_opts[supervisor] if supervisor != "None" else None
                res = supabase.table("subtasks").insert({
                    "task_id":          task_id,
                    "name":             name,
                    "owner_email":      owner_email,
                    "supervisor_email": sup_email,
                    "status":           "Not started",
                    "deadline":         str(deadline) if deadline else None,
                    "notes":            notes,
                    "sort_order":       999,
                }).execute()

                if res.data:
                    parent_rows = supabase.table("tasks").select("project_id").eq(
                        "id", task_id
                    ).execute().data
                    log_status_change(
                        "subtask", res.data[0]["id"],
                        parent_rows[0].get("project_id") if parent_rows else None,
                        None, "Not started",
                        st.session_state.get("user_email"),
                    )

                # Notify owner and supervisor
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                subtask_as_task = {
                    "id": res.data[0]["id"] if res.data else 0,
                    "sequence_id": f"SUB-{res.data[0]['id']}" if res.data else "",
                    "name": name,
                    "deadline": str(deadline) if deadline else None,
                    "priority": "none",
                    "project_name": "",
                }
                send_task_assigned(subtask_as_task, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(subtask_as_task, sup_email, assigner)

                # clear subtask notes editor after successful creation
                st.session_state.pop(f"__mde_new_subtask_notes_{task_id}", None)
                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Create New Project")
def add_project_modal():
    with st.form("new_proj_form"):
        name       = st.text_input("Project Name*")
        c1, c2     = st.columns(2)
        with c1:
            acronym    = st.text_input("Acronym", help="E.g. HIPA2")
            identifier = st.text_input("Task ID Template*", help="E.g. HIP → HIP-1, HIP-2…")
        with c2:
            start_date = st.date_input("Start Date", value=_dt.date.today(), format="DD/MM/YYYY")
            end_date   = st.date_input("Estimated End Date", value=None, format="DD/MM/YYYY")
        funding = st.text_input("Funding Agency")
        description = markdown_editor(
            value="",
            key="new_proj_notes",
            height=220,
            label="📝 Project Description (optional)",
        )

        if st.form_submit_button("Create Project", type="primary"):
            if not name or not identifier:
                st.error("Name and ID Template are required.")
                return
            try:
                supabase.table("projects").insert({
                    "name":            name,
                    "acronym":         acronym,
                    "identifier":      identifier.upper(),
                    "funding_agency":  funding,
                    "description":     description or None,
                    "start_date":      str(start_date) if start_date else None,
                    "end_date":        str(end_date) if end_date else None,
                    "is_archived":     False,
                }).execute()
                # clear project description editor after successful creation
                st.session_state.pop("__mde_new_proj_notes", None)
                st.success("Project created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


# ─── Task row renderer ──────────────────────────────────────────────────────────

def _deadline_html(deadline_str: str | None, status: str, threshold: int = 7) -> str:
    if not deadline_str:
        return ""
    try:
        dl = _dt.date.fromisoformat(deadline_str)
        delta = (dl - _dt.date.today()).days
        label = dl.strftime("%Y/%m/%d")
    except Exception:
        return ""

    if status in ("Completed", "Cancelled"):
        return (
            f"<span style='font-size:11px;color:#888;'>"
            f"📅 {label}</span>"
        )
    if delta < 0:
        days = abs(delta)
        return (
            f"<span style='font-size:11px;color:#E24B4A;font-weight:500;'>📅 {label}</span>&nbsp;"
            f"<span style='font-size:10px;background:#FCEBEB;color:#A32D2D;"
            f"padding:1px 6px;border-radius:3px;font-weight:600;'>overdue {days}d</span>"
        )
    if delta <= threshold:
        return (
            f"<span style='font-size:11px;color:#BA7517;font-weight:500;'>📅 {label}</span>&nbsp;"
            f"<span style='font-size:10px;background:#FAEEDA;color:#854F0B;"
            f"padding:1px 6px;border-radius:3px;font-weight:600;'>due in {delta}d</span>"
        )
    return (
        f"<span style='font-size:11px;color:#888;'>📅 {label}</span>"
    )


def _parse_date(value: str | None) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _deadline_window_days(scope: str | None) -> int | None:
    mapping = {
        "week": 7,
        "month": 30,
    }
    return mapping.get(scope or "")


def _matches_people(item: dict, owner_email: str | None, supervisor_email: str | None) -> bool:
    if owner_email and item.get("owner_email") != owner_email:
        return False
    if supervisor_email and item.get("supervisor_email") != supervisor_email:
        return False
    return True


def _matches_deadline(item: dict, deadline_days: int | None) -> bool:
    if deadline_days is None:
        return True
    dl = _parse_date(item.get("deadline"))
    if not dl:
        return False
    delta = (dl - _dt.date.today()).days
    return 0 <= delta <= deadline_days


def _apply_projects_filters(
    projects: list[dict],
    deliverables: list[dict],
    tasks: list[dict],
    subtasks: list[dict],
    *,
    is_admin: bool,
    owner_email: str | None = None,
    supervisor_email: str | None = None,
    deadline_scope: str | None = None,
):
    deadline_days = _deadline_window_days(deadline_scope)
    owner_filter = owner_email if is_admin else None
    supervisor_filter = supervisor_email if is_admin else None

    def _task_visible(task: dict) -> bool:
        return _matches_people(task, owner_filter, supervisor_filter) and _matches_deadline(task, deadline_days)

    def _subtask_visible(subtask: dict) -> bool:
        return _matches_people(subtask, owner_filter, supervisor_filter) and _matches_deadline(subtask, deadline_days)

    visible_subtask_ids = {s["id"] for s in subtasks if s.get("id") is not None and _subtask_visible(s)}
    visible_task_ids = {
        t["id"]
        for t in tasks
        if t.get("id") is not None and (
            _task_visible(t)
            or any(s.get("task_id") == t.get("id") for s in subtasks if s.get("id") in visible_subtask_ids)
        )
    }
    visible_deliv_ids = {
        d["id"]
        for d in deliverables
        if d.get("id") is not None and any(t.get("deliverable_id") == d.get("id") for t in tasks if t.get("id") in visible_task_ids)
    }
    visible_project_ids = {
        t.get("project_id")
        for t in tasks
        if t.get("id") in visible_task_ids and t.get("project_id") is not None
    }

    filtered_projects = [p for p in projects if p.get("id") in visible_project_ids]
    filtered_deliverables = [d for d in deliverables if d.get("id") in visible_deliv_ids]
    filtered_tasks = [t for t in tasks if t.get("id") in visible_task_ids]
    filtered_subtasks = [s for s in subtasks if s.get("task_id") in visible_task_ids]

    return filtered_projects, filtered_deliverables, filtered_tasks, filtered_subtasks


def _is_projects_filter_active(*, is_admin: bool, owner_email: str | None, supervisor_email: str | None, deadline_scope: str | None) -> bool:
    """Return True when at least one Projects filter is actively restricting the view."""
    people_filter_active = is_admin and (owner_email is not None or supervisor_email is not None)
    deadline_filter_active = deadline_scope is not None
    return people_filter_active or deadline_filter_active


def _get_projects_filter_signature(*, is_admin: bool, owner_email: str | None, supervisor_email: str | None, deadline_scope: str | None) -> tuple:
    """Build a stable signature used to detect filter changes across reruns."""
    return (is_admin, owner_email, supervisor_email, deadline_scope)


def _render_task_row(t, subtasks, users, user_map, user_email, is_admin, key_prefix, threshold: int):
    t_id      = t["id"]
    is_owner  = t.get("owner_email") == user_email
    is_sup    = t.get("supervisor_email") == user_email
    can_edit  = is_admin or is_owner or is_sup
    readonly_for_user = (not is_admin) and (not can_edit)
    opacity   = "1" if can_edit else "0.35" if readonly_for_user else "0.45"
    seq_id    = t.get("sequence_id") or f"T-{t_id}"
    status    = t.get("status", "Not started")
    priority  = (t.get("priority") or "none").lower()
    name      = t.get("name", "")

    owner_e = t.get("owner_email")
    sup_e   = t.get("supervisor_email")
    pills   = ""
    if not readonly_for_user:
        if owner_e:
            u = user_map.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
            pills += person_pill_html(
                u.get("name", owner_e),
                u.get("avatar_color", "#534AB7"),
                role="owner",
                compact=False,
            )
        if sup_e and sup_e != owner_e:
            u = user_map.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
            pills += person_pill_html(
                u.get("name", sup_e),
                u.get("avatar_color", "#BA7517"),
                role="sup",
                compact=False,
            )

    dl_html = "" if readonly_for_user else _deadline_html(t.get("deadline"), status, threshold)
    s_fg, s_bg = STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
    p_fg, p_bg = PRIORITY_COLOURS.get(priority, ("#888", "#f0f0f0"))
    s_badge = _badge(status, s_fg, s_bg)
    p_badge = _badge(priority, p_fg, p_bg) if not readonly_for_user else ""

    col_html, col_btns = st.columns([6, 4])
    with col_html:
        st.html(
            f"""
            <div class='{TASK_ROW_CLASS}'
                 style='display:grid;grid-template-columns:52px 1fr auto;
                        gap:0;padding:5px 8px 5px 8px;align-items:start;
                        opacity:{opacity};'>
              <span style='font-family:monospace;font-size:10px;
                           color:#aaa;padding-top:4px;'>{seq_id}</span>
              <div>
                <div style='display:flex;align-items:center;gap:7px;
                            flex-wrap:wrap;margin-bottom:5px;'>
                  <span style='{TASK_NAME_STYLE}'>{name}</span>
                  {s_badge}
                  {p_badge}
                  {f"<span style='margin-left:8px;'>{dl_html}</span>" if dl_html else ""}
                </div>
                {f"<div>{pills}</div>" if pills else ""}
              </div>
              <div></div>
            </div>
            """
        )
    with col_btns:
        if readonly_for_user:
            st.write("")  # no actions for non-involved users
        else:
            b1, b2, b3 = st.columns([2.5, 2, 1])
            with b1:
                if st.button("Details", key=f"{key_prefix}_det_{t_id}", use_container_width=True):
                    task_details_modal(t, can_edit)
            with b2:
                if st.button("+ Sub", key=f"{key_prefix}_addsub_{t_id}", disabled=not can_edit, use_container_width=True):
                    add_subtask_modal(t_id, users)
            with b3:
                if is_admin:
                    confirm_key = f"_confirm_del_t_{t_id}"
                    if st.button("✕", key=f"{key_prefix}_delx_{t_id}", help="Permanently delete", use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()

    # ── Delete confirmation (inline, full width) ─────────────────────────────
    confirm_key = f"_confirm_del_t_{t_id}"
    if st.session_state.get(confirm_key):
        with st.container():
            st.warning(
                f"Permanently delete **{seq_id} — {t.get('name')}**? "
                f"This action cannot be undone."
            )
            cc1, cc2, cc3 = st.columns([1.5, 1.5, 7])
            with cc1:
                if st.button("Yes, delete", key=f"{key_prefix}_delyes_{t_id}", type="primary"):
                    delete_task_cascade(t_id)
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            with cc2:
                if st.button("Cancel", key=f"{key_prefix}_delno_{t_id}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()

    # ── Nested subtasks ──────────────────────────────────────────────────────
    t_subtasks = sort_tasks_by_deadline([s for s in subtasks if s.get("task_id") == t_id])
    for s in t_subtasks:
        s_id        = s["id"]
        s_is_owner  = s.get("owner_email") == user_email
        s_can_edit  = is_admin or s_is_owner or (s.get("supervisor_email") == user_email)
        s_readonly  = (not is_admin) and (not s_can_edit)
        s_opacity   = "1" if s_can_edit else "0.35" if s_readonly else "0.45"
        s_status    = s.get("status", "Not started")
        s_name      = s.get("name", "")

        s_owner_e = s.get("owner_email")
        s_sup_e   = s.get("supervisor_email")
        s_pills   = ""
        if not s_readonly:
            if s_owner_e:
                u = user_map.get(s_owner_e, {"name": s_owner_e, "avatar_color": "#534AB7"})
                s_pills += person_pill_html(
                    u.get("name", s_owner_e),
                    u.get("avatar_color", "#534AB7"),
                    role="owner",
                    compact=False,
                )
            if s_sup_e and s_sup_e != s_owner_e:
                u = user_map.get(s_sup_e, {"name": s_sup_e, "avatar_color": "#BA7517"})
                s_pills += person_pill_html(
                    u.get("name", s_sup_e),
                    u.get("avatar_color", "#BA7517"),
                    role="sup",
                    compact=False,
                )

        s_dl_html = "" if s_readonly else _deadline_html(s.get("deadline"), s_status, threshold)
        ss_fg, ss_bg = STATUS_COLOURS.get(s_status, ("#888", "#f0f0f0"))
        s_badge = _badge(s_status, ss_fg, ss_bg)

        scol_html, scol_btns = st.columns([6, 4])
        with scol_html:
            st.html(
                f"""
                <div class='{SUBTASK_ROW_CLASS}'
                     style='display:grid;grid-template-columns:52px 1fr auto;
                            gap:0;padding:5px 8px 4px 8px;align-items:start;
                            opacity:{s_opacity};padding-left:24px;'>
                  <span></span>
                  <div>
                    <div style='display:flex;align-items:center;gap:7px;
                                flex-wrap:wrap;margin-bottom:5px;'>
                      <span style='{SUBTASK_NAME_STYLE}'>{SUBTASK_PREFIX} {s_name}</span>
                      {s_badge}
                    </div>
                    {f"<div style='margin-bottom:5px;'>{s_dl_html}</div>" if s_dl_html else ""}
                    {f"<div>{s_pills}</div>" if s_pills else ""}
                  </div>
                  <div></div>
                </div>
                """
            )
        with scol_btns:
            if s_readonly:
                st.write("")
            else:
                sb1, sb2 = st.columns([3, 1])
                with sb1:
                    if st.button("Details", key=f"{key_prefix}_vistaS_{s_id}", use_container_width=True):
                        subtask_details_modal(s, s_can_edit)
                with sb2:
                    if is_admin:
                        s_confirm_key = f"_confirm_del_s_{s_id}"
                        if st.button("✕", key=f"{key_prefix}_sdelx_{s_id}", help="Permanently delete", use_container_width=True):
                            st.session_state[s_confirm_key] = True
                            st.rerun()

        # subtask delete confirmation
        s_confirm_key = f"_confirm_del_s_{s_id}"
        if st.session_state.get(s_confirm_key):
            with st.container():
                st.warning(
                    f"Permanently delete subtask **{s.get('name')}**? "
                    f"This action cannot be undone."
                )
                scc1, scc2, scc3 = st.columns([1.5, 1.5, 7])
                with scc1:
                    if st.button("Yes, delete", key=f"{key_prefix}_sdelyes_{s_id}", type="primary"):
                        supabase.table("subtasks").delete().eq("id", s_id).execute()
                        st.session_state.pop(s_confirm_key, None)
                        st.rerun()
                with scc2:
                    if st.button("Cancel", key=f"{key_prefix}_sdelno_{s_id}"):
                        st.session_state.pop(s_confirm_key, None)
                        st.rerun()


# ─── Main view ──────────────────────────────────────────────────────────────────

def _render_archive_completed(tasks: list, subtasks: list) -> None:
    """Admin-only: archive every Completed item currently in view.

    Scoped to what the filters show, so it can be used per project rather than
    only globally. Archiving hides, never deletes — the data stays for the
    punctuality and trend reports, which read archived rows on purpose.
    """
    done_t = [t for t in tasks if (t.get("status") or "") == "Completed" and not t.get("is_archived")]
    done_s = [s for s in subtasks if (s.get("status") or "") == "Completed" and not s.get("is_archived")]
    total = len(done_t) + len(done_s)
    if not total:
        return

    key = "_confirm_archive_completed"
    c_info, c_btn = st.columns([6, 2])
    with c_info:
        st.caption(
            f"🗄️ **{total} completed items in view** "
            f"({len(done_t)} tasks, {len(done_s)} subtasks) — archiving clears the "
            "board without losing history."
        )
    with c_btn:
        if st.session_state.get(key):
            if st.button(f"✅ Confirm ({total})", key="arch_done_ok",
                         type="primary", use_container_width=True):
                ok_t = ok_s = 0
                try:
                    if done_t:
                        supabase.table("tasks").update({"is_archived": True}).in_(
                            "id", [t["id"] for t in done_t]).execute()
                        ok_t = len(done_t)
                    if done_s:
                        supabase.table("subtasks").update({"is_archived": True}).in_(
                            "id", [s["id"] for s in done_s]).execute()
                        ok_s = len(done_s)
                    st.session_state.pop(key, None)
                    st.success(f"Archived {ok_t} tasks and {ok_s} subtasks.")
                    st.rerun()
                except Exception as e:
                    st.session_state.pop(key, None)
                    st.error(f"Archiving failed: {e}")
        else:
            if st.button("🗄️ Archive completed", key="arch_done",
                         use_container_width=True,
                         help="Archive every Completed task/subtask currently shown."):
                st.session_state[key] = True
                st.rerun()
    if st.session_state.get(key):
        st.warning(
            f"Archive **{total}** completed items now in view? They disappear from the "
            "board but stay in the database (and in the reports). Use *Show Archived* to see them."
        )


def show_projects():
    st.title("Projects")
    st.caption(
        "The full work breakdown: project → deliverable → task → subtask. "
        "Create and organise here; the **Dashboard** tells you what is urgent."
    )

    # Compact row rhythm for dense task/subtask tables in this page.
    st.markdown(
        """
        <style>
        div[data-testid='stButton'] > button {
            min-height: 1.75rem;
            padding: 0.15rem 0.5rem;
            font-size: 0.78rem;
        }
        div[data-testid='stHorizontalBlock'] {
            padding-top: 3px !important;
            padding-bottom: 3px !important;
        }
        /* tighten vertical spacing between rows inside project view */
        div[data-testid='stVerticalBlock'] > div:has(> div[data-testid='stHorizontalBlock']) {
            margin-top: 0.05rem !important;
            margin-bottom: 0.05rem !important;
        }
        /* deliverable box custom green border */
        .deliverable-box [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid #9FD9C8 !important;
            border-radius: 0.5rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    user_email = st.session_state.get('user_email')
    is_admin   = st.session_state.get('user_role') == 'admin'

    col_tools, c_scope, c_actions = st.columns([1.4, 2.2, 2.2])
    with col_tools:
        if is_admin:
            if st.button("➕ New Project", type="primary", use_container_width=True):
                add_project_modal()
    with c_scope:
        if is_admin:
            show_all = st.checkbox(
                "All tasks and projects",
                value=False,
                key="proj_show_all",
                help="Unchecked (default): only tasks where you are the owner or the supervisor.",
            )
        else:
            # Non-admins are already scoped to the projects they are involved in.
            show_all = True
    with c_actions:
        a_exp, a_col, a_arch = st.columns([1.0, 1.0, 1.3])
        with a_exp:
            if st.button("Expand all", key="proj_expand_all", use_container_width=True):
                st.session_state["_projects_expand_mode"] = "all"
        with a_col:
            if st.button("Collapse all", key="proj_collapse_all", use_container_width=True):
                st.session_state["_projects_expand_mode"] = "none"
        with a_arch:
            show_archived = st.checkbox("Show Archived", value=False)

    only_mine = is_admin and not show_all
    if only_mine:
        st.caption("Showing only tasks where you are owner or supervisor.")

    projects, deliverables, tasks, subtasks, users, user_map = fetch_hierarchy(
        show_archived,
        user_email=user_email,
        is_admin=is_admin,
        only_mine=only_mine,
    )

    # deadline urgency threshold from settings
    try:
        settings = get_settings()
        threshold = int(settings.get("expiring_threshold_days", 7))
    except Exception:
        threshold = 7

    if not projects:
        if only_mine:
            st.info(
                "You have no tasks assigned to you as owner or supervisor. "
                "Tick **All tasks and projects** to see everything."
            )
        else:
            st.info("No active tasks found. Create a new task to get started.")
        return

    user_labels = [f"{u['name']} ({u['email']})" for u in users if u.get("email")]
    user_label_to_email = {f"{u['name']} ({u['email']})": u["email"] for u in users if u.get("email")}

    with st.expander("⚙️ View filters", expanded=False):
        if is_admin:
            c_owner, c_sup, c_dead, c_export = st.columns([2.1, 2.1, 1.4, 1.6])
            with c_owner:
                owner_label = st.selectbox(
                    "Owner",
                    ["All owners"] + user_labels,
                    key="proj_filter_owner",
                )
            with c_sup:
                supervisor_label = st.selectbox(
                    "Supervisor",
                    ["All supervisors"] + user_labels,
                    key="proj_filter_supervisor",
                )
        else:
            c_dead, c_export = st.columns([2.0, 1.6])
            owner_label = "All owners"
            supervisor_label = "All supervisors"

        with c_dead:
            deadline_label = st.selectbox(
                "Deadline",
                ["All deadlines", "Within a week", "Within a month"],
                key="proj_filter_deadline",
            )

        owner_email = user_label_to_email.get(owner_label) if is_admin and owner_label != "All owners" else None
        supervisor_email = user_label_to_email.get(supervisor_label) if is_admin and supervisor_label != "All supervisors" else None
        deadline_scope = {
            "Within a week": "week",
            "Within a month": "month",
        }.get(deadline_label)
        filters_active = _is_projects_filter_active(
            is_admin=is_admin,
            owner_email=owner_email,
            supervisor_email=supervisor_email,
            deadline_scope=deadline_scope,
        )
        filter_signature = _get_projects_filter_signature(
            is_admin=is_admin,
            owner_email=owner_email,
            supervisor_email=supervisor_email,
            deadline_scope=deadline_scope,
        )

        prev_signature = st.session_state.get("_projects_last_filter_signature")
        if prev_signature is None:
            st.session_state["_projects_last_filter_signature"] = filter_signature
            st.session_state.setdefault("_projects_expand_all_once", False)
        elif prev_signature != filter_signature:
            st.session_state["_projects_last_filter_signature"] = filter_signature
            st.session_state["_projects_expand_all_once"] = filters_active

        filtered_projects, filtered_deliverables, filtered_tasks, filtered_subtasks = _apply_projects_filters(
            projects,
            deliverables,
            tasks,
            subtasks,
            is_admin=is_admin,
            owner_email=owner_email,
            supervisor_email=supervisor_email,
            deadline_scope=deadline_scope,
        )

        with c_export:
            pdf_buf = generate_projects_pdf(
                filtered_projects,
                filtered_deliverables,
                filtered_tasks,
                filtered_subtasks,
                users,
            )
            st.download_button(
                "📄 Export PDF",
                data=pdf_buf,
                file_name=f"projects_view_{_dt.date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        if is_admin:
            st.caption("Admins can filter by owner and supervisor. Everyone can filter by deadline.")
        else:
            st.caption("You can filter the view by deadline.")

    if filters_active:
        st.caption("🔎 Filters are active — some projects may be hidden.")

    # ── Admin housekeeping: clear the backlog of finished work ───────────────
    if is_admin:
        _render_archive_completed(filtered_tasks, filtered_subtasks)

    projects = filtered_projects
    deliverables = filtered_deliverables
    tasks = filtered_tasks
    subtasks = filtered_subtasks

    expand_all_once = bool(st.session_state.get("_projects_expand_all_once", False))
    expand_mode = st.session_state.get("_projects_expand_mode")
    expand_all_now = (expand_mode == "all") or expand_all_once
    collapse_all_now = expand_mode == "none"

    for proj in projects:
        proj_id   = proj["id"]
        proj_name = proj.get("name", "Project")
        acronym   = proj.get("acronym", "")
        arch_tag  = " 🗄️ ARCHIVED" if proj.get("is_archived") else ""

        # Open all on filter-change one-shot or when requested via top command bar.
        with st.expander(
            f"📁 {proj_name} ({acronym}){arch_tag}",
            expanded=expand_all_now if not collapse_all_now else False,
        ):

            proj_deliverables = [d for d in deliverables if d.get("project_id") == proj_id]

            # ── Top-bar: add deliverable + add generic task ───────────────────
            tc1, tc2, _ = st.columns([2, 2, 6])
            with tc1:
                if is_admin:
                    if st.button("➕ Deliverable", key=f"add_del_{proj_id}", use_container_width=True):
                        add_deliverable_modal(proj_id, users)
            with tc2:
                if st.button("➕ Generic Task", key=f"add_generic_t_{proj_id}", use_container_width=True):
                    add_task_modal(proj_id, deliverables, users, prefill_deliverable_id=None)
            with _:
                if not proj_deliverables:
                    st.markdown(
                        "<div style='font-style:italic;color:#888;font-size:0.85rem;"
                        "line-height:2.2rem;padding-left:0.25rem'>"
                        "No deliverables defined for this project."
                        "</div>",
                        unsafe_allow_html=True,
                    )

            # ── One styled block per deliverable ──────────────────────────────
            for d in proj_deliverables:
                d_id     = d["id"]
                d_name   = d.get("name", "")
                d_type   = d.get("type", "")
                d_status = d.get("status", "Not started")
                arch_d   = " (archived)" if d.get("is_archived") else ""
                owner_e  = d.get("owner_email")
                sup_e    = d.get("supervisor_email")

                user_map = {u["email"]: u for u in users}
                d_people = ""
                if owner_e:
                    u = user_map.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
                    d_people += person_pill_html(
                        u.get("name", owner_e),
                        u.get("avatar_color", "#534AB7"),
                        role="owner",
                        compact=False,
                    )
                if sup_e and sup_e != owner_e:
                    u = user_map.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
                    d_people += person_pill_html(
                        u.get("name", sup_e),
                        u.get("avatar_color", "#BA7517"),
                        role="sup",
                        compact=False,
                    )

                deliv_tasks = [t for t in tasks if t.get("deliverable_id") == d_id]
                deliv_tasks = sort_tasks_by_deadline(deliv_tasks)

                # Wrap each deliverable block so we can scope a custom border colour
                st.markdown("<div class='deliverable-box'>", unsafe_allow_html=True)
                with st.container(border=True):
                    # Deliverable header
                    h1, h_det, h_arch = st.columns([6.5, 1.2, 0.8])
                    d_deadline_txt = f" · {fmt_date(d.get('deadline'))}" if d.get("deadline") else ""
                    d_type_chip = deliverable_chip_html(d_type or "generic", settings)
                    with h1:
                        st.html(
                            f"<div style='background:#E6F7F3;border-radius:6px;padding:6px 10px;"
                            f"margin-bottom:4px'>"
                            f"<span style='font-size:10px;color:#2E8B6E;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;'>Deliverable</span> "
                            f"<b style='color:#0F5943;'>{d_name}</b>"
                            f"<i style='color:#2E8B6E;font-size:0.85rem'>"
                            f"  {d_type_chip}{d_deadline_txt}{arch_d}</i>"
                            f"&nbsp;&nbsp;"
                            f"<span style='float:right'>{_status_badge(d_status)}</span>"
                            f"</div>"
                        )
                        st.html(d_people if d_people else "<span style='color:#2E8B6E;font-size:0.82rem'>Owner/Supervisor: —</span>")
                    with h_det:
                        if st.button("🔍", key=f"det_del_{d_id}", use_container_width=True):
                            d_can_edit = (
                                is_admin
                                or d.get("owner_email") == user_email
                                or d.get("supervisor_email") == user_email
                            ) and not d.get("is_archived")
                            deliverable_details_modal(d, can_edit=d_can_edit)
                    with h_arch:
                        if is_admin and not d.get("is_archived"):
                            if st.button("🗑️", key=f"arch_del_{d_id}", help="Archive Deliverable"):
                                supabase.table("deliverables").update({"is_archived": True}).eq("id", d_id).execute()
                                st.rerun()

                    # Task rows
                    if not deliv_tasks:
                        st.caption("    *No tasks for this deliverable.*")
                    else:
                        for t in deliv_tasks:
                            _render_task_row(
                                t,
                                subtasks,
                                users,
                                user_map,
                                user_email,
                                is_admin,
                                key_prefix=f"d{d_id}",
                                threshold=threshold,
                            )

                    # Per-deliverable "+ New Task" button
                    if st.button(f"➕ New Task in «{d_name}»", key=f"add_dt_{d_id}",
                                 use_container_width=True):
                        add_task_modal(proj_id, deliverables, users, prefill_deliverable_id=d_id)
                st.markdown("</div>", unsafe_allow_html=True)

            # ── Unassigned tasks section ──────────────────────────────────────
            unassigned = [
                t for t in tasks
                if t.get("project_id") == proj_id and not t.get("deliverable_id")
            ]
            unassigned = sort_tasks_by_deadline(unassigned)

            if unassigned:
                st.html(
                    "<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                    "color:#666;text-transform:uppercase'>Tasks without deliverable</span>"
                )
                with st.container(border=True):
                    for t in unassigned:
                        _render_task_row(
                            t,
                            subtasks,
                            users,
                            user_map,
                            user_email,
                            is_admin,
                            key_prefix=f"p{proj_id}_u",
                            threshold=threshold,
                        )

    if expand_all_once:
        st.session_state["_projects_expand_all_once"] = False
