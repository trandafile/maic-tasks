import streamlit as st
import datetime
from core.supabase_client import supabase
from utils.pdf_generator import generate_report_pdf
from utils.modals import person_pill_html, task_details_modal, subtask_details_modal, deliverable_details_modal
from utils.helpers import fmt_date, sort_tasks_by_deadline

# ─── Colour constants ──────────────────────────────────────────────────────────

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
AVATAR_PALETTE = [
    "#1565C0", "#2E7D32", "#E65100", "#6A1B9A",
    "#00695C", "#AD1457", "#F57F17", "#0277BD",
]
_PROJECT_PALETTE = [
    "#1565C0", "#2E7D32", "#E65100", "#6A1B9A",
    "#00695C", "#AD1457", "#0277BD", "#4527A0",
    "#558B2F", "#00838F",
]
STATUS_SQUARE = {
    "Completed":   "#2E7D32",
    "Working on":  "#1565C0",
    "Blocked":     "#E65100",
    "Not started": "#888888",
    "Cancelled":   "#B71C1C",
}

# ─── Small HTML / formatting helpers ──────────────────────────────────────────

def _avatar_colour(name: str) -> str:
    return AVATAR_PALETTE[abs(hash(name)) % len(AVATAR_PALETTE)]

def _proj_badge_color(acronym: str) -> str:
    return _PROJECT_PALETTE[abs(hash(acronym or "?")) % len(_PROJECT_PALETTE)]

def _initials(name: str) -> str:
    parts = (name or "?").split()
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()

def _badge(text: str, fg: str, bg: str) -> str:
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 8px;"
        f"border-radius:4px;font-size:0.78rem;font-weight:600;white-space:nowrap'>"
        f"{text}</span>"
    )

def _avatar_html(name: str, size: int = 24, color: str | None = None) -> str:
    c        = color or _avatar_colour(name)
    initials = _initials(name)
    fs       = size * 0.42
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;white-space:nowrap'>"
        f"<span style='background:{c};color:#fff;border-radius:50%;"
        f"width:{size}px;height:{size}px;display:inline-flex;align-items:center;"
        f"justify-content:center;font-size:{fs:.1f}px;font-weight:700'>{initials}</span>"
        f"<span>{name}</span></span>"
    )

def _deadline_html(deadline_str: str | None) -> str:
    if not deadline_str:
        return "<span style='color:#aaa'>—</span>"
    try:
        dl    = datetime.date.fromisoformat(deadline_str)
        delta = (dl - datetime.date.today()).days
        colour = "#C62828" if delta <= 3 else "#333333"
        label  = dl.strftime("%Y/%m/%d")
        return f"<span style='color:{colour};font-weight:{'700' if delta<=3 else '400'}'>{label}</span>"
    except Exception:
        return deadline_str

def _pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0

def _bar_row_html(label: str, pct: int, color: str) -> str:
    fill = f"width:{pct}%;min-width:{'2px' if pct > 0 else '0'}"
    return (
        f"<div style='display:flex;align-items:center;gap:8px;margin:3px 0'>"
        f"<span style='min-width:72px;color:#555;font-size:0.78rem'>{label}</span>"
        f"<div style='flex:1;background:#e8e8e8;border-radius:3px;height:7px'>"
        f"<div style='{fill};background:{color};border-radius:3px;height:7px'></div></div>"
        f"<span style='min-width:32px;text-align:right;font-size:0.78rem;"
        f"color:#444;font-weight:600'>{pct}%</span></div>"
    )

def _squares_html(task_roles: list, max_show: int = 12) -> str:
    shown = task_roles[:max_show]
    extra = len(task_roles) - max_show
    html  = ""
    for tr in shown:
        s = tr["task"].get("status", "Not started")
        c = STATUS_SQUARE.get(s, "#888")
        html += (
            f"<span style='display:inline-block;width:11px;height:11px;"
            f"background:{c};border-radius:2px;margin:1px'></span>"
        )
    if extra > 0:
        html += f"<span style='font-size:0.7rem;color:#888;margin-left:2px'>+{extra}</span>"
    return html

