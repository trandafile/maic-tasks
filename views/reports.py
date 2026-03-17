import streamlit as st
import datetime
from core.supabase_client import supabase
from utils.pdf_generator import generate_report_pdf

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

def _render_task_row(t: dict, users_dict: dict):
    seq_id   = t.get("sequence_id") or f"T-{t['id']}"
    name     = t.get("name", "")
    status   = t.get("status", "Not started")
    priority = (t.get("priority") or "none").lower()
    owner_n  = users_dict.get(t.get("owner_email"), t.get("owner_email") or "—")
    deadline = t.get("deadline")

    s_fg, s_bg = STATUS_COLOURS.get(status,    ("#888", "#f0f0f0"))
    p_fg, p_bg = PRIORITY_COLOURS.get(priority, ("#888", "#f0f0f0"))

    c_id, c_name, c_status, c_prio, c_owner, c_dl = st.columns([1.2, 3.2, 1.4, 1.2, 2.2, 1.4])
    with c_id:
        st.html(f"<span style='font-family:monospace;color:#888;font-size:0.82rem'>{seq_id}</span>")
    with c_name:
        st.write(f"**{name}**")
    with c_status:
        st.html(_badge(status, s_fg, s_bg))
    with c_prio:
        st.html(_badge(priority, p_fg, p_bg))
    with c_owner:
        st.html(_avatar_html(owner_n))
    with c_dl:
        st.html(_deadline_html(deadline))

def _fetch():
    try:
        projects     = supabase.table("projects").select("*").eq("is_archived", False).order("name").execute().data
        deliverables = supabase.table("deliverables").select("*").eq("is_archived", False).execute().data
        tasks        = supabase.table("tasks").select("*").order("sort_order", desc=False).execute().data
        subtasks     = supabase.table("subtasks").select("*").order("sort_order", desc=False).execute().data
        users        = supabase.table("users").select("email, name").execute().data
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

    users_dict = {u["email"]: u["name"] for u in users}

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
            caption_parts.append(f"{proj['start_date']} → {proj.get('end_date') or '—'}")
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
                total    = len(d_tasks)
                done     = len([t for t in d_tasks if t.get("status") == "Completed"])
                progress = done / total if total > 0 else 0.0
                d_status = d.get("status", "Not started")
                d_sl_fg, d_sl_bg = STATUS_COLOURS.get(d_status, ("#888", "#f0f0f0"))

                with st.container(border=True):
                    h1, h2, h3, h4 = st.columns([3, 2, 2, 1.3])
                    with h1:
                        st.write(f"**{d.get('name')}**")
                        st.caption(f"{d.get('type')} · deadline {d.get('deadline') or '—'}")
                    with h2:
                        st.progress(progress)
                    with h3:
                        st.caption(f"{done} / {total} tasks completed")
                    with h4:
                        st.html(_badge(d_status, d_sl_fg, d_sl_bg))
                    st.divider()
                    if d_tasks:
                        for t in d_tasks:
                            _render_task_row(t, users_dict)
                    else:
                        st.caption("No tasks matching the filters.")

        unassigned = [
            t for t in tasks
            if t.get("project_id") == pid and not t.get("deliverable_id") and task_matches(t)
        ]
        if unassigned:
            st.html(
                "<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                "color:#666;margin-top:16px;display:block'>TASKS WITHOUT DELIVERABLE</span>"
            )
            with st.container(border=True):
                st.html("<p style='font-style:italic;color:#888;font-size:0.85rem;margin:0 0 8px 0'>"
                        "General tasks — not linked to a specific deliverable</p>")
                for t in unassigned:
                    _render_task_row(t, users_dict)

        st.divider()


# ─── Carico per Persona ────────────────────────────────────────────────────────

