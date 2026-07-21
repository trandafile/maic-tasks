"""views/dashboard.py — "What needs my attention now".

Deliberately NOT a project tree (that is the Projects page). The dashboard is
urgency-first and flat:

* **My work** — my own tasks/subtasks bucketed by urgency
  (overdue → blocked → due soon → in progress → later). The project is a small
  chip on the row, never a folder to open.
* **Supervision** — for supervisors, who typically watch far more items than
  they execute: first "needs your attention" (blocked + overdue across
  everyone), then one card per person so you can see who is stuck.
"""

import datetime
import html as _htmllib

import streamlit as st

from core.supabase_client import supabase
from db import (
    get_settings, compute_delay_stats, get_conference_paper_tasks, get_comment_counts,
    get_pending_timesheets, days_since_update, stale_threshold,
)
from utils.helpers import (
    PRIORITY_ORDER, strip_markdown, sort_tasks_by_deadline, comment_badge_html,
    TASK_NAME_STYLE, SUBTASK_NAME_STYLE, SUBTASK_PREFIX, stable_colour,
)
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

# Buckets, in the order they are shown. A task lands in the FIRST one it matches,
# so nothing is ever listed twice.
_BUCKETS = [
    ("overdue",     "🔴 Overdue",        "#C62828", "#FDECEC"),
    ("blocked",     "🚫 Blocked",        "#D93025", "#FDEDEC"),
    ("due_soon",    "🟠 Due soon",       "#E65100", "#FFF4E5"),
    ("in_progress", "🔵 In progress",    "#1565C0", "#E8F1FC"),
    ("later",       "⚪ Later",           "#5F6368", "#F1F3F4"),
]
_BUCKET_META = {k: (label, fg, bg) for k, label, fg, bg in _BUCKETS}

# Colours come from utils.helpers.stable_colour so the app and the notification
# emails always agree on a project's colour.


# ─── small helpers ────────────────────────────────────────────────────────────

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _esc(v) -> str:
    return _htmllib.escape(str(v or ""))


def _proj_chip(label: str) -> str:
    if not label:
        return ""
    c = stable_colour(label)
    return (
        f"<span style='background:{c};color:#fff;border-radius:4px;padding:1px 7px;"
        f"font-size:10px;font-weight:700;white-space:nowrap'>{_esc(label)}</span>"
    )


def _status_badge_html(status: str) -> str:
    icon, color = _STATUS_BADGE.get(status or "Not started", ("⚪", "#888888"))
    return (
        f"<span style='background:{color}22;color:{color};border-radius:4px;padding:1px 8px;"
        f"font-size:11px;white-space:nowrap'>{icon} {_esc(status or 'Not started')}</span>"
    )


def _priority_badge_html(priority) -> str:
    icon, lbl = _PRIORITY_BADGE.get((priority or "none").lower(), ("⚪", "None"))
    if lbl == "None":
        return ""
    return (
        "<span style='background:#f5f5f5;color:#555;border:1px solid #ddd;border-radius:4px;"
        f"padding:1px 7px;font-size:11px;white-space:nowrap'>{icon} {lbl}</span>"
    )


def _deadline_html(deadline, threshold: int) -> str:
    dl = _parse_date(deadline)
    if not dl:
        return "<span style='font-size:11px;color:#aaa;'>no deadline</span>"
    delta = (dl - datetime.date.today()).days
    label = dl.strftime("%Y/%m/%d")
    if delta < 0:
        return (
            f"<span style='font-size:11px;color:#C62828;font-weight:700;'>📅 {label}</span>"
            f" <span style='font-size:10px;background:#FDECEC;color:#A32020;padding:1px 6px;"
            f"border-radius:3px;font-weight:700'>overdue {abs(delta)}d</span>"
        )
    if delta <= threshold:
        lbl = "today" if delta == 0 else f"in {delta}d"
        return (
            f"<span style='font-size:11px;color:#B26A00;font-weight:700;'>📅 {label}</span>"
            f" <span style='font-size:10px;background:#FFF4E5;color:#8A4B00;padding:1px 6px;"
            f"border-radius:3px;font-weight:700'>{lbl}</span>"
        )
    return f"<span style='font-size:11px;color:#666;'>📅 {label}</span>"


def _stale_badge(item: dict, threshold: int) -> str:
    """'Fermo da N giorni' — the signal that actually works on long tasks,
    where a far-off deadline says nothing for months. Silent when the
    freshness migration has not been run yet."""
    d = days_since_update(item)
    if d is None or d < threshold:
        return ""
    fg, bg = ("#B80D48", "#FBE7EE") if d >= threshold * 2 else ("#B26A00", "#FFF4E5")
    return (f"<span style='background:{bg};color:{fg};border-radius:4px;padding:1px 7px;"
            f"font-size:11px;font-weight:700;white-space:nowrap'>⏳ fermo {d}g</span>")


