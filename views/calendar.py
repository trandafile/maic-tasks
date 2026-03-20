import datetime
import streamlit as st
from streamlit_calendar import calendar

from core.supabase_client import supabase
from db import get_settings
from utils.helpers import get_deliverable_tag_color


_EVENT_COLOUR = {
    "deliverable": "#8E24AA",
    "task": "#1565C0",
    "subtask": "#EF6C00",
}


def _iso_to_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except Exception:
        return None


def _fmt_date(value: str | None) -> str:
    d = _iso_to_date(value)
    return d.strftime("%Y/%m/%d") if d else "-"


def _safe_ics_text(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _build_ics(events: list[dict]) -> bytes:
    now = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MAIC LAB//Task Manager//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for ev in events:
        start = ev.get("start")
        if not start:
            continue
        uid = f"{ev.get('id', 'event')}@maic-lab"
        title = _safe_ics_text(ev.get("title", "Task"))
        desc = _safe_ics_text(ev.get("extendedProps", {}).get("description", ""))
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now}",
                f"DTSTART;VALUE=DATE:{start.replace('-', '')}",
                f"SUMMARY:{title}",
                f"DESCRIPTION:{desc}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")


def _fetch_calendar_data():
    try:
        projects = (
            supabase.table("projects")
            .select("id, name, acronym")
            .eq("is_archived", False)
            .order("name")
            .execute()
            .data
            or []
        )
        users = (
            supabase.table("users")
            .select("email, name")
            .eq("is_approved", True)
            .order("name")
            .execute()
            .data
            or []
        )
        deliverables = (
            supabase.table("deliverables")
            .select("id, project_id, name, type, deadline, status, owner_email, supervisor_email, is_archived")
            .eq("is_archived", False)
            .execute()
            .data
            or []
        )
        tasks = (
            supabase.table("tasks")
            .select("id, sequence_id, project_id, deliverable_id, name, owner_email, supervisor_email, deadline, status, is_archived")
            .eq("is_archived", False)
            .execute()
            .data
            or []
        )
        subtasks = (
            supabase.table("subtasks")
            .select("id, task_id, name, owner_email, supervisor_email, deadline, status, is_archived")
            .eq("is_archived", False)
            .execute()
            .data
            or []
        )
        return projects, users, deliverables, tasks, subtasks
    except Exception as e:
        st.error(f"Error loading calendar data: {e}")
        return [], [], [], [], []