def _fmt_date(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%Y/%m/%d")
    except Exception:
        return d or "—"

# ─── Main report helpers ───────────────────────────────────────────────────────

def _render_people_pills(owner_email: str | None, sup_email: str | None, users_meta: dict) -> str:
    pills = ""
    if owner_email:
        u = users_meta.get(owner_email, {"name": owner_email, "avatar_color": "#534AB7"})
        pills += person_pill_html(
            u.get("name", owner_email),
            u.get("avatar_color", "#534AB7"),
            role="owner",
            compact=True,
        )
    if sup_email and sup_email != owner_email:
        u = users_meta.get(sup_email, {"name": sup_email, "avatar_color": "#BA7517"})
        pills += person_pill_html(
            u.get("name", sup_email),
            u.get("avatar_color", "#BA7517"),
            role="sup",
            compact=True,
        )
    return pills


def _render_task_row(t: dict, users_meta: dict, key_prefix: str = "rp_t"):
    seq_id   = t.get("sequence_id") or f"T-{t['id']}"
    name     = t.get("name", "")
    status   = t.get("status", "Not started")
    priority = (t.get("priority") or "none").lower()
    deadline = t.get("deadline")

    s_fg, s_bg = STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
    p_fg, p_bg = PRIORITY_COLOURS.get(priority, ("#888", "#f0f0f0"))

    c_id, c_name, c_status, c_prio, c_people, c_dl, c_action = st.columns([1.15, 2.8, 1.2, 1.05, 2.8, 1.2, 1.0])
    with c_id:
        st.html(f"<span style='font-family:monospace;color:#888;font-size:0.78rem'>{seq_id}</span>")
    with c_name:
        st.markdown(f"**{name}**")
    with c_status:
        st.html(_badge(status, s_fg, s_bg))
    with c_prio:
        st.html(_badge(priority, p_fg, p_bg))
    with c_people:
        pills = _render_people_pills(t.get("owner_email"), t.get("supervisor_email"), users_meta)
        st.html(pills if pills else "<span style='color:#aaa'>—</span>")
    with c_dl:
        st.html(_deadline_html(deadline))
    with c_action:
        if st.button("Details", key=f"{key_prefix}_{t['id']}", use_container_width=True):
            task_details_modal(t, can_edit=False)


def _render_subtask_row(s: dict, users_meta: dict, key_prefix: str = "rp_s"):
    s_name   = s.get("name", "")
    s_status = s.get("status", "Not started")
    s_dead   = s.get("deadline")
    s_fg, s_bg = STATUS_COLOURS.get(s_status, ("#888", "#f0f0f0"))

    c_pad, c_name, c_status, c_prio, c_people, c_dl, c_action = st.columns([1.15, 2.8, 1.2, 1.05, 2.8, 1.2, 1.0])
    with c_pad:
        st.html("<span style='color:#aaa;font-size:0.78rem'>↳ sub</span>")
    with c_name:
        st.markdown(f"<span style='font-size:0.9rem;color:#333'>{s_name}</span>", unsafe_allow_html=True)
    with c_status:
        st.html(_badge(s_status, s_fg, s_bg))
    with c_prio:
        st.html("<span style='color:#aaa'>—</span>")
    with c_people:
        pills = _render_people_pills(s.get("owner_email"), s.get("supervisor_email"), users_meta)
        st.html(pills if pills else "<span style='color:#aaa'>—</span>")
    with c_dl:
        st.html(_deadline_html(s_dead))
    with c_action:
        if st.button("Details", key=f"{key_prefix}_{s['id']}", use_container_width=True):
            subtask_details_modal(s, can_edit=False)

def _fetch():
    try:
        projects     = supabase.table("projects").select("*").eq("is_archived", False).order("name").execute().data
        deliverables = supabase.table("deliverables").select("*").eq("is_archived", False).execute().data
        tasks        = supabase.table("tasks").select("*").order("sort_order", desc=False).execute().data
        subtasks     = supabase.table("subtasks").select("*").order("sort_order", desc=False).execute().data
        users        = supabase.table("users").select("email, name, avatar_color").execute().data
        return projects, deliverables, tasks, subtasks, users
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return [], [], [], [], []

# ─── Main report ──────────────────────────────────────────────────────────────

def _render_main_report():
    user_role  = st.session_state.get("user_role")
    user_email = st.session_state.get("user_email")
    rbac_email = None if user_role == "admin" else user_email

    projects, deliverables, tasks, subtasks, users = _fetch()
    if not projects:
        st.info("No projects available.")
        return

    users_dict = {u["email"]: u.get("name", u["email"]) for u in users}
    users_meta = {u["email"]: u for u in users}

    with st.expander("⚙️ Filters", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            proj_map = {"All Projects": None}
            proj_map.update({p["name"]: p["id"] for p in projects})
            sel_proj  = st.selectbox("Project", list(proj_map.keys()), key="rp_proj")
            filt_proj = proj_map[sel_proj]
        with fc2:
            if rbac_email is None:
                user_map = {"All Users": None}
                user_map.update({u["name"]: u["email"] for u in users})
                sel_user  = st.selectbox("Assignee (Owner/Sup)", list(user_map.keys()), key="rp_user")
                filt_user = user_map[sel_user]
            else:
                st.caption(f"Assignee: {users_dict.get(rbac_email, rbac_email)}")
                filt_user = None
        with fc3:
            status_opts = ["All", "Active", "Completed", "Blocked"]
            sel_status  = st.selectbox("Task Status", status_opts, key="rp_status")
            filt_status = None if sel_status == "All" else sel_status

    def task_matches(t):
        if t.get("is_archived"):
            return False
        if rbac_email:
            if t.get("owner_email") != rbac_email and t.get("supervisor_email") != rbac_email:
                return False
        if filt_proj and t.get("project_id") != filt_proj:
            return False
        if filt_user:
            if t.get("owner_email") != filt_user and t.get("supervisor_email") != filt_user:
                return False
        if filt_status == "Active":
            if t.get("status") in ("Completed", "Cancelled"):
                return False
        elif filt_status == "Completed":
            if t.get("status") != "Completed":
                return False
        elif filt_status == "Blocked":
            if t.get("status") != "Blocked":
                return False
        return True

    visible_tasks     = [t for t in tasks if task_matches(t)]
    visible_deliv_ids = {t["deliverable_id"] for t in visible_tasks if t.get("deliverable_id")}
    visible_proj_ids  = {t["project_id"]     for t in visible_tasks if t.get("project_id")}

    proj_list = [
        p for p in projects
        if (filt_proj is None or p["id"] == filt_proj)
        and (rbac_email is None or p["id"] in visible_proj_ids)
    ]

    if st.button("📄 Export PDF", type="primary", key="rp_pdf"):
        pdf_buf = generate_report_pdf(
            proj_list, deliverables, tasks, subtasks, users_dict,
            filt_proj, filt_user, filt_status, rbac_email=rbac_email,
        )
        st.download_button(
            label="⬇️ Download PDF",
            data=pdf_buf,
            file_name=f"report_maic_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )

    st.divider()

    if rbac_email and not proj_list:
        st.info("No tasks assigned to you in available projects.")
        return

    for proj in proj_list:
        pid = proj["id"]
        st.html(
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:2px'>"
            f"<span style='width:18px;height:18px;background:#F59E0B;border-radius:4px;"
            f"display:inline-block'></span>"
            f"<span style='font-size:1.5rem;font-weight:700'>{proj.get('name')} "
            f"({proj.get('acronym','')})</span></div>"
        )
        caption_parts = []
        if proj.get("funding_agency"):
            caption_parts.append(f"Funding: {proj['funding_agency']}")
        if proj.get("start_date"):
            caption_parts.append(f"{fmt_date(proj.get('start_date'))} → {fmt_date(proj.get('end_date'))}")
        st.caption("  ·  ".join(caption_parts))
        st.write("")

        proj_deliverables = [
            d for d in deliverables
            if d.get("project_id") == pid
            and (rbac_email is None or d["id"] in visible_deliv_ids)
        ]

        if proj_deliverables:
            st.html("<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                    "color:#666'>DELIVERABLES</span>")
            for d in proj_deliverables:
                did      = d["id"]
                d_tasks  = [t for t in tasks if t.get("deliverable_id") == did and task_matches(t)]
                d_tasks  = sort_tasks_by_deadline(d_tasks)
                total    = len(d_tasks)
                done     = len([t for t in d_tasks if t.get("status") == "Completed"])
                progress = done / total if total > 0 else 0.0
                d_status = d.get("status", "Not started")
                d_sl_fg, d_sl_bg = STATUS_COLOURS.get(d_status, ("#888", "#f0f0f0"))

                with st.container(border=True):
                    h1, h2, h3, h4, h5 = st.columns([2.6, 1.8, 1.8, 1.2, 1.0])
                    with h1:
                        d_people = _render_people_pills(d.get("owner_email"), d.get("supervisor_email"), users_meta)
                        st.write(f"**{d.get('name')}**")
                        st.caption(f"{d.get('type')} · deadline: {fmt_date(d.get('deadline'))}")
                        st.html(d_people if d_people else "<span style='color:#aaa'>Owner/Supervisor: —</span>")
                    with h2:
                        st.progress(progress)
                    with h3:
                        st.caption(f"{done} / {total} tasks completed")
                    with h4:
                        st.html(_badge(d_status, d_sl_fg, d_sl_bg))
                    with h5:
                        if st.button("Details", key=f"rp_dd_{did}", use_container_width=True):
                            deliverable_details_modal(
                                d,
                                can_edit=False,
                                breadcrumb=f"Reports / {proj.get('name', '-') } / Deliverable",
                            )
                    st.divider()
                    if d_tasks:
                        for t in d_tasks:
                            _render_task_row(t, users_meta, key_prefix=f"rp_t_{did}")
                            t_subtasks = [
                                s for s in subtasks
                                if s.get("task_id") == t.get("id")
                                and not s.get("is_archived", False)
                            ]
                            for s in t_subtasks:
                                _render_subtask_row(s, users_meta, key_prefix=f"rp_s_{did}_{t.get('id')}")
                    else:
                        st.caption("No tasks matching the filters.")

        unassigned = [
            t for t in tasks
            if t.get("project_id") == pid and not t.get("deliverable_id") and task_matches(t)
        ]
        unassigned = sort_tasks_by_deadline(unassigned)
        if unassigned:
            st.html(
                "<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                "color:#666;margin-top:16px;display:block'>TASKS WITHOUT DELIVERABLE</span>"
            )
            with st.container(border=True):
                st.html("<p style='font-style:italic;color:#888;font-size:0.85rem;margin:0 0 8px 0'>"
                        "General tasks — not linked to a specific deliverable</p>")
                for t in unassigned:
                    _render_task_row(t, users_meta, key_prefix=f"rp_t_un_{pid}")
                    t_subtasks = [
                        s for s in subtasks
                        if s.get("task_id") == t.get("id")
                        and not s.get("is_archived", False)
                    ]
                    for s in t_subtasks:
                        _render_subtask_row(s, users_meta, key_prefix=f"rp_s_un_{pid}_{t.get('id')}")

        st.divider()


# ─── Carico per Persona ────────────────────────────────────────────────────────

def _render_person_card(person: dict):
    user         = person["user"]
    av_color     = user.get("avatar_color") or _avatar_colour(user.get("name", "?"))
    name         = user.get("name", "?")
    role         = user.get("role", "user")
    notes        = user.get("notes") or ""
    initials     = _initials(name)

    tasks_active      = person["tasks_active"]
    supervises_count  = person.get("supervises_count", 0)
    tasks_overdue     = person["tasks_overdue"]
    est_hours         = person["estimate_hours"]
    hours_str         = f"{int(est_hours)}h" if est_hours else "—"
    overdue_col       = "#C62828" if tasks_overdue > 0 else "#1a1a1a"

    owned_tasks      = person.get("owned_tasks", person["all_user_tasks"])
    supervised_tasks = person.get("supervised_tasks", [])
    total            = len(owned_tasks)
    pct_c  = _pct(sum(1 for t in owned_tasks if t.get("status") == "Completed"),  total)
    pct_w  = _pct(sum(1 for t in owned_tasks if t.get("status") == "Working on"), total)
    pct_b  = _pct(sum(1 for t in owned_tasks if t.get("status") == "Blocked"),    total)

    sub_label = f"{role} · {notes}" if notes else role

    # Status sort order for task lists
    _STATUS_ORDER = {"Blocked": 0, "Working on": 1, "Not started": 2, "Completed": 3, "Cancelled": 4}

    def _proj_badge(proj_id, all_projects_map) -> str:
        p = all_projects_map.get(proj_id, {})
        ac = p.get("acronym") or p.get("identifier", "?")
        c  = _proj_badge_color(ac)
        return (
            f"<span style='background:{c};color:#fff;border-radius:4px;"
            f"padding:1px 5px;font-size:0.7rem;font-weight:700;flex-shrink:0'>{ac}</span>"
        )

    def _task_row_html(t: dict, proj_map: dict) -> str:
        seq    = t.get("sequence_id") or f"T-{t['id']}"
        tname  = t.get("name", "")
        status = t.get("status", "Not started")
        s_fg, s_bg = STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
        badge  = f"<span style='background:{s_bg};color:{s_fg};border-radius:4px;padding:1px 6px;font-size:0.7rem;font-weight:600;flex-shrink:0;white-space:nowrap'>{status}</span>"
        proj_b = _proj_badge(t.get("project_id"), proj_map)
        return (
            f"<div style='display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid #f5f5f5;flex-wrap:wrap'>"
            f"<span style='font-family:monospace;color:#aaa;font-size:0.72rem;min-width:60px;flex-shrink:0'>{seq}</span>"
            f"<span style='flex:1;font-size:0.8rem;color:#222;min-width:80px'>{tname}</span>"
            f"{proj_b}"
            f"{badge}"
            f"</div>"
        )

    # Fetch projects map for badges
    try:
        _projs = supabase.table("projects").select("id, name, acronym, identifier").execute().data
        proj_map = {p["id"]: p for p in _projs}
    except Exception:
        proj_map = {}

    with st.container(border=True):
        # ── Header ────────────────────────────────────────────────────────────
        st.html(
            f"<div style='background:#f5f5f5;border-radius:6px;padding:10px 16px;"
            f"display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px'>"
            f"<div style='display:flex;align-items:center;gap:12px'>"
            f"<div style='background:{av_color};color:#fff;width:40px;height:40px;border-radius:50%;"
            f"display:flex;align-items:center;justify-content:center;"
            f"font-size:1rem;font-weight:700;flex-shrink:0'>{initials}</div>"
            f"<div>"
            f"<div style='font-size:1.05rem;font-weight:700;color:#1a1a1a'>{name}</div>"
            f"<div style='font-size:0.78rem;color:#666'>{sub_label}</div>"
            f"</div></div>"
            f"<div style='display:flex;gap:22px;text-align:center'>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:#3C3489'>{tasks_active}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>executes</div></div>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:#633806'>{supervises_count}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>supervises</div></div>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:{overdue_col}'>{tasks_overdue}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>overdue</div></div>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:#1a1a1a'>{hours_str}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>est. hours</div></div>"
            f"</div></div>"
        )

        # ── Progress bars (owned tasks only) ───────────────────────────────────
        if total > 0:
            st.html(
                f"<div style='padding:6px 16px'>"
                f"{_bar_row_html('Completed',   pct_c, '#2E7D32')}"
                f"{_bar_row_html('In progress', pct_w, '#1565C0')}"
                f"{_bar_row_html('Blocked',     pct_b, '#E65100')}"
                f"</div>"
            )

        # ── Two-column body: Executes | Supervises ────────────────────────────
        col_ex, col_sep, col_sup = st.columns([1, 0.02, 1])

        with col_ex:
            st.html(
                f"<div style='padding:4px 0 6px 0;'>"
                f"<span style='display:inline-block;width:8px;height:8px;background:#534AB7;"
                f"border-radius:50%;margin-right:5px;vertical-align:middle'></span>"
                f"<span style='font-size:11px;font-weight:700;color:#3C3489;"
                f"letter-spacing:0.05em;text-transform:uppercase'>Executes (Owner)</span>"
                f"</div>"
            )
            sorted_owned = sorted(
                [t for t in owned_tasks if t.get("status") != "Cancelled"],
                key=lambda t: _STATUS_ORDER.get(t.get("status", "Not started"), 99)
            )
            if sorted_owned:
                rows_html = "".join(_task_row_html(t, proj_map) for t in sorted_owned)
                st.html(f"<div style='padding:0 4px'>{rows_html}</div>")
            else:
                st.html("<p style='color:#aaa;font-style:italic;font-size:0.82rem;padding:4px'>No tasks owned.</p>")

        with col_sep:
            st.html("<div style='border-left:1px solid #e8e8e8;height:100%;min-height:60px'></div>")

        with col_sup:
            st.html(
                f"<div style='padding:4px 0 6px 0;'>"
                f"<span style='display:inline-block;width:8px;height:8px;background:#BA7517;"
                f"border-radius:50%;margin-right:5px;vertical-align:middle'></span>"
                f"<span style='font-size:11px;font-weight:700;color:#633806;"
                f"letter-spacing:0.05em;text-transform:uppercase'>Supervises</span>"
                f"</div>"
            )
            sorted_sup = sorted(
                [t for t in supervised_tasks if t.get("status") != "Cancelled"],
                key=lambda t: _STATUS_ORDER.get(t.get("status", "Not started"), 99)
            )
            if sorted_sup:
                rows_html = "".join(_task_row_html(t, proj_map) for t in sorted_sup)
                st.html(f"<div style='padding:0 4px'>{rows_html}</div>")
            else:
                st.html("<p style='color:#aaa;font-style:italic;font-size:0.82rem;padding:4px'>No tasks to supervise.</p>")


def _render_workload_report():
    from db import get_workload_per_person
    from utils.pdf_generator import generate_workload_pdf

    st.html(
        "<p style='font-size:0.75rem;font-weight:700;letter-spacing:0.1em;color:#666;"
        "text-transform:uppercase;margin-bottom:8px'>"
        "Active Task Distribution by Researcher</p>"
    )

    data = get_workload_per_person()
    if not data:
        st.info("No data available.")
        return

    if st.button("📄 Export PDF — Workload by Person", type="primary", key="pdf_wl"):
        pdf_buf = generate_workload_pdf(data)
        st.download_button(
            label="⬇️ Download PDF",
            data=pdf_buf,
            file_name=f"workload_by_person_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            key="dl_wl",
        )

    st.divider()

    for person in data:
        _render_person_card(person)
        st.write("")


# ─── Organico per Progetto ─────────────────────────────────────────────────────

def _render_project_staff_card(proj_data: dict):
    proj       = proj_data["project"]
    people     = proj_data["people"]
    task_count = proj_data["tasks_active_count"]

    with st.container(border=True):
        # ── Header ────────────────────────────────────────────────────────────
        hc1, hc2 = st.columns([6, 2])
        with hc1:
            acronym = proj.get("acronym", "") or proj.get("identifier", "")
            st.markdown(f"**{proj.get('name')} — {acronym}**")
            parts = []
            if proj.get("funding_agency"):
                parts.append(proj["funding_agency"])
            if proj.get("start_date"):
                parts.append(f"{fmt_date(proj.get('start_date'))} → {fmt_date(proj.get('end_date'))}")
            parts.append(f"{len(people)} researchers involved")
            st.caption("  ·  ".join(parts))
        with hc2:
            st.html(
                f"<div style='text-align:right;padding-top:4px'>"
                f"<span style='font-size:0.95rem;font-weight:700;color:#555'>"
                f"{task_count} active tasks</span></div>"
            )

        st.divider()

        # ── Column headers ────────────────────────────────────────────────────
        ch1, ch2, ch3, ch4, ch5 = st.columns([3, 1.4, 1.4, 2.8, 1.2])
        ch1.caption("Researcher")
        ch2.html("<span style='font-size:0.75rem;font-weight:700;color:#3C3489'>Executes</span>")
        ch3.html("<span style='font-size:0.75rem;font-weight:700;color:#633806'>Supervises</span>")
        ch4.caption("Status distribution")
        ch5.caption("Est. hours")

        for p in people:
            user           = p["user"]
            av_color       = user.get("avatar_color") or _avatar_colour(user.get("name", "?"))
            name           = user.get("name", "?")
            initials       = _initials(name)
            owned_count    = p.get("owned_count", 0)
            sup_count      = p.get("supervised_count", 0)
            owned_hours    = p.get("owned_hours")
            hrs_str        = f"{int(owned_hours)}h" if owned_hours else "—"
            sq             = _squares_html(p["task_roles"])

            c1, c2, c3, c4, c5 = st.columns([3, 1.4, 1.4, 2.8, 1.2])
            with c1:
                st.html(
                    f"<div style='display:flex;align-items:center;gap:7px;padding:3px 0'>"
                    f"<div style='background:{av_color};color:#fff;width:26px;height:26px;"
                    f"border-radius:50%;display:flex;align-items:center;justify-content:center;"
                    f"font-size:0.65rem;font-weight:700;flex-shrink:0'>{initials}</div>"
                    f"<span style='font-size:0.88rem'>{name}</span></div>"
                )
            with c2:
                if owned_count > 0:
                    st.html(
                        f"<div style='padding:4px 8px;background:#EEEDFE;border-radius:4px;"
                        f"text-align:center;font-size:0.88rem;font-weight:700;color:#3C3489'>"
                        f"{owned_count}</div>"
                    )
                else:
                    st.html("<div style='padding:4px 8px;text-align:center;font-size:0.88rem;color:#aaa'>—</div>")
            with c3:
                if sup_count > 0:
                    st.html(
                        f"<div style='padding:4px 8px;background:#FAEEDA;border-radius:4px;"
                        f"text-align:center;font-size:0.88rem;font-weight:700;color:#633806'>"
                        f"{sup_count}</div>"
                    )
                else:
                    st.html("<div style='padding:4px 8px;text-align:center;font-size:0.88rem;color:#aaa'>—</div>")
            with c4:
                st.html(
                    f"<div style='padding:4px 0;display:flex;flex-wrap:wrap;"
                    f"align-items:center'>{sq}</div>"
                )
            with c5:
                st.html(f"<div style='padding:6px 0;font-size:0.88rem;color:#555'>{hrs_str}</div>")

        # ── Legend ────────────────────────────────────────────────────────────
        legend_items = [
            ("Completed",   "#2E7D32"),
            ("Working on",  "#1565C0"),
            ("Blocked",     "#E65100"),
            ("Not started", "#888888"),
        ]
        legend_html = "".join(
            f"<span style='display:inline-flex;align-items:center;gap:4px'>"
            f"<span style='display:inline-block;width:10px;height:10px;"
            f"background:{c};border-radius:2px'></span>"
            f"<span>{s}</span></span>"
            for s, c in legend_items
        )
        st.html(
            f"<div style='display:flex;gap:14px;padding:6px 0 2px 0;"
            f"font-size:0.72rem;color:#555'>{legend_html}</div>"
        )


def _render_staff_report():
    from db import get_staff_per_project
    from utils.pdf_generator import generate_staff_pdf

    data = get_staff_per_project()
    if not data:
        st.info("No data available.")
        return

    if st.button("📄 Export PDF — Staff by Project", type="primary", key="pdf_sp"):
        pdf_buf = generate_staff_pdf(data)
        st.download_button(
            label="⬇️ Download PDF",
            data=pdf_buf,
            file_name=f"staff_by_project_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            key="dl_sp",
        )

    st.divider()

    for proj_data in data:
        _render_project_staff_card(proj_data)
        st.write("")


# ─── Detailed Report ──────────────────────────────────────────────────────────

def _render_detailed_report():
    """Detailed per-project report: deliverables → tasks → subtasks → activity."""
    from utils.helpers import strip_markdown
    from utils.pdf_generator import generate_detailed_report_pdf

    try:
        projects  = supabase.table("projects").select("*").eq("is_archived", False).order("name").execute().data
        all_users = supabase.table("users").select("email, name, avatar_color").eq("is_approved", True).execute().data
    except Exception as e:
        st.error(f"Error loading projects: {e}")
        return

    if not projects:
        st.info("No active projects.")
        return

    user_map = {u["email"]: u for u in all_users}
    users_dict_simple = {u["email"]: u.get("name", u["email"]) for u in all_users}

    proj_options = {p["name"]: p for p in projects}
    sel_proj_name = st.selectbox("Select Project", list(proj_options.keys()), key="dr_proj")
    proj = proj_options[sel_proj_name]
    pid  = proj["id"]

    # Fetch project data
    try:
        deliverables = supabase.table("deliverables").select("*").eq("project_id", pid).eq("is_archived", False).order("deadline").execute().data
        tasks        = supabase.table("tasks").select("*").eq("project_id", pid).eq("is_archived", False).order("sort_order").execute().data
        subtasks_all = supabase.table("subtasks").select("*").eq("is_archived", False).order("sort_order").execute().data
        # filter subtasks belonging to tasks of this project
        task_ids     = {t["id"] for t in tasks}
        subtasks     = [s for s in subtasks_all if s.get("task_id") in task_ids]
    except Exception as e:
        st.error(f"Error loading project data: {e}")
        return

    active_tasks = [t for t in tasks if t.get("status") not in ("Cancelled",)]
    completed    = [t for t in active_tasks if t.get("status") == "Completed"]
    today_str    = datetime.date.today().isoformat()
    overdue      = [t for t in active_tasks if t.get("deadline") and t["deadline"] < today_str and t.get("status") != "Completed"]
    total_hours  = sum(t.get("estimate_hours") or 0 for t in active_tasks)

    # ── Header ────────────────────────────────────────────────────────────────
    acronym = proj.get("acronym", "") or proj.get("identifier", "")
    st.html(
        f"<div style='margin-bottom:8px'>"
        f"<span style='font-size:1.5rem;font-weight:700;color:#1a1a1a'>"
        f"{proj.get('name')} ({acronym})</span></div>"
    )
    caption_parts = []
    if proj.get("funding_agency"):
        caption_parts.append(proj["funding_agency"])
    if proj.get("start_date"):
        caption_parts.append(f"{fmt_date(proj.get('start_date'))} → {fmt_date(proj.get('end_date'))}")
    caption_parts.append(f"Generated: {datetime.date.today().strftime('%Y/%m/%d')}")
    st.caption("  ·  ".join(caption_parts))

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total tasks", len(active_tasks))
    with m2:
        st.metric("Completed", len(completed), delta=None)
    with m3:
        overdue_col = len(overdue)
        st.metric("Overdue", overdue_col)
    with m4:
        st.metric("Est. hours", f"{int(total_hours)}h" if total_hours else "—")

    st.divider()

    # ── Export buttons ────────────────────────────────────────────────────────
    col_pdf, col_md, _ = st.columns([1.5, 1.5, 5])

    # Build activity comments for export
    try:
        comments_all = supabase.table("comments").select("*, users(name)").in_("task_id", list(task_ids)).order("created_at", desc=True).execute().data
    except Exception:
        comments_all = []
    comments_by_task = {}
    for c in comments_all:
        tid = c.get("task_id")
        comments_by_task.setdefault(tid, []).append(c)

    with col_pdf:
        if st.button("📄 Export PDF", type="primary", key="dr_pdf"):
            try:
                from utils.pdf_generator import generate_detailed_report_pdf
                subs_by_task = {}
                for s in subtasks:
                    subs_by_task.setdefault(s.get("task_id"), []).append(s)
                pdf_buf = generate_detailed_report_pdf(proj, deliverables, tasks, subs_by_task, comments_by_task, user_map)
                st.download_button(
                    "⬇️ Download PDF", data=pdf_buf,
                    file_name=f"detailed_report_{acronym}_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf", key="dr_dl_pdf"
                )
            except Exception as e:
                st.error(f"PDF error: {e}")

    with col_md:
        # Build markdown export
        md_lines = [
            f"# {proj.get('name')} ({acronym}) — Detailed Report",
            f"Generated: {datetime.date.today().strftime('%Y/%m/%d')}",
        ]
        if caption_parts:
            md_lines.append(f"Funding: {'  ·  '.join(caption_parts)}")
        md_lines.append("")
        md_lines.append(
            f"**Tasks:** {len(active_tasks)} total · {len(completed)} completed · "
            f"{len(overdue)} overdue · {int(total_hours)}h est. hours"
        )
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

        subs_by_task = {}
        for s in subtasks:
            subs_by_task.setdefault(s.get("task_id"), []).append(s)

        def _md_task_block(t):
            lines = []
            seq     = t.get("sequence_id") or f"T-{t['id']}"
            status  = t.get("status", "Not started")
            prio    = (t.get("priority") or "none").capitalize()
            owner_n = users_dict_simple.get(t.get("owner_email"), t.get("owner_email") or "—")
            sup_n   = users_dict_simple.get(t.get("supervisor_email"), t.get("supervisor_email") or "")
            dl      = fmt_date(t.get("deadline"))
            est     = f"{int(t['estimate_hours'])}h" if t.get("estimate_hours") else "—"

            lines.append(f"### {seq} — {t.get('name', '')}")
            lines.append(
                f"**Status:** {status} · **Priority:** {prio} · "
                f"**Deadline:** {dl} · **Est:** {est}"
            )
            lines.append(f"**Assignee:** {owner_n}" + (f" · **Supervisor:** {sup_n}" if sup_n else ""))
            lines.append("")
            if t.get("notes"):
                lines.append(t["notes"])
                lines.append("")

            t_subs = subs_by_task.get(t["id"], [])
            if t_subs:
                lines.append("#### Subtasks")
                for s in t_subs:
                    s_status   = s.get("status", "Not started")
                    s_owner_n  = users_dict_simple.get(s.get("owner_email"), s.get("owner_email") or "—")
                    s_sup_n    = users_dict_simple.get(s.get("supervisor_email"), "") if s.get("supervisor_email") else ""
                    s_seq      = s.get("sequence_id") or f"S-{s['id']}"
                    chk        = "x" if s_status == "Completed" else " "
                    lines.append(f"- [{chk}] {s_seq} — {s.get('name', '')} ({s_status})")
                    if s_owner_n:
                        lines.append(f"  Owner: {s_owner_n}" + (f" · Sup: {s_sup_n}" if s_sup_n else ""))
                    if s.get("notes"):
                        for ln in s["notes"].split("\n"):
                            lines.append(f"  {ln}")
                lines.append("")

            t_comments = [c for c in comments_by_task.get(t["id"], []) if not c.get("is_system_event")]
            if t_comments:
                lines.append("#### Activity")
                for c in t_comments:
                    author = "?"
                    u_rel = c.get("users")
                    if isinstance(u_rel, dict):
                        author = u_rel.get("name", "?")
                    elif isinstance(u_rel, list) and u_rel:
                        author = u_rel[0].get("name", "?")
                    ts = c.get("created_at", "")[:16].replace("T", " ")
                    lines.append(f"- {ts} · {author} — {c.get('body', '')}")
                lines.append("")

            lines.append("---")
            lines.append("")
            return lines

        deliv_map = {d["id"]: d for d in deliverables}
        sorted_delivs = sorted(deliverables, key=lambda d: d.get("deadline") or "9999-12-31")

        for d in sorted_delivs:
            did     = d["id"]
            d_tasks = [t for t in tasks if t.get("deliverable_id") == did and t.get("status") != "Cancelled"]
            d_tasks = sort_tasks_by_deadline(d_tasks)
            total_d = len(d_tasks)
            done_d  = len([t for t in d_tasks if t.get("status") == "Completed"])
            md_lines.append(f"## {d.get('name')} ({d.get('type', '')} · deadline {fmt_date(d.get('deadline'))})")
            md_lines.append(f"Progress: {done_d}/{total_d} tasks")
            md_lines.append("")
            for t in d_tasks:
                md_lines.extend(_md_task_block(t))

        no_deliv = [t for t in tasks if not t.get("deliverable_id") and t.get("status") != "Cancelled"]
        no_deliv = sort_tasks_by_deadline(no_deliv)
        if no_deliv:
            md_lines.append("## Generic Tasks (No Deliverable)")
            md_lines.append("")
            for t in no_deliv:
                md_lines.extend(_md_task_block(t))

        md_content = "\n".join(md_lines)
        st.download_button(
            "⬇️ Export Markdown", data=md_content,
            file_name=f"detailed_report_{acronym}_{datetime.date.today().strftime('%Y%m%d')}.md",
            mime="text/markdown", key="dr_dl_md"
        )

    st.write("")

    # ── Deliverables ──────────────────────────────────────────────────────────
    sorted_delivs = sorted(deliverables, key=lambda d: d.get("deadline") or "9999-12-31")
    subs_by_task  = {}
    for s in subtasks:
        subs_by_task.setdefault(s.get("task_id"), []).append(s)

    STATUS_DOT = {
        "Completed":   "#2E7D32",
        "Working on":  "#1565C0",
        "Blocked":     "#E65100",
        "Not started": "#888888",
        "Cancelled":   "#B71C1C",
    }

    def _render_task_block(t: dict):
        seq     = t.get("sequence_id") or f"T-{t['id']}"
        status  = t.get("status", "Not started")
        prio    = (t.get("priority") or "none").lower()
        s_fg, s_bg = STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
        p_fg, p_bg = PRIORITY_COLOURS.get(prio, ("#888", "#f0f0f0"))

        # a) Header row
        h_left, h_right = st.columns([5, 2])
        with h_left:
            st.html(
                f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
                f"<span style='font-family:monospace;color:#aaa;font-size:0.8rem;flex-shrink:0'>{seq}</span>"
                f"<span style='font-size:14px;font-weight:700;color:#1a1a1a'>{t.get('name','')}</span>"
                f"</div>"
            )
        with h_right:
            st.html(
                f"<div style='display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end'>"
                f"<span style='background:{s_bg};color:{s_fg};border-radius:4px;"
                f"padding:2px 8px;font-size:0.78rem;font-weight:600'>{status}</span>"
                f"<span style='background:{p_bg};color:{p_fg};border-radius:4px;"
                f"padding:2px 8px;font-size:0.78rem;font-weight:600'>{prio}</span>"
                f"</div>"
            )

        # b) Metadata row
        owner_e = t.get("owner_email")
        sup_e   = t.get("supervisor_email")
        meta_pills = ""
        if owner_e:
            u = user_map.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
            meta_pills += person_pill_html(u.get("name", owner_e), u.get("avatar_color", "#534AB7"),
                                           role="owner", compact=False)
        if sup_e and sup_e != owner_e:
            u = user_map.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
            meta_pills += person_pill_html(u.get("name", sup_e), u.get("avatar_color", "#BA7517"),
                                           role="sup", compact=False)
        deadline_txt = f"Deadline: {fmt_date(t.get('deadline'))}" if t.get("deadline") else ""
        compl_txt    = f"Completed: {fmt_date(t.get('completion_date'))}" if t.get("completion_date") else ""
        est_txt      = f"Est: {int(t['estimate_hours'])}h" if t.get("estimate_hours") else ""
        meta_text    = "  ·  ".join(x for x in [deadline_txt, compl_txt, est_txt] if x)

        st.html(
            f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:4px 0'>"
            f"{meta_pills}"
            f"<span style='font-size:12px;color:#666'>{meta_text}</span>"
            f"</div>"
        )

        # c) Description / notes
        if t.get("notes"):
            with st.container():
                st.markdown(
                    f"<div style='background:#FAFAFA;border-radius:6px;padding:10px 14px;"
                    f"margin:6px 0;border:1px solid #f0f0f0'>"
                    f"",
                    unsafe_allow_html=True
                )
                st.markdown(t["notes"])
                st.markdown("</div>", unsafe_allow_html=True)

        # d) Subtasks
        t_subs = subs_by_task.get(t["id"], [])
        if t_subs:
            st.html(
                "<div style='font-size:11px;font-weight:700;color:#888;"
                "text-transform:uppercase;letter-spacing:0.08em;margin:8px 0 4px 0'>"
                "SUBTASKS</div>"
            )
            for s in t_subs:
                s_status   = s.get("status", "Not started")
                s_dot_col  = STATUS_DOT.get(s_status, "#888")
                s_seq      = s.get("sequence_id") or f"S-{s['id']}"
                s_owner_e  = s.get("owner_email")
                s_sup_e    = s.get("supervisor_email")
                s_sf, s_sb = STATUS_COLOURS.get(s_status, ("#888", "#f0f0f0"))
                s_badge = (
                    f"<span style='background:{s_sb};color:{s_sf};border-radius:4px;"
                    f"padding:1px 6px;font-size:0.72rem;font-weight:600'>{s_status}</span>"
                )
                s_pills = ""
                if s_owner_e:
                    u = user_map.get(s_owner_e, {"name": s_owner_e, "avatar_color": "#534AB7"})
                    s_pills += person_pill_html(u.get("name", s_owner_e), u.get("avatar_color", "#534AB7"),
                                                role="owner", compact=True)
                if s_sup_e and s_sup_e != s_owner_e:
                    u = user_map.get(s_sup_e, {"name": s_sup_e, "avatar_color": "#BA7517"})
                    s_pills += person_pill_html(u.get("name", s_sup_e), u.get("avatar_color", "#BA7517"),
                                                role="sup", compact=True)

                st.html(
                    f"<div style='display:flex;align-items:center;gap:6px;"
                    f"padding:3px 0 3px 16px;flex-wrap:wrap'>"
                    f"<span style='width:8px;height:8px;background:{s_dot_col};"
                    f"border-radius:50%;flex-shrink:0'></span>"
                    f"<span style='font-family:monospace;color:#aaa;font-size:0.72rem;flex-shrink:0'>{s_seq}</span>"
                    f"<span style='font-size:13px;flex:1;min-width:80px'>{s.get('name','')}</span>"
                    f"{s_badge}"
                    f"{s_pills}"
                    f"</div>"
                )
                if s.get("notes"):
                    st.markdown(
                        f"<div style='margin-left:24px;background:#FAFAFA;border-radius:4px;"
                        f"padding:6px 10px;margin-top:2px;font-size:0.85rem'>",
                        unsafe_allow_html=True
                    )
                    st.markdown(s["notes"])
                    st.markdown("</div>", unsafe_allow_html=True)

        # e) Activity log
        t_comments = comments_by_task.get(t["id"], [])
        if t_comments:
            st.html(
                "<div style='font-size:11px;font-weight:700;color:#888;"
                "text-transform:uppercase;letter-spacing:0.08em;margin:8px 0 4px 0'>"
                "ACTIVITY</div>"
            )
            for c in t_comments:
                dot_col = "#2E7D32" if c.get("is_system_event") else "#1565C0"
                author  = "?"
                u_rel = c.get("users")
                if isinstance(u_rel, dict):
                    author = u_rel.get("name", "?")
                elif isinstance(u_rel, list) and u_rel:
                    author = u_rel[0].get("name", "?")
                ts = (c.get("created_at") or "")[:16].replace("T", " ")
                st.html(
                    f"<div style='display:flex;align-items:flex-start;gap:6px;"
                    f"padding:3px 0;font-size:0.85rem'>"
                    f"<span style='width:8px;height:8px;background:{dot_col};"
                    f"border-radius:50%;flex-shrink:0;margin-top:4px'></span>"
                    f"<span style='flex:1'>{c.get('body','')}</span>"
                    f"<span style='color:#aaa;font-size:11px;white-space:nowrap;flex-shrink:0'>"
                    f"· {ts} · {author}</span>"
                    f"</div>"
                )

        st.divider()

        for d in sorted_delivs:
            did     = d["id"]
            d_tasks = [t for t in tasks if t.get("deliverable_id") == did and t.get("status") != "Cancelled"]
        total_d = len(d_tasks)
        done_d  = len([t for t in d_tasks if t.get("status") == "Completed"])
        prog    = done_d / total_d if total_d > 0 else 0.0
        d_owner = d.get("owner_email")
        d_sup   = d.get("supervisor_email")
        d_pills = ""
        if d_owner:
            u = user_map.get(d_owner, {"name": d_owner, "avatar_color": "#534AB7"})
            d_pills += person_pill_html(u.get("name", d_owner), u.get("avatar_color", "#534AB7"), role="owner", compact=True)
        if d_sup and d_sup != d_owner:
            u = user_map.get(d_sup, {"name": d_sup, "avatar_color": "#BA7517"})
            d_pills += person_pill_html(u.get("name", d_sup), u.get("avatar_color", "#BA7517"), role="sup", compact=True)

        dh1, dh_btn = st.columns([8, 1])
        with dh1:
            st.html(
                f"<div style='background:#F5F5F5;border-radius:6px;padding:10px 16px;margin:8px 0'>"
                f"<span style='font-weight:700;font-size:1.05rem'>{d.get('name','')}</span>"
                f"&nbsp;<span style='font-style:italic;color:#888;font-size:0.85rem'>{d.get('type','')}</span>"
                f"&nbsp;&nbsp;<span style='font-size:0.85rem;color:#555'>"
                f"Deadline: {fmt_date(d.get('deadline'))}</span>"
                f"<div style='margin-top:4px'>{d_pills if d_pills else '<span style=\'color:#888;font-size:0.82rem\'>Owner/Supervisor: —</span>'}</div>"
                f"</div>"
            )
        with dh_btn:
            if st.button("Details", key=f"dr_dd_{did}", use_container_width=True):
                deliverable_details_modal(
                    d,
                    can_edit=False,
                    breadcrumb=f"Reports / Detailed Report / {proj.get('name', '-') } / Deliverable",
                )
        if d.get("description"):
            st.markdown(
                "<div style='background:#FAFAFA;border-radius:4px;padding:10px 16px;"
                "margin:4px 0 8px 0;border-left:3px solid #ddd;font-size:0.92rem'>",
                unsafe_allow_html=True,
            )
            st.markdown(d.get("description"))
            st.markdown("</div>", unsafe_allow_html=True)
        st.progress(prog)
        st.caption(f"{done_d} / {total_d} tasks completed")

        if d_tasks:
            for t in sorted(d_tasks, key=lambda t: t.get("sort_order") or 0):
                _render_task_block(t)
        else:
            st.caption("No tasks in this deliverable.")

    # ── Generic tasks (no deliverable) ────────────────────────────────────────
        no_deliv = [t for t in tasks if not t.get("deliverable_id") and t.get("status") != "Cancelled"]
    if no_deliv:
        st.html(
            "<div style='border:2px dashed #cccccc;border-radius:6px;padding:10px 16px;margin:16px 0;'>"
            "<span style='font-weight:700;color:#888;font-size:0.95rem'>"
            "GENERIC TASKS (NO DELIVERABLE)</span></div>"
        )
        for t in sorted(no_deliv, key=lambda t: t.get("sort_order") or 0):
            _render_task_block(t)


# ─── Main entry point ──────────────────────────────────────────────────────────

def show_reports():
    st.title("📊 Project Reports")

    user_role = st.session_state.get("user_role")

    if user_role == "admin":
        tab_main, tab_wl, tab_sp, tab_det = st.tabs([
            "📋 Project Report",
            "👤 Workload by Person",
            "🏗️ Staff by Project",
            "📄 Detailed Report",
        ])
        with tab_main:
            _render_main_report()
        with tab_wl:
            _render_workload_report()
        with tab_sp:
            _render_staff_report()
        with tab_det:
            _render_detailed_report()
    else:
        _render_main_report()