def _people_pills(owner_email, sup_email, user_map: dict) -> str:
    pills = ""
    if owner_email:
        u = user_map.get(owner_email, {"name": owner_email, "avatar_color": "#534AB7"})
        pills += person_pill_html(u.get("name", owner_email), u.get("avatar_color", "#534AB7"),
                                  role="owner", compact=True)
    if sup_email and sup_email != owner_email:
        u = user_map.get(sup_email, {"name": sup_email, "avatar_color": "#BA7517"})
        pills += person_pill_html(u.get("name", sup_email), u.get("avatar_color", "#BA7517"),
                                  role="sup", compact=True)
    return pills


def _truncate(value, max_len: int = 110) -> str:
    txt = strip_markdown(value or "").strip()
    if len(txt) <= max_len:
        return txt
    return f"{txt[:max_len - 1].rstrip()}…"


# ─── bucketing ────────────────────────────────────────────────────────────────

def _bucket_of(item: dict, threshold: int, today: datetime.date) -> str:
    """First match wins, so an item is never counted in two buckets.

    Overdue outranks blocked: a blocked task that is also late is first of all
    late. The Blocked badge still shows on the row.
    """
    status = item.get("status") or "Not started"
    dl = _parse_date(item.get("deadline"))
    if dl and dl < today:
        return "overdue"
    if status == "Blocked":
        return "blocked"
    if dl and (dl - today).days <= threshold:
        return "due_soon"
    if status == "Working on":
        return "in_progress"
    return "later"


def _sort_key(item: dict):
    """Overdue-first, then soonest deadline, then priority."""
    dl = _parse_date(item.get("deadline")) or datetime.date(9999, 12, 31)
    prio = PRIORITY_ORDER.get((item.get("priority") or "none").lower(), 4)
    return (dl, prio, (item.get("name") or "").lower())


# ─── row rendering ────────────────────────────────────────────────────────────

def _render_row(item: dict, *, kind: str, ctx: dict, key_prefix: str,
                show_people: bool = True):
    """One flat, self-contained row. The project is a chip — never a folder."""
    threshold = ctx["threshold"]
    user_map = ctx["user_map"]
    projects = ctx["projects"]
    task_map = ctx["task_map"]
    email = ctx["email"]
    is_admin = ctx["is_admin"]

    if kind == "task":
        proj = projects.get(item.get("project_id"), {})
        parent_note = ""
        name_style = TASK_NAME_STYLE
        prefix = ""
        cc = ctx["comment_counts"].get(item.get("id"), 0)
    else:
        parent = task_map.get(item.get("task_id"), {})
        proj = projects.get(parent.get("project_id"), {})
        pname = parent.get("name") or ""
        parent_note = (
            f"<span style='font-size:11px;color:#999'>in: {_esc(pname)}</span>"
            if pname else ""
        )
        name_style = SUBTASK_NAME_STYLE
        prefix = f"{SUBTASK_PREFIX} "
        cc = 0  # comments live on tasks

    proj_label = proj.get("acronym") or proj.get("identifier") or proj.get("name") or ""
    can_edit = (
        is_admin
        or item.get("owner_email") == email
        or item.get("supervisor_email") == email
    )

    notes = _truncate(item.get("notes"))
    people = _people_pills(item.get("owner_email"), item.get("supervisor_email"), user_map) if show_people else ""

    col_main, col_btn = st.columns([8.6, 1.4])
    with col_main:
        st.html(
            f"<div style='padding:6px 4px;'>"
            f"  <div style='display:flex;align-items:center;gap:7px;flex-wrap:wrap;'>"
            f"    {_proj_chip(proj_label)}"
            f"    <span style='{name_style}'>{prefix}{_esc(item.get('name'))}</span>"
            f"    {_status_badge_html(item.get('status'))}"
            f"    {_priority_badge_html(item.get('priority')) if kind == 'task' else ''}"
            f"    {_stale_badge(item, ctx['stale_threshold'])}"
            f"    {comment_badge_html(cc)}"
            f"    <span style='margin-left:auto;white-space:nowrap'>"
            f"      {_deadline_html(item.get('deadline'), threshold)}</span>"
            f"  </div>"
            f"  <div style='display:flex;align-items:center;justify-content:space-between;"
            f"              gap:8px;margin-top:3px;'>"
            f"    <span style='font-size:11px;color:#888;'>"
            f"      {parent_note}{' · ' if parent_note and notes else ''}{_esc(notes)}</span>"
            f"    <span style='white-space:nowrap'>{people}</span>"
            f"  </div>"
            f"</div>"
        )
    with col_btn:
        if st.button("Details", key=f"{key_prefix}_{kind}_{item['id']}", use_container_width=True):
            if kind == "task":
                task_details_modal(item, can_edit=can_edit)
            else:
                subtask_details_modal(item, can_edit=can_edit)


