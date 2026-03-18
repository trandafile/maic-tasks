import datetime
import streamlit as st
from streamlit_calendar import calendar

from core.supabase_client import supabase


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
            .select("id, project_id, name, deadline, status, owner_email, supervisor_email, is_archived")
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

    f1, f2 = st.columns([2, 2])
    with f1:
        sel_project_label = st.selectbox("Project", list(project_map.keys()), key="cal_project")
        sel_project = project_map[sel_project_label]
    with f2:
        sel_user_label = st.selectbox("Person (owner or supervisor)", list(user_map.keys()), key="cal_user")
        sel_user = user_map[sel_user_label]

    proj_by_id = {p.get("id"): p for p in projects}
    users_by_email = {u.get("email"): u.get("name", u.get("email")) for u in users}
    events: list[dict] = []

    # Independent toggles
    c_tasks, c_delivs = st.columns(2)
    with c_tasks:
        show_tasks = st.checkbox("Show Tasks & Subtasks", value=True, key="cal_show_tasks")
    with c_delivs:
        show_deliverables = st.checkbox("Show Deliverables", value=True, key="cal_show_deliverables")

    task_map = {t.get("id"): t for t in tasks}

    # Deliverables events (if enabled)
    if show_deliverables:
        for d in deliverables:
            dl = d.get("deadline")
            if not dl:
                continue
            if sel_project is not None and d.get("project_id") != sel_project:
                continue
            proj = proj_by_id.get(d.get("project_id"), {})
            status = d.get("status", "Not started")
            status_color = {
                "Completed": "#2E7D32",
                "Working on": "#1565C0",
                "Blocked": "#E65100",
                "Cancelled": "#B71C1C",
            }.get(status, _EVENT_COLOUR["deliverable"])
            owner_e = d.get("owner_email")
            sup_e = d.get("supervisor_email")
            events.append(
                {
                    "id": f"d_{d.get('id')}",
                    "title": f"[Deliverable] {d.get('name')}",
                    "start": dl,
                    "allDay": True,
                    "color": status_color,
                    "extendedProps": {
                        "kind": "deliverable",
                        "project": proj.get("name", "-"),
                        "status": status,
                        "owner_email": owner_e,
                        "supervisor_email": sup_e,
                        "description": f"Deliverable: {d.get('name')} | Project: {proj.get('name', '-')}",
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
    timeline: dict[tuple[int, int], list[dict]] = {}
    for ev in events:
        start = ev.get("start")
        if not start:
            continue
        try:
            d = datetime.date.fromisoformat(start)
        except Exception:
            continue
        key = (d.year, d.month)
        ext = ev.get("extendedProps", {}) or {}
        proj_name = ext.get("project", "-")
        kind = ext.get("kind", "")
        title = ev.get("title") or ""
        owner_e = ext.get("owner_email")
        sup_e = ext.get("supervisor_email")
        owner_name = users_by_email.get(owner_e, owner_e) if owner_e else "—"
        sup_name = users_by_email.get(sup_e, sup_e) if sup_e else "—"
        timeline.setdefault(key, []).append(
            {
                "date": d,
                "project": proj_name,
                "kind": kind,
                "title": title,
                "owner": owner_name or "—",
                "sup": sup_name or "—",
            }
        )

    for (year, month) in sorted(timeline.keys()):
        month_name = datetime.date(year, month, 1).strftime("%B %Y")
        st.markdown(f"### {month_name}")
        for item in sorted(timeline[(year, month)], key=lambda x: x["date"]):
            # Strip leading tag like "[Deliverable]" or "[Task]" from title for readability
            name = item["title"]
            if name.startswith("["):
                try:
                    name = name.split("]", 1)[1].strip()
                except Exception:
                    pass
            st.markdown(
                f"**{item['project']} - {name}** - Due on {item['date'].isoformat()}\n"
                f"Owner: {item['owner']} | Supervisor: {item['sup']}"
            )

    clicked = (selected or {}).get("eventClick")
    if clicked:
        ext = clicked.get("event", {}).get("extendedProps", {})
        st.info(
            f"{clicked.get('event', {}).get('title', '')}\n"
            f"Type: {ext.get('kind', '-')} | Status: {ext.get('status', '-')} | Project: {ext.get('project', '-')}"
        )
        st.caption(ext.get("description", ""))