def show_calendar():
    st.title("Calendar")

    user_role = st.session_state.get("user_role")
    user_email = st.session_state.get("user_email")
    is_admin = user_role == "admin"
    settings = get_settings()

    projects, users, deliverables, tasks, subtasks = _fetch_calendar_data()
    if not projects:
        st.info("No projects available.")
        return

    project_map = {"All projects": None}
    project_map.update(
        {f"{p.get('name')} ({p.get('acronym') or p.get('name')})": p.get("id") for p in projects}
    )

    user_map = {"All people": None}
    user_map.update({u.get("name", u.get("email")): u.get("email") for u in users})

    admin_scope = "all"
    if is_admin:
        admin_scope = st.radio(
            "Admin view",
            options=["all", "personal"],
            format_func=lambda v: "All items" if v == "all" else "Personal items only",
            horizontal=True,
            key="cal_admin_scope",
        )

    f1, f2 = st.columns([2, 2])
    with f1:
        sel_project_label = st.selectbox("Project", list(project_map.keys()), key="cal_project")
        sel_project = project_map[sel_project_label]
    with f2:
        if is_admin:
            if admin_scope == "all":
                sel_user_label = st.selectbox("Person (owner or supervisor)", list(user_map.keys()), key="cal_user")
                sel_user = user_map[sel_user_label]
            else:
                sel_user = user_email
                user_name = next((u.get("name") for u in users if u.get("email") == user_email), user_email)
                st.caption(f"Person: {user_name or user_email}")
        else:
            sel_user = user_email
            user_name = next((u.get("name") for u in users if u.get("email") == user_email), user_email)
            st.caption(f"Person: {user_name or user_email}")

    all_tags = sorted(
        {
            ((d.get("type") or "generic").strip() or "generic")
            for d in deliverables
        }
    )

    f3, f4 = st.columns([2, 2])
    with f3:
        event_scope = st.radio(
            "Event scope",
            options=["all", "deliverables_only", "tasks_only"],
            format_func=lambda v: {
                "all": "All events",
                "deliverables_only": "Deliverables only",
                "tasks_only": "Tasks & Subtasks only",
            }[v],
            horizontal=True,
            key="cal_event_scope",
        )
    with f4:
        sel_tags = st.multiselect(
            "Deliverable tags",
            options=all_tags,
            default=[],
            key="cal_deliverable_tags",
            help="Leave empty to show all tags.",
        )

    proj_by_id = {p.get("id"): p for p in projects}
    users_by_email = {u.get("email"): u.get("name", u.get("email")) for u in users}
    events: list[dict] = []

    show_deliverables = event_scope in ("all", "deliverables_only")
    show_tasks = event_scope in ("all", "tasks_only")

    task_map = {t.get("id"): t for t in tasks}

    # Deliverables events (if enabled)
    if show_deliverables:
        for d in deliverables:
            dl = d.get("deadline")
            if not dl:
                continue
            d_tag = (d.get("type") or "generic").strip() or "generic"
            if sel_tags and d_tag not in sel_tags:
                continue
            if sel_project is not None and d.get("project_id") != sel_project:
                continue
            if not is_admin:
                if user_email not in (d.get("owner_email"), d.get("supervisor_email")):
                    continue
            elif admin_scope == "personal":
                if user_email not in (d.get("owner_email"), d.get("supervisor_email")):
                    continue
            if sel_user is not None and sel_user not in (
                d.get("owner_email"),
                d.get("supervisor_email"),
            ):
                continue
            proj = proj_by_id.get(d.get("project_id"), {})
            status = d.get("status", "Not started")
            status_color = {
                "Completed": "#2E7D32",
                "Working on": "#1565C0",
                "Blocked": "#E65100",
                "Cancelled": "#B71C1C",
            }.get(status, get_deliverable_tag_color(d_tag, settings))
            owner_e = d.get("owner_email")
            sup_e = d.get("supervisor_email")
            events.append(
                {
                    "id": f"d_{d.get('id')}",
                    "title": f"[Deliverable] {d.get('name')} ({d_tag})",
                    "start": dl,
                    "allDay": True,
                    "color": status_color,
                    "extendedProps": {
                        "kind": "deliverable",
                        "tag": d_tag,
                        "project": proj.get("name", "-"),
                        "status": status,
                        "owner_email": owner_e,
                        "supervisor_email": sup_e,
                        "description": f"Deliverable: {d.get('name')} | Tag: {d_tag} | Project: {proj.get('name', '-')}",
                    },
                }
            )

    # Tasks and subtasks events (if enabled)
    if show_tasks:
        for t in tasks:
            dl = t.get("deadline")
            if not dl:
                continue
            if sel_project is not None and t.get("project_id") != sel_project:
                continue
            if not is_admin:
                if user_email not in (t.get("owner_email"), t.get("supervisor_email")):
                    continue
            elif admin_scope == "personal":
                if user_email not in (t.get("owner_email"), t.get("supervisor_email")):
                    continue
            if sel_user is not None and sel_user not in (
                t.get("owner_email"),
                t.get("supervisor_email"),
            ):
                continue
            proj = proj_by_id.get(t.get("project_id"), {})
            seq = t.get("sequence_id") or f"T-{t.get('id')}"
            events.append(
                {
                    "id": f"t_{t.get('id')}",
                    "title": f"[Task] {seq} - {t.get('name')}",
                    "start": dl,
                    "allDay": True,
                    "color": _EVENT_COLOUR["task"],
                    "extendedProps": {
                        "kind": "task",
                        "project": proj.get("name", "-"),
                        "status": t.get("status", "Not started"),
                        "owner_email": t.get("owner_email"),
                        "supervisor_email": t.get("supervisor_email"),
                        "description": f"Task: {seq} - {t.get('name')} | Project: {proj.get('name', '-')}",
                    },
                }
            )

        for s in subtasks:
            dl = s.get("deadline")
            if not dl:
                continue
            parent = task_map.get(s.get("task_id"), {})
            pid = parent.get("project_id")
            if sel_project is not None and pid != sel_project:
                continue
            if not is_admin:
                if user_email not in (s.get("owner_email"), s.get("supervisor_email")):
                    continue
            elif admin_scope == "personal":
                if user_email not in (s.get("owner_email"), s.get("supervisor_email")):
                    continue
            if sel_user is not None and sel_user not in (
                s.get("owner_email"),
                s.get("supervisor_email"),
            ):
                continue
            proj = proj_by_id.get(pid, {})
            pseq = parent.get("sequence_id") or f"T-{parent.get('id', '?')}"
            events.append(
                {
                    "id": f"s_{s.get('id')}",
                    "title": f"[Subtask] {s.get('name')}",
                    "start": dl,
                    "allDay": True,
                    "color": _EVENT_COLOUR["subtask"],
                    "extendedProps": {
                        "kind": "subtask",
                        "project": proj.get("name", "-"),
                        "status": s.get("status", "Not started"),
                        "owner_email": s.get("owner_email"),
                        "supervisor_email": s.get("supervisor_email"),
                        "description": f"Subtask: {s.get('name')} | Parent task: {pseq} | Project: {proj.get('name', '-')}",
                    },
                }
            )

    events.sort(key=lambda e: e.get("start") or "9999-12-31")

    ics_data = _build_ics(events)
    st.download_button(
        "Export .ics",
        data=ics_data,
        file_name=f"maic_calendar_{datetime.date.today().strftime('%Y%m%d')}.ics",
        mime="text/calendar",
        use_container_width=False,
    )

    cal_opts = {
        "initialView": "dayGridMonth",
        "height": 760,
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek,multiMonthYear",
        },
    }
    selected = calendar(events=events, options=cal_opts, key="maic_calendar_unified")

    st.caption(f"Visible events: {len(events)}")

    # ── Long-scale text timeline ───────────────────────────────────────────────
    st.subheader("Long-scale Timeline")
    # Build normalized items directly from events to avoid state issues
    timeline_items: list[dict] = []
    for ev in events:
        start = ev.get("start")
        if not start:
            continue
        try:
            d = datetime.date.fromisoformat(start)
        except Exception:
            continue
        ext = ev.get("extendedProps", {}) or {}
        proj_name = ext.get("project", "-")
        kind = ext.get("kind", "")
        title = ev.get("title") or ""
        owner_e = ext.get("owner_email")
        sup_e = ext.get("supervisor_email")
        owner_name = users_by_email.get(owner_e, owner_e) if owner_e else "—"
        sup_name = users_by_email.get(sup_e, sup_e) if sup_e else "—"
        timeline_items.append(
            {
                "date": d,
                "project": proj_name,
                "kind": kind,
                "title": title,
                "owner": owner_name or "—",
                "sup": sup_name or "—",
            }
        )

    timeline_by_month: dict[tuple[int, int], list[dict]] = {}
    for item in timeline_items:
        d = item["date"]
        key = (d.year, d.month)
        timeline_by_month.setdefault(key, []).append(item)

    md_lines: list[str] = []

    for (year, month) in sorted(timeline_by_month.keys()):
        month_name = datetime.date(year, month, 1).strftime("%B %Y")
        st.markdown(f"### {month_name}")
        md_lines.append(f"### {month_name}")

        def _kind_order(k: str) -> int:
            return {"deliverable": 0, "task": 1, "subtask": 2}.get(k, 3)

        month_items = sorted(
            timeline_by_month[(year, month)],
            key=lambda x: (x["date"], _kind_order(x["kind"])),
        )

        open_block = False
        for item in month_items:
            name = item["title"]
            if name.startswith("["):
                try:
                    name = name.split("]", 1)[1].strip()
                except Exception:
                    pass

            is_deliv = item["kind"] == "deliverable"

            if is_deliv:
                if open_block:
                    st.markdown("---")
                    md_lines.append("---")
                st.markdown("---")
                md_lines.append("---")
                line = (
                    f"**Deliverable: {item['project']} - {name}** - Due on {item['date'].isoformat()}"
                )
                meta = f"Owner: {item['owner']} | Supervisor: {item['sup']}"
                st.markdown(line + "\n" + meta)
                md_lines.append(line)
                md_lines.append(meta)
                open_block = True
            else:
                line = (
                    f"&nbsp;&nbsp;**{item['project']} - {name}** - Due on {item['date'].isoformat()}"
                )
                meta = f"&nbsp;&nbsp;Owner: {item['owner']} | Supervisor: {item['sup']}"
                st.markdown(line + "\n" + meta)
                md_lines.append(
                    f"  **{item['project']} - {name}** - Due on {item['date'].isoformat()}"
                )
                md_lines.append(
                    f"  Owner: {item['owner']} | Supervisor: {item['sup']}"
                )

        if open_block:
            st.markdown("---")
            md_lines.append("---")

    if md_lines:
        md_content = "\n".join(md_lines)
        st.download_button(
            "⬇️ Export Timeline (Markdown)",
            data=md_content,
            file_name=f"timeline_{datetime.date.today().strftime('%Y%m%d')}.md",
            mime="text/markdown",
            key="timeline_md_export",
        )

    clicked = (selected or {}).get("eventClick")
    if clicked:
        ext = clicked.get("event", {}).get("extendedProps", {})
        st.info(
            f"{clicked.get('event', {}).get('title', '')}\n"
            f"Type: {ext.get('kind', '-')} | Status: {ext.get('status', '-')} | Project: {ext.get('project', '-')}"
        )
        st.caption(ext.get("description", ""))