def _render_bucket(bucket: str, items: list, ctx: dict, key_prefix: str,
                   collapsed: bool = False, show_people: bool = True):
    if not items:
        return
    label, fg, bg = _BUCKET_META[bucket]
    header = (
        f"<div style='background:{bg};border-left:4px solid {fg};border-radius:5px;"
        f"padding:5px 10px;margin:10px 0 2px 0;'>"
        f"<span style='color:{fg};font-weight:800;font-size:13px;letter-spacing:0.02em'>"
        f"{label}</span>"
        f"<span style='color:{fg};font-size:12px;font-weight:600'> · {len(items)}</span>"
        f"</div>"
    )

    if collapsed:
        with st.expander(f"{label} · {len(items)}", expanded=False):
            for it in items:
                _render_row(it, kind=it["_kind"], ctx=ctx, key_prefix=key_prefix,
                            show_people=show_people)
        return

    st.html(header)
    for it in items:
        _render_row(it, kind=it["_kind"], ctx=ctx, key_prefix=key_prefix,
                    show_people=show_people)


# ─── data ─────────────────────────────────────────────────────────────────────

def _fetch(email: str):
    try:
        threshold = int(get_settings().get("expiring_threshold_days", 14))
    except (TypeError, ValueError):
        threshold = 14

    projects = {
        p["id"]: p for p in (
            supabase.table("projects").select("*").eq("is_archived", False).execute().data or []
        )
    }
    tasks = supabase.table("tasks").select("*").eq("is_archived", False).execute().data or []
    subtasks = supabase.table("subtasks").select("*").eq("is_archived", False).execute().data or []
    users = supabase.table("users").select("email, name, avatar_color").eq(
        "is_approved", True
    ).execute().data or []

    task_map = {t["id"]: t for t in tasks}
    # Only work that belongs to a live project.
    tasks = [t for t in tasks if t.get("project_id") in projects]
    subtasks = [
        s for s in subtasks
        if task_map.get(s.get("task_id"), {}).get("project_id") in projects
    ]

    return {
        "threshold": threshold,
        "stale_threshold": stale_threshold(),
        "projects": projects,
        "tasks": tasks,
        "subtasks": subtasks,
        "task_map": task_map,
        "user_map": {u["email"]: u for u in users},
        "email": email,
        "is_admin": st.session_state.get("user_role") == "admin",
        "comment_counts": get_comment_counts(),
    }


def _mine(items: list, email: str, role: str) -> list:
    """Active items where the user is owner (role='owner') or supervisor."""
    field = "owner_email" if role == "owner" else "supervisor_email"
    return [
        i for i in items
        if i.get(field) == email and (i.get("status") or "Not started") not in _INACTIVE
    ]


def _bucketize(items: list, threshold: int) -> dict[str, list]:
    today = datetime.date.today()
    out: dict[str, list] = {k: [] for k, *_ in _BUCKETS}
    for i in items:
        out[_bucket_of(i, threshold, today)].append(i)
    for k in out:
        out[k].sort(key=_sort_key)
    return out


# ─── sections ─────────────────────────────────────────────────────────────────

def _render_timesheet_reminder(email: str) -> None:
    """Contractors only: months still to file. Silent for everyone else."""
    try:
        pending = get_pending_timesheets(email)
    except Exception:
        return
    if not pending:
        return

    from utils.timesheet import MONTHS_IT

    months = ", ".join(
        f"{MONTHS_IT[p['month']]} {p['year']}" + (" (draft)" if p["status"] == "draft" else "")
        for p in pending
    )
    st.warning(
        f"🧾 **Time sheet to file — {months}.**  \n"
        "Open **Time Sheets** → **Autofill** and adjust → **Mark as completed** → "
        "**Download Excel** → export to PDF, sign it and email it to your supervisor."
    )
    if st.button("Open Time Sheets →", key="dash_ts_open"):
        st.session_state["current_page"] = "Time Sheets"
        st.rerun()


