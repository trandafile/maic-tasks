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

import streamlit as st

from core.supabase_client import supabase
from db import (
    get_settings, compute_delay_stats, get_conference_paper_tasks, get_comment_counts,
    get_pending_timesheets, days_since_update, stale_threshold,
)
from utils.helpers import PRIORITY_ORDER
from utils.modals import task_details_modal, subtask_details_modal
from utils.rows import ROW_COLS, row_html, header_html, urgency_sort

_INACTIVE = {"Completed", "Cancelled"}

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



# ─── small helpers ────────────────────────────────────────────────────────────

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


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
# Same row as the Projects tree (utils/rows.py): name | status | deadline |
# owner / supervisor, tinted light red when late and light orange when due soon.
# Here the project is a chip and the parent a muted second line, because the
# dashboard is flat — never a folder to open.

def _row_context(item: dict, kind: str, ctx: dict) -> tuple[str, str, str]:
    """(project label, path line, meta line) for a flat row."""
    if kind == "task":
        proj = ctx["projects"].get(item.get("project_id"), {})
        deliv = ctx["deliverables"].get(item.get("deliverable_id"))
        path = deliv.get("name") if deliv else ""
        cc = ctx["comment_counts"].get(item.get("id"), 0)
    else:
        parent = ctx["task_map"].get(item.get("task_id"), {})
        proj = ctx["projects"].get(parent.get("project_id"), {})
        path = f"in: {parent.get('name')}" if parent.get("name") else ""
        cc = 0  # comments live on tasks

    meta = []
    idle = days_since_update(item)
    if idle is not None and idle >= ctx["stale_threshold"]:
        meta.append(f"idle {idle}d")
    if cc:
        meta.append(f"💬 {cc}")
    label = proj.get("acronym") or proj.get("identifier") or proj.get("name") or ""
    return label, path, " · ".join(meta)


def _render_row(item: dict, *, kind: str, ctx: dict, key_prefix: str,
                show_people: bool = True):
    email, is_admin = ctx["email"], ctx["is_admin"]
    can_edit = (is_admin or item.get("owner_email") == email
                or item.get("supervisor_email") == email)
    label, path, meta = _row_context(item, kind, ctx)

    c_row, c_act = st.columns(ROW_COLS, vertical_alignment="center")
    with c_row:
        st.html(row_html(item, kind=kind, user_map=ctx["user_map"],
                         threshold=ctx["threshold"], project_label=label,
                         path=path, meta=meta, show_people=show_people, flat=True))
    with c_act:
        if st.button("✏️", key=f"{key_prefix}_{kind}_{item['id']}", type="tertiary",
                     help="Details and edit"):
            if kind == "task":
                task_details_modal(item, can_edit=can_edit)
            else:
                subtask_details_modal(item, can_edit=can_edit)


def _render_rows(items: list, ctx: dict, key_prefix: str, show_people: bool = True,
                 first_label: str = "Item"):
    """A bordered block of rows with the shared column header."""
    with st.container(border=True, gap=None):
        hc, _ = st.columns(ROW_COLS)
        with hc:
            st.html(header_html(first_label=first_label))
        for it in items:
            _render_row(it, kind=it["_kind"], ctx=ctx, key_prefix=key_prefix,
                        show_people=show_people)


def _section_title(title: str, note: str = "", colour: str = "#202124") -> None:
    st.html(f"<div style='margin:14px 0 4px 0'><span style='font-size:15px;font-weight:700;"
            f"color:{colour}'>{title}</span>"
            + (f"<span style='color:#80868B;font-size:12px'> — {note}</span>" if note else "")
            + "</div>")


def _render_bucket(bucket: str, items: list, ctx: dict, key_prefix: str,
                   collapsed: bool = False, show_people: bool = True):
    if not items:
        return
    label, fg, _bg = _BUCKET_META[bucket]
    if collapsed:
        with st.expander(f"{label} · {len(items)}", expanded=False):
            _render_rows(items, ctx, key_prefix, show_people)
        return
    _section_title(f"{label} · {len(items)}", colour=fg)
    _render_rows(items, ctx, key_prefix, show_people)


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
    deliverables = {
        d["id"]: d for d in (
            supabase.table("deliverables").select("id, name").execute().data or []
        )
    }

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
        "deliverables": deliverables,
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
    for t in items:
        t["_kind"] = "task"
    _render_rows(urgency_sort(items, ctx["threshold"]), ctx, "confdash", first_label="Paper")


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

    _render_bucket("overdue", buckets["overdue"], ctx, "mw")
    _render_bucket("blocked", buckets["blocked"], ctx, "mw")
    _render_bucket("due_soon", buckets["due_soon"], ctx, "mw")
    _render_bucket("in_progress", buckets["in_progress"], ctx, "mw")
    _render_bucket("later", buckets["later"], ctx, "mw", collapsed=True)


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

    from db import get_supervisor_digest
    dig = get_supervisor_digest(email, days=7)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔴 Overdue", len(buckets["overdue"]))
    m2.metric("🚫 Blocked", len(buckets["blocked"]))
    m3.metric(f"🟠 Due ≤{threshold}d", len(buckets["due_soon"]))
    m4.metric(f"⏳ Idle ≥{stale_threshold()}d", len(dig["stuck"]))
    st.caption(
        f"Last 7 days: **{len(dig['completed'])}** closed · **{len(dig['moved'])}** moved · "
        f"{len(by_person)} people supervised. 'Idle' does not mean late — it means "
        "nobody has touched it; on a long task that is the most reliable signal you have."
    )

    # ── What needs the supervisor, across everyone ───────────────────────────
    attention = urgency_sort(buckets["overdue"] + buckets["blocked"] + buckets["due_soon"],
                             threshold)
    if attention:
        _section_title("⚠️ Needs your attention", "late, due soon or blocked, whoever is executing",
                       colour="#B3261E")
        _render_rows(attention, ctx, "sup_att", first_label="Task")
    else:
        st.success("✅ Nothing late, due soon or blocked under your supervision.")

    # ── Per person ───────────────────────────────────────────────────────────
    _section_title("👥 By person", "who needs help most first")

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
        bits = []
        if c["overdue"]:
            bits.append(f":red[**{c['overdue']} overdue**]")
        if c["blocked"]:
            bits.append(f":red[**{c['blocked']} blocked**]")
        if c["due_soon"]:
            bits.append(f":orange[**{c['due_soon']} due soon**]")
        if not bits:
            bits.append(":green[on track]")
        bits.append(f"{len(lst)} active")
        touched = [d for d in (days_since_update(i) for i in lst) if d is not None]
        if touched:
            last = min(touched)
            bits.append("updated today" if last == 0 else f"last update {last}d ago")

        with st.expander(f"**{name}** · " + " · ".join(bits),
                         expanded=bool(c["overdue"] or c["blocked"])):
            _render_rows(urgency_sort(lst, threshold), ctx, f"sup_{owner}",
                         first_label="Task")


# ─── entry point ──────────────────────────────────────────────────────────────

def show_dashboard():
    st.markdown(
        """
        <style>
        div[data-testid='stButton'] > button {
            min-height: 1.7rem; padding: 0.1rem 0.5rem; font-size: 0.78rem;
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
