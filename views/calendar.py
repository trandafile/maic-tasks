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
            .select("id, project_id, name, deadline, status, is_archived")
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

    mode = st.radio(
        "Calendar mode",
        ["Tasks Calendar", "Deliverables Calendar"],
        horizontal=True,
        key="cal_mode",
    )

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
    events = []

    if mode == "Deliverables Calendar":
        # Annual multi-month view of deliverable deadlines only
        for d in deliverables:
            dl = d.get("deadline")
            if not dl:
                continue
            if sel_project is not None and d.get("project_id") != sel_project:
                continue
            proj = proj_by_id.get(d.get("project_id"), {})
            status = d.get("status", "Not started")
            # Simple status-based colour coding
            status_color = {
                "Completed": "#2E7D32",
                "Working on": "#1565C0",
                "Blocked": "#E65100",
                "Cancelled": "#B71C1C",
            }.get(status, _EVENT_COLOUR["deliverable"])
            events.append(
                {
                    "id": f"d_{d.get('id')}",
                    "title": f"{d.get('name')}",
                    "start": dl,
                    "allDay": True,
                    "color": status_color,
                    "extendedProps": {
                        "kind": "deliverable",
                        "project": proj.get("name", "-"),
                        "status": status,
                        "description": f"Deliverable: {d.get('name')} | Project: {proj.get('name', '-')}",
                    },
                }
            )

        events.sort(key=lambda e: e.get("start") or "9999-12-31")
        ics_data = _build_ics(events)
        st.download_button(
            "Export .ics",
            data=ics_data,
            file_name=f"maic_deliverables_calendar_{datetime.date.today().strftime('%Y%m%d')}.ics",
            mime="text/calendar",
            use_container_width=False,
        )

        cal_opts = {
            "initialView": "multiMonthYear",
            "height": 760,
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "",
            },
        }
        selected = calendar(events=events, options=cal_opts, key="maic_calendar_deliverables")
    else:
        # Existing tasks/subtasks calendar (optionally showing deliverables)
        show_deliverables = st.toggle("Show deliverables", value=True, key="cal_show_deliv")

        task_map = {t.get("id"): t for t in tasks}

        if show_deliverables and sel_user is None:
            for d in deliverables:
                dl = d.get("deadline")
                if not dl:
                    continue
                if sel_project is not None and d.get("project_id") != sel_project:
                    continue
                proj = proj_by_id.get(d.get("project_id"), {})
                events.append(
                    {
                        "id": f"d_{d.get('id')}",
                        "title": f"[Deliverable] {d.get('name')}",
                        "start": dl,
                        "allDay": True,
                        "color": _EVENT_COLOUR["deliverable"],
                        "extendedProps": {
                            "kind": "deliverable",
                            "project": proj.get("name", "-"),
                            "status": d.get("status", "Not started"),
                            "description": f"Deliverable: {d.get('name')} | Project: {proj.get('name', '-')}",
                        },
                    }
                )

        for t in tasks:
            dl = t.get("deadline")
            if not dl:
                continue
            if sel_project is not None and t.get("project_id") != sel_project:
                continue
            if sel_user is not None and sel_user not in (t.get("owner_email"), t.get("supervisor_email")):
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
            if sel_user is not None and sel_user not in (s.get("owner_email"), s.get("supervisor_email")):
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
                "right": "dayGridMonth,timeGridWeek,listWeek",
            },
        }
        selected = calendar(events=events, options=cal_opts, key="maic_calendar_tasks")

    st.caption(f"Visible events: {len(events)}")

    clicked = (selected or {}).get("eventClick")
    if clicked:
        ext = clicked.get("event", {}).get("extendedProps", {})
        st.info(
            f"{clicked.get('event', {}).get('title', '')}\n"
            f"Type: {ext.get('kind', '-')} | Status: {ext.get('status', '-')} | Project: {ext.get('project', '-')}"
        )
        st.caption(ext.get("description", ""))