def _render_conference_strip(email: str, ctx: dict) -> None:
    """Conference papers the user is involved in, kept front-of-mind."""
    try:
        items = get_conference_paper_tasks(user_email=email)
    except Exception:
        return
    items = [t for t in items if (t.get("status") or "Not started") not in _INACTIVE]
    if not items:
        return

    st.html(
        "<div style='display:flex;align-items:center;gap:8px;margin:8px 0 2px 0'>"
        "<span style='font-size:13px;font-weight:800;color:#1A3E8B'>🎤 Conference papers</span>"
        f"<span style='background:#EEF3FF;color:#1A3E8B;border-radius:99px;padding:1px 9px;"
        f"font-size:11px;font-weight:700'>{len(items)}</span></div>"
    )
    with st.container(border=True):
        for t in sort_tasks_by_deadline(items):
            t["_kind"] = "task"
            _render_row(t, kind="task", ctx=ctx, key_prefix="confdash")


def _render_my_work(ctx: dict) -> None:
    email, threshold = ctx["email"], ctx["threshold"]

    my_tasks = _mine(ctx["tasks"], email, "owner")
    my_subs = _mine(ctx["subtasks"], email, "owner")
    for t in my_tasks:
        t["_kind"] = "task"
    for s in my_subs:
        s["_kind"] = "subtask"
    items = my_tasks + my_subs
    buckets = _bucketize(items, threshold)

    # ── Focus metrics ────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔴 Overdue", len(buckets["overdue"]))
    m2.metric("🚫 Blocked", len(buckets["blocked"]))
    m3.metric(f"🟠 Due ≤{threshold}d", len(buckets["due_soon"]))
    m4.metric("Active total", len(items))

    # All-time punctuality, kept as one quiet line instead of three big tiles.
    try:
        owned_all = supabase.table("tasks").select(
            "status, deadline, completion_date"
        ).eq("owner_email", email).execute().data or []
    except Exception:
        owned_all = []
    owned_all = [t for t in owned_all if t.get("status") != "Cancelled"]
    ds = compute_delay_stats(owned_all)
    today = datetime.date.today()
    done_30 = sum(
        1 for t in owned_all
        if t.get("status") == "Completed"
        and (cd := _parse_date(t.get("completion_date")))
        and (today - cd).days <= 30
    )
    st.caption(
        f"Completed in the last 30 days: **{done_30}** · "
        f"On-time rate: **{ds['on_time_rate']}%**" if ds["on_time_rate"] is not None
        else f"Completed in the last 30 days: **{done_30}** · On-time rate: —"
    )

    _render_conference_strip(email, ctx)

    if not items:
        st.success("✅ Nothing on your plate. All your tasks are completed.")
        return

    _render_bucket("overdue", buckets["overdue"], ctx, "mw", show_people=False)
    _render_bucket("blocked", buckets["blocked"], ctx, "mw", show_people=False)
    _render_bucket("due_soon", buckets["due_soon"], ctx, "mw", show_people=False)
    _render_bucket("in_progress", buckets["in_progress"], ctx, "mw", show_people=False)
    _render_bucket("later", buckets["later"], ctx, "mw", collapsed=True, show_people=False)