def _render_person_card(person: dict):
    user        = person["user"]
    av_color    = user.get("avatar_color") or _avatar_colour(user.get("name", "?"))
    name        = user.get("name", "?")
    role        = user.get("role", "user")
    notes       = user.get("notes") or ""
    initials    = _initials(name)

    tasks_active  = person["tasks_active"]
    tasks_overdue = person["tasks_overdue"]
    proj_count    = person["projects_count"]
    est_hours     = person["estimate_hours"]
    hours_str     = f"{int(est_hours)}h" if est_hours else "—"
    overdue_col   = "#C62828" if tasks_overdue > 0 else "#1a1a1a"

    all_tasks = person["all_user_tasks"]
    total     = len(all_tasks)
    pct_c     = _pct(sum(1 for t in all_tasks if t.get("status") == "Completed"),  total)
    pct_w     = _pct(sum(1 for t in all_tasks if t.get("status") == "Working on"), total)
    pct_b     = _pct(sum(1 for t in all_tasks if t.get("status") == "Blocked"),    total)

    sub_label = f"{role} · {notes}" if notes else role

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
            f"<div><div style='font-size:1.15rem;font-weight:700;color:#1a1a1a'>{tasks_active}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>active tasks</div></div>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:{overdue_col}'>{tasks_overdue}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>overdue</div></div>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:#1a1a1a'>{proj_count}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>projects</div></div>"
            f"<div><div style='font-size:1.15rem;font-weight:700;color:#1a1a1a'>{hours_str}</div>"
            f"<div style='font-size:0.68rem;color:#888;text-transform:uppercase;letter-spacing:.04em'>est. hours</div></div>"
            f"</div></div>"
        )

        # ── Progress bars ──────────────────────────────────────────────────────
        if total > 0:
            st.html(
                f"<div style='padding:6px 16px'>"
                f"{_bar_row_html('Completed',   pct_c, '#2E7D32')}"
                f"{_bar_row_html('In progress', pct_w, '#1565C0')}"
                f"{_bar_row_html('Blocked',     pct_b, '#E65100')}"
                f"</div>"
            )

        # ── Project rows ───────────────────────────────────────────────────────
        for proj in person["projects"]:
            acronym   = proj["project_acronym"] or "?"
            proj_name = proj["project_name"]
            role_p    = proj["role"]
            sc        = proj["status_counts"]
            badge_col = _proj_badge_color(acronym)
            role_fg   = "#6A1B9A" if role_p == "owner" else "#E65100"
            role_bg   = "#F3E5F5" if role_p == "owner" else "#FFF3E0"

            chips = "".join(
                f"<span style='background:{STATUS_SQUARE.get(s,'#888')}22;"
                f"color:{STATUS_SQUARE.get(s,'#888')};border-radius:4px;"
                f"padding:1px 6px;font-size:0.72rem;margin-right:3px;font-weight:600'>"
                f"{cnt} {s.lower()}</span>"
                for s, cnt in sorted(sc.items())
            )

            st.html(
                f"<div style='display:flex;align-items:center;gap:10px;padding:6px 16px;"
                f"border-top:1px solid #f0f0f0;flex-wrap:wrap'>"
                f"<span style='background:{badge_col};color:#fff;border-radius:4px;"
                f"padding:2px 7px;font-size:0.72rem;font-weight:700;min-width:44px;"
                f"text-align:center;flex-shrink:0'>{acronym}</span>"
                f"<span style='flex:1;font-size:0.85rem;color:#333;min-width:120px'>{proj_name}</span>"
                f"<span style='display:flex;gap:2px;flex-wrap:wrap'>{chips}</span>"
                f"<span style='background:{role_bg};color:{role_fg};border-radius:4px;"
                f"padding:2px 8px;font-size:0.72rem;font-weight:700;flex-shrink:0'>{role_p}</span>"
                f"</div>"
            )


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
                parts.append(f"{_fmt_date(proj.get('start_date'))} → {_fmt_date(proj.get('end_date'))}")
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
        ch1, ch2, ch3, ch4, ch5 = st.columns([3, 1.4, 2.8, 1.6, 1.2])
        ch1.caption("Researcher")
        ch2.caption("Active tasks")
        ch3.caption("Status distribution")
        ch4.caption("Prevalent role")
        ch5.caption("Est. hours")

        for p in people:
            user     = p["user"]
            av_color = user.get("avatar_color") or _avatar_colour(user.get("name", "?"))
            name     = user.get("name", "?")
            initials = _initials(name)
            role     = p["role_prevalent"]
            est      = p["estimate_hours"]
            hrs_str  = f"{int(est)}h" if est else "—"
            role_fg  = "#6A1B9A" if role == "owner" else "#E65100"
            role_bg  = "#F3E5F5" if role == "owner" else "#FFF3E0"
            sq       = _squares_html(p["task_roles"])

            c1, c2, c3, c4, c5 = st.columns([3, 1.4, 2.8, 1.6, 1.2])
            with c1:
                st.html(
                    f"<div style='display:flex;align-items:center;gap:7px;padding:3px 0'>"
                    f"<div style='background:{av_color};color:#fff;width:26px;height:26px;"
                    f"border-radius:50%;display:flex;align-items:center;justify-content:center;"
                    f"font-size:0.65rem;font-weight:700;flex-shrink:0'>{initials}</div>"
                    f"<span style='font-size:0.88rem'>{name}</span></div>"
                )
            with c2:
                st.html(f"<div style='padding:6px 0;font-size:0.88rem'>{p['tasks_active']}</div>")
            with c3:
                st.html(
                    f"<div style='padding:4px 0;display:flex;flex-wrap:wrap;"
                    f"align-items:center'>{sq}</div>"
                )
            with c4:
                st.html(
                    f"<div style='padding:4px 0'>"
                    f"<span style='background:{role_bg};color:{role_fg};border-radius:4px;"
                    f"padding:2px 8px;font-size:0.75rem;font-weight:700'>{role}</span></div>"
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


# ─── Main entry point ──────────────────────────────────────────────────────────

def show_reports():
    st.title("📊 Project Reports")

    user_role = st.session_state.get("user_role")

    if user_role == "admin":
        tab_main, tab_wl, tab_sp = st.tabs([
            "📋 Project Report",
            "👤 Workload by Person",
            "🏗️ Staff by Project",
        ])
        with tab_main:
            _render_main_report()
        with tab_wl:
            _render_workload_report()
        with tab_sp:
            _render_staff_report()
    else:
        _render_main_report()
