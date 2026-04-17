"""
views/dashboard.py
──────────────────
Daily guidance dashboard:
- Tab 1: My Tasks (owner)
- Tab 2: Supervised Tasks (supervisor)

Hierarchy:
Project -> Deliverable -> Task -> Subtask

Projects are sorted by urgency (closest deadlines first).
"""

import datetime
import streamlit as st

from core.supabase_client import supabase
from db import get_settings
from utils.helpers import PRIORITY_ORDER, strip_markdown, deliverable_chip_html
from utils.modals import person_pill_html, task_details_modal, subtask_details_modal

_INACTIVE = {"Completed", "Cancelled"}

_STATUS_BADGE = {
    "Not started": ("⚪", "#888888"),
    "Working on": ("🔵", "#1565C0"),
    "Blocked": ("🔴", "#D93025"),
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


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except Exception:
        return None


def _truncate_text(value: str | None, max_len: int = 120) -> str:
    txt = strip_markdown(value or "").strip()
    if not txt:
        return ""
    if len(txt) <= max_len:
        return txt
    return f"{txt[: max_len - 1].rstrip()}…"


def _deadline_sort_key(deadline_str: str | None) -> datetime.date:
    dl = _parse_date(deadline_str)
    return dl or datetime.date(9999, 12, 31)


def _deadline_html(deadline_str: str | None, threshold: int) -> tuple[datetime.date | None, str]:
    dl = _parse_date(deadline_str)
    if not dl:
        return None, "<span style='font-size:11px;color:#999;'>No deadline</span>"

    delta = (dl - datetime.date.today()).days
    label = dl.strftime("%Y/%m/%d")

    if delta < 0:
        return (
            dl,
            f"<span style='font-size:11px;color:#D93025;font-weight:700;'>📅 {label}</span>"
            f" <span style='font-size:10px;background:#FDECEC;color:#A32020;padding:1px 6px;border-radius:3px;'>"
            f"overdue {abs(delta)}d</span>",
        )
    if delta <= threshold:
        return (
            dl,
            f"<span style='font-size:11px;color:#BA7517;font-weight:700;'>📅 {label}</span>"
            f" <span style='font-size:10px;background:#FAEEDA;color:#854F0B;padding:1px 6px;border-radius:3px;'>"
            f"due in {delta}d</span>",
        )
    return dl, f"<span style='font-size:11px;color:#666;'>📅 {label}</span>"


def _status_badge_html(status: str) -> str:
    icon, color = _STATUS_BADGE.get(status or "Not started", ("⚪", "#888888"))
    return (
        f"<span style='background:{color}22;color:{color};border-radius:4px;padding:2px 8px;"
        f"font-size:11px;white-space:nowrap'>{icon} {status or 'Not started'}</span>"
    )


def _priority_badge_html(priority: str | None) -> str:
    icon, lbl = _PRIORITY_BADGE.get((priority or "none").lower(), ("⚪", "None"))
    return (
        "<span style='background:#f5f5f5;color:#555;border:1px solid #ddd;border-radius:4px;"
        f"padding:2px 8px;font-size:11px;white-space:nowrap'>{icon} {lbl}</span>"
    )


def _people_pills(owner_email: str | None, sup_email: str | None, user_map: dict) -> str:
    pills = ""
    if owner_email:
        u = user_map.get(owner_email, {"name": owner_email, "avatar_color": "#534AB7"})
        pills += person_pill_html(
            u.get("name", owner_email),
            u.get("avatar_color", "#534AB7"),
            role="owner",
            compact=True,
        )
    if sup_email and sup_email != owner_email:
        u = user_map.get(sup_email, {"name": sup_email, "avatar_color": "#BA7517"})
        pills += person_pill_html(
            u.get("name", sup_email),
            u.get("avatar_color", "#BA7517"),
            role="sup",
            compact=True,
        )
    return pills


def _fetch_dashboard_data(email: str):
    try:
        s_res = supabase.table("settings").select("expiring_threshold_days").limit(1).execute()
        threshold = int(s_res.data[0]["expiring_threshold_days"]) if s_res.data else 7
    except Exception:
        threshold = 7

    proj_res = supabase.table("projects").select("*").eq("is_archived", False).execute()
    projects = {p["id"]: p for p in (proj_res.data or [])}

    d_res = supabase.table("deliverables").select("*").eq("is_archived", False).execute()
    deliverables = {d["id"]: d for d in (d_res.data or [])}

    t_res = supabase.table("tasks").select("*").eq("is_archived", False).execute()
    all_tasks = t_res.data or []
    task_map = {t["id"]: t for t in all_tasks}

    st_res = supabase.table("subtasks").select("*").eq("is_archived", False).execute()
    all_subtasks = st_res.data or []

    u_res = supabase.table("users").select("email, name, avatar_color").eq("is_approved", True).execute()
    user_map = {u["email"]: u for u in (u_res.data or [])}

    # Keep only entities connected to active projects in scope.
    active_project_ids = set(projects.keys())
    all_tasks = [t for t in all_tasks if t.get("project_id") in active_project_ids]
    all_subtasks = [s for s in all_subtasks if task_map.get(s.get("task_id"), {}).get("project_id") in active_project_ids]

    return threshold, projects, deliverables, all_tasks, all_subtasks, task_map, user_map


def _scope_filters(email: str, scope: str, all_tasks: list, all_subtasks: list):
    if scope == "owner":
        selected_tasks = [
            t for t in all_tasks
            if t.get("owner_email") == email and t.get("status") not in _INACTIVE
        ]
        selected_subtasks = [
            s for s in all_subtasks
            if s.get("owner_email") == email and s.get("status") not in _INACTIVE
        ]
    else:
        selected_tasks = [
            t for t in all_tasks
            if t.get("supervisor_email") == email and t.get("status") not in _INACTIVE
        ]
        selected_subtasks = [
            s for s in all_subtasks
            if s.get("supervisor_email") == email and s.get("status") not in _INACTIVE
        ]

    return selected_tasks, selected_subtasks


def _project_min_deadline(selected_tasks: list, selected_subtasks: list) -> datetime.date | None:
    dates = []
    for item in [*selected_tasks, *selected_subtasks]:
        dl = _parse_date(item.get("deadline"))
        if dl:
            dates.append(dl)
    if not dates:
        return None
    return min(dates)


def _build_hierarchy(selected_tasks: list, selected_subtasks: list, task_map: dict):
    selected_task_ids = {t["id"] for t in selected_tasks}

    grouped: dict = {}

    def ensure_task_node(task: dict):
        proj_id = task.get("project_id")
        if not proj_id:
            return None

        project_node = grouped.setdefault(
            proj_id,
            {
                "deliverables": {},
                "generic_tasks": {},
                "task_ids": set(),
                "subtask_ids": set(),
            },
        )

        did = task.get("deliverable_id")
        if did:
            deliverable_node = project_node["deliverables"].setdefault(did, {"tasks": {}})
            task_node = deliverable_node["tasks"].setdefault(
                task["id"], {"task": task, "show_task": False, "subtasks": []}
            )
        else:
            task_node = project_node["generic_tasks"].setdefault(
                task["id"], {"task": task, "show_task": False, "subtasks": []}
            )

        return project_node, task_node

    for t in selected_tasks:
        node_result = ensure_task_node(t)
        if not node_result:
            continue
        project_node, task_node = node_result
        task_node["show_task"] = True
        project_node["task_ids"].add(t["id"])

    for s in selected_subtasks:
        parent_task = task_map.get(s.get("task_id"))
        if not parent_task:
            continue
        node_result = ensure_task_node(parent_task)
        if not node_result:
            continue
        project_node, task_node = node_result
        task_node["subtasks"].append(s)
        project_node["subtask_ids"].add(s["id"])

    return grouped


def _render_item_row(
    *,
    item: dict,
    kind: str,
    threshold: int,
    user_map: dict,
    key_prefix: str,
    indent_px: int,
    can_edit: bool,
    context_only: bool = False,
):
    status = item.get("status", "Not started")
    title = item.get("name", "")
    notes = _truncate_text(item.get("notes"), max_len=150)
    _, dl_html = _deadline_html(item.get("deadline"), threshold)

    status_html = _status_badge_html(status)
    prio_html = _priority_badge_html(item.get("priority")) if kind == "task" else ""
    people_html = _people_pills(item.get("owner_email"), item.get("supervisor_email"), user_map)

    if kind == "task":
        type_chip = "<span style='font-size:10px;background:#E8F0FE;color:#1A73E8;border-radius:3px;padding:1px 7px;'>TASK</span>"
        icon_prefix = ""
    else:
        type_chip = "<span style='font-size:10px;background:#EEF7FF;color:#1565C0;border-radius:3px;padding:1px 7px;'>SUBTASK</span>"
        icon_prefix = "↳ "

    context_chip = (
        "<span style='font-size:10px;background:#f3f3f3;color:#888;border-radius:3px;padding:1px 7px;'>context</span>"
        if context_only
        else ""
    )

    opacity = "0.78" if context_only else "1"

    row_html = f"""
    <div style='margin-left:{indent_px}px;border-left:2px solid #EFEFEF;padding:4px 0 4px 10px;opacity:{opacity};'>
      <div style='display:flex;align-items:center;gap:7px;flex-wrap:wrap;'>
        {type_chip}
        {context_chip}
        <span style='font-size:13px;font-weight:{'450' if kind == 'subtask' else '550'};line-height:1.25;'>
          {icon_prefix}{title}
        </span>
        {status_html}
        {prio_html}
        <span style='margin-left:auto;white-space:nowrap'>{dl_html}</span>
      </div>
      <div style='display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:3px;'>
        <span style='font-size:11px;color:#777;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>
          {notes or '—'}
        </span>
        <span style='white-space:nowrap'>{people_html or "<span style='font-size:11px;color:#999;'>Owner/Sup: —</span>"}</span>
      </div>
    </div>
    """

    col_item, col_btn = st.columns([8.4, 1.6])
    with col_item:
        st.html(row_html)
    with col_btn:
        if st.button("Details", key=f"{key_prefix}_{kind}_{item['id']}", use_container_width=True):
            if kind == "task":
                task_details_modal(item, can_edit=can_edit)
            else:
                subtask_details_modal(item, can_edit=can_edit)


def _sort_task_nodes(task_nodes: list):
    def task_node_key(node):
        task = node["task"]
        prio = PRIORITY_ORDER.get((task.get("priority") or "none").lower(), 4)
        return (_deadline_sort_key(task.get("deadline")), prio, task.get("name") or "")

    return sorted(task_nodes, key=task_node_key)


def _render_project_header(project: dict):
    st.html(
        f"<div style='display:flex;align-items:center;gap:10px;margin:2px 0 6px 0'>"
        f"<span style='width:16px;height:16px;background:#F59E0B;border-radius:4px;display:inline-block'></span>"
        f"<span style='font-size:1.15rem;font-weight:700'>{project.get('name','Project')} ({project.get('acronym','')})</span>"
        f"</div>"
    )


def _render_deliverable_block(
    deliverable: dict,
    project: dict,
    task_nodes: list,
    threshold: int,
    user_map: dict,
    email: str,
    tab_key: str,
    settings: dict,
):
    with st.container(border=True):
        d_deadline = deliverable.get("deadline") or "—"
        type_chip = deliverable_chip_html(deliverable.get("type") or "generic", settings)
        st.html(
            f"<div style='background:#E6F7F3;border-radius:6px;padding:6px 10px;margin-bottom:6px;'>"
            f"<span style='color: green; font-weight: bold;'>DELIVERABLE</span> "
            f"<span style='font-size:13px;font-weight:700;color:#0F5943;'>{deliverable.get('name','')}</span>"
            f"<span style='font-size:11px;color:#2E8B6E;'> · {type_chip} · deadline {d_deadline}</span>"
            f"<span style='float:right;font-size:11px;color:#2E8B6E'>{project.get('acronym') or project.get('name','')}</span>"
            f"</div>"
        )

        for task_node in _sort_task_nodes(task_nodes):
            task = task_node["task"]
            task_direct = task_node["show_task"]
            task_can_edit = task.get("owner_email") == email or task.get("supervisor_email") == email

            _render_item_row(
                item=task,
                kind="task",
                threshold=threshold,
                user_map=user_map,
                key_prefix=f"{tab_key}_t",
                indent_px=0,
                can_edit=task_can_edit,
                context_only=not task_direct,
            )

            for sub in sorted(task_node["subtasks"], key=lambda s: (_deadline_sort_key(s.get("deadline")), s.get("name") or "")):
                sub_can_edit = sub.get("owner_email") == email or sub.get("supervisor_email") == email
                _render_item_row(
                    item=sub,
                    kind="subtask",
                    threshold=threshold,
                    user_map=user_map,
                    key_prefix=f"{tab_key}_s",
                    indent_px=18,
                    can_edit=sub_can_edit,
                    context_only=False,
                )


def _render_scope_tab(
    scope_label: str,
    email: str,
    threshold: int,
    projects: dict,
    deliverables: dict,
    selected_tasks: list,
    selected_subtasks: list,
    task_map: dict,
    user_map: dict,
    settings: dict,
):
    hierarchy = _build_hierarchy(selected_tasks, selected_subtasks, task_map)
    if not hierarchy:
        st.info("No active items for this view. ✅")
        return

    project_priority = []
    for proj_id, proj_node in hierarchy.items():
        proj_tasks = [t for t in selected_tasks if t.get("project_id") == proj_id]
        proj_subtasks = []
        for s in selected_subtasks:
            p_task = task_map.get(s.get("task_id"))
            if p_task and p_task.get("project_id") == proj_id:
                proj_subtasks.append(s)
        min_dl = _project_min_deadline(proj_tasks, proj_subtasks)
        project_priority.append((min_dl or datetime.date(9999, 12, 31), projects.get(proj_id, {}).get("name") or "", proj_id, proj_node))

    project_priority.sort(key=lambda row: (row[0], row[1]))

    for idx, (_, _, proj_id, proj_node) in enumerate(project_priority):
        project = projects.get(proj_id)
        if not project:
            continue

        with st.expander(f"📁 {project.get('name','Project')} ({project.get('acronym','')})", expanded=(idx == 0)):
            _render_project_header(project)

            deliverable_nodes = []
            for did, d_node in proj_node["deliverables"].items():
                d = deliverables.get(did)
                if not d:
                    continue
                nearest_deadline = _deadline_sort_key(d.get("deadline"))
                deliverable_nodes.append((nearest_deadline, d.get("name") or "", d, list(d_node["tasks"].values())))

            deliverable_nodes.sort(key=lambda row: (row[0], row[1]))

            for _, _, deliverable, task_nodes in deliverable_nodes:
                st.markdown("<div class='deliverable-box'>", unsafe_allow_html=True)
                _render_deliverable_block(
                    deliverable,
                    project,
                    task_nodes,
                    threshold,
                    user_map,
                    email,
                    scope_label,
                    settings,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            generic_nodes = list(proj_node["generic_tasks"].values())
            if generic_nodes:
                st.html(
                    "<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;color:#666;'>"
                    "GENERIC TASKS (NO DELIVERABLE)</span>"
                )
                with st.container(border=True):
                    for task_node in _sort_task_nodes(generic_nodes):
                        task = task_node["task"]
                        task_direct = task_node["show_task"]
                        task_can_edit = task.get("owner_email") == email or task.get("supervisor_email") == email
                        _render_item_row(
                            item=task,
                            kind="task",
                            threshold=threshold,
                            user_map=user_map,
                            key_prefix=f"{scope_label}_gt",
                            indent_px=0,
                            can_edit=task_can_edit,
                            context_only=not task_direct,
                        )
                        for sub in sorted(task_node["subtasks"], key=lambda s: (_deadline_sort_key(s.get("deadline")), s.get("name") or "")):
                            sub_can_edit = sub.get("owner_email") == email or sub.get("supervisor_email") == email
                            _render_item_row(
                                item=sub,
                                kind="subtask",
                                threshold=threshold,
                                user_map=user_map,
                                key_prefix=f"{scope_label}_gs",
                                indent_px=18,
                                can_edit=sub_can_edit,
                                context_only=False,
                            )


def show_dashboard():
    st.title("Dashboard")
    st.markdown("**Most urgent tasks to work on**")

    st.markdown(
        """
        <style>
        div[data-testid='stButton'] > button {
            min-height: 1.75rem;
            padding: 0.15rem 0.5rem;
            font-size: 0.78rem;
        }
        div[data-testid='stHorizontalBlock'] {
            padding-top: 2px !important;
            padding-bottom: 2px !important;
        }
        .deliverable-box [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid #9FD9C8 !important;
            border-radius: 0.5rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    email = st.session_state.get("user_email")
    if not email:
        st.error("User not found in session.")
        return

    try:
        threshold, projects, deliverables, all_tasks, all_subtasks, task_map, user_map = _fetch_dashboard_data(email)
    except Exception as e:
        st.error(f"Error while loading dashboard data: {e}")
        return

    my_tasks, my_subtasks = _scope_filters(email, "owner", all_tasks, all_subtasks)
    supervised_tasks, supervised_subtasks = _scope_filters(email, "supervisor", all_tasks, all_subtasks)

    my_count = len(my_tasks) + len(my_subtasks)
    supervised_count = len(supervised_tasks) + len(supervised_subtasks)

    tab_my, tab_supervised = st.tabs([
        f"My Tasks ({my_count})",
        f"Supervised Tasks ({supervised_count})",
    ])
    settings = get_settings()

    with tab_my:
        _render_scope_tab(
            scope_label="my",
            email=email,
            threshold=threshold,
            projects=projects,
            deliverables=deliverables,
            selected_tasks=my_tasks,
            selected_subtasks=my_subtasks,
            task_map=task_map,
            user_map=user_map,
            settings=settings,
        )

    with tab_supervised:
        st.caption("Tasks and subtasks where you are supervisor.")
        _render_scope_tab(
            scope_label="sup",
            email=email,
            threshold=threshold,
            projects=projects,
            deliverables=deliverables,
            selected_tasks=supervised_tasks,
            selected_subtasks=supervised_subtasks,
            task_map=task_map,
            user_map=user_map,
            settings=settings,
        )