def _render_supervision(ctx: dict) -> None:
    email, threshold = ctx["email"], ctx["threshold"]

    sup_tasks = _mine(ctx["tasks"], email, "supervisor")
    sup_subs = _mine(ctx["subtasks"], email, "supervisor")
    for t in sup_tasks:
        t["_kind"] = "task"
    for s in sup_subs:
        s["_kind"] = "subtask"
    items = sup_tasks + sup_subs

    if not items:
        st.info("You are not supervising any active task.")
        return

    buckets = _bucketize(items, threshold)
    by_person: dict[str, list] = {}
    for i in items:
        by_person.setdefault(i.get("owner_email") or "—", []).append(i)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔴 Overdue", len(buckets["overdue"]))
    m2.metric("🚫 Blocked", len(buckets["blocked"]))
    m3.metric(f"🟠 Due ≤{threshold}d", len(buckets["due_soon"]))
    m4.metric("People", len(by_person))

    # ── Weekly digest: what moved and what went quiet ────────────────────────
    from db import get_supervisor_digest
    dig = get_supervisor_digest(email, days=7)
    d1, d2, d3 = st.columns(3)
    d1.metric("✅ Chiusi (7g)", len(dig["completed"]))
    d2.metric("📈 Mossi (7g)", len(dig["moved"]))
    d3.metric(f"⏳ Fermi ≥{stale_threshold()}g", len(dig["stuck"]))
    if dig["stuck"]:
        st.caption(
            "I 'fermi' non sono necessariamente in ritardo: semplicemente nessuno "
            "li aggiorna. Su un task lungo è il segnale più affidabile che hai."
        )

    # ── What needs the supervisor, across everyone ───────────────────────────
    attention = buckets["overdue"] + buckets["blocked"]
    if attention:
        st.html(
            "<div style='margin:12px 0 2px 0'>"
            "<span style='font-size:14px;font-weight:800;color:#B3261E'>"
            "⚠️ Needs your attention</span>"
            "<span style='color:#888;font-size:12px'> — late or blocked, "
            "whoever is executing</span></div>"
        )
        with st.container(border=True):
            for it in sorted(attention, key=_sort_key):
                _render_row(it, kind=it["_kind"], ctx=ctx, key_prefix="sup_att")
    else:
        st.success("✅ Nothing late or blocked under your supervision.")

    # ── Per person ───────────────────────────────────────────────────────────
    st.html(
        "<div style='margin:16px 0 2px 0'>"
        "<span style='font-size:14px;font-weight:800;color:#333'>👥 By person</span>"
        "<span style='color:#888;font-size:12px'> — sorted by who needs help most</span></div>"
    )

    today = datetime.date.today()

    def _counts(lst):
        b = _bucketize(lst, threshold)
        return {k: len(v) for k, v in b.items()}

    people = []
    for owner, lst in by_person.items():
        c = _counts(lst)
        people.append((c["overdue"] + c["blocked"], c, owner, lst))
    people.sort(key=lambda x: (-x[0], -len(x[3])))

    for _, c, owner, lst in people:
        u = ctx["user_map"].get(owner, {"name": owner})
        name = u.get("name", owner)
        chips = []
        if c["overdue"]:
            chips.append(f"<span style='background:#FDECEC;color:#C62828;border-radius:4px;"
                         f"padding:1px 7px;font-size:11px;font-weight:700'>{c['overdue']} overdue</span>")
        if c["blocked"]:
            chips.append(f"<span style='background:#FDEDEC;color:#D93025;border-radius:4px;"
                         f"padding:1px 7px;font-size:11px;font-weight:700'>{c['blocked']} blocked</span>")
        if c["due_soon"]:
            chips.append(f"<span style='background:#FFF4E5;color:#B26A00;border-radius:4px;"
                         f"padding:1px 7px;font-size:11px;font-weight:700'>{c['due_soon']} due soon</span>")
        if not chips:
            chips.append("<span style='background:#E8F5E9;color:#2E7D32;border-radius:4px;"
                         "padding:1px 7px;font-size:11px;font-weight:700'>on track</span>")

        title = f"{name} — {len(lst)} active"
        with st.expander(title, expanded=bool(c["overdue"] or c["blocked"])):
            st.html(f"<div style='display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px'>"
                    f"{''.join(chips)}</div>")
            pb = _bucketize(lst, threshold)
            for bucket in ("overdue", "blocked", "due_soon", "in_progress", "later"):
                for it in pb[bucket]:
                    _render_row(it, kind=it["_kind"], ctx=ctx,
                                key_prefix=f"sup_{owner}", show_people=False)


# ─── entry point ──────────────────────────────────────────────────────────────

def show_dashboard():
    st.markdown(
        """
        <style>
        div[data-testid='stButton'] > button {
            min-height: 1.7rem; padding: 0.1rem 0.5rem; font-size: 0.78rem;
        }
        div[data-testid='stHorizontalBlock'] {
            background: transparent !important;
            border-bottom: 1px solid #F1F3F4;
            padding-top: 1px !important; padding-bottom: 1px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    email = st.session_state.get("user_email")
    if not email:
        st.error("User not found in session.")
        return

    given = st.session_state.get("user_given_name") or (
        st.session_state.get("user_name") or ""
    ).split(" ")[0]
    st.title(f"Hi {given}" if given else "Dashboard")
    st.caption(
        "What needs your attention now. The full project breakdown lives in **Projects**."
    )

    _render_timesheet_reminder(email)

    try:
        ctx = _fetch(email)
    except Exception as e:
        st.error(f"Error while loading dashboard data: {e}")
        return

    n_mine = len(_mine(ctx["tasks"], email, "owner")) + len(_mine(ctx["subtasks"], email, "owner"))
    n_sup = len(_mine(ctx["tasks"], email, "supervisor")) + len(_mine(ctx["subtasks"], email, "supervisor"))

    if n_sup:
        tab_mine, tab_sup = st.tabs([f"🎯 My work ({n_mine})", f"👥 Supervision ({n_sup})"])
        with tab_mine:
            _render_my_work(ctx)
        with tab_sup:
            _render_supervision(ctx)
    else:
        _render_my_work(ctx)
