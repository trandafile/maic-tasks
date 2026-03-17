import streamlit as st
import datetime
from core.supabase_client import supabase
from utils.pdf_generator import generate_report_pdf

# ─── Colour helpers ────────────────────────────────────────────────────────────

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

def _avatar_colour(name: str) -> str:
    return AVATAR_PALETTE[hash(name) % len(AVATAR_PALETTE)]

def _initials(name: str) -> str:
    parts = (name or "?").split()
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()

def _badge(text: str, fg: str, bg: str) -> str:
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 8px;"
        f"border-radius:4px;font-size:0.78rem;font-weight:600;white-space:nowrap'>"
        f"{text}</span>"
    )

def _avatar_html(name: str) -> str:
    colour   = _avatar_colour(name)
    initials = _initials(name)
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;white-space:nowrap'>"
        f"<span style='background:{colour};color:#fff;border-radius:50%;"
        f"width:24px;height:24px;display:inline-flex;align-items:center;"
        f"justify-content:center;font-size:0.68rem;font-weight:700'>{initials}</span>"
        f"<span>{name}</span></span>"
    )

def _deadline_html(deadline_str: str | None) -> str:
    if not deadline_str:
        return "<span style='color:#aaa'>—</span>"
    try:
        dl    = datetime.date.fromisoformat(deadline_str)
        delta = (dl - datetime.date.today()).days
        colour = "#C62828" if delta <= 3 else "#333333"
        label  = dl.strftime("%d/%m/%Y")
        return f"<span style='color:{colour};font-weight:{'700' if delta<=3 else '400'}'>{label}</span>"
    except Exception:
        return deadline_str

# ─── Task table ────────────────────────────────────────────────────────────────

def _render_task_row(t: dict, users_dict: dict):
    seq_id   = t.get("sequence_id") or f"T-{t['id']}"
    name     = t.get("name", "")
    status   = t.get("status", "Not started")
    priority = (t.get("priority") or "none").lower()
    owner_n  = users_dict.get(t.get("owner_email"), t.get("owner_email") or "—")
    deadline = t.get("deadline")

    s_fg, s_bg = STATUS_COLOURS.get(status, ("#888", "#f0f0f0"))
    p_fg, p_bg = PRIORITY_COLOURS.get(priority, ("#888", "#f0f0f0"))

    c_id, c_name, c_status, c_prio, c_owner, c_dl = st.columns(
        [1.2, 3.2, 1.4, 1.2, 2.2, 1.4]
    )
    with c_id:
        st.html(
            f"<span style='font-family:monospace;color:#888;font-size:0.82rem'>{seq_id}</span>"
        )
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

# ─── Data fetching ──────────────────────────────────────────────────────────────

def _fetch():
    try:
        projects     = supabase.table("projects").select("*").eq("is_archived", False).order("name").execute().data
        deliverables = supabase.table("deliverables").select("*").eq("is_archived", False).execute().data
        tasks        = supabase.table("tasks").select("*").order("sort_order", desc=False).execute().data
        subtasks     = supabase.table("subtasks").select("*").order("sort_order", desc=False).execute().data
        users        = supabase.table("users").select("email, name").execute().data
        return projects, deliverables, tasks, subtasks, users
    except Exception as e:
        st.error(f"Errore nel caricamento dati: {e}")
        return [], [], [], [], []

# ─── Main view ──────────────────────────────────────────────────────────────────

def show_reports():
    st.title("📊 Report Progetti")

    # ── RBAC ──────────────────────────────────────────────────────────────────
    user_role  = st.session_state.get("user_role")
    user_email = st.session_state.get("user_email")
    # For "user" role: filter by their email; for "admin": no filter (None)
    rbac_email = None if user_role == "admin" else user_email

    projects, deliverables, tasks, subtasks, users = _fetch()
    if not projects:
        st.info("Nessun progetto disponibile.")
        return

    users_dict = {u["email"]: u["name"] for u in users}

    # ── Filters ──────────────────────────────────────────────────────────────
    with st.expander("⚙️ Filtri", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            proj_map = {"Tutti i Progetti": None}
            proj_map.update({p["name"]: p["id"] for p in projects})
            sel_proj  = st.selectbox("Progetto", list(proj_map.keys()))
            filt_proj = proj_map[sel_proj]
        with fc2:
            # For "user" role, restrict assignee filter to themselves only
            if rbac_email is None:
                user_map = {"Tutti gli Utenti": None}
                user_map.update({u["name"]: u["email"] for u in users})
                sel_user  = st.selectbox("Assegnatario (Owner/Sup)", list(user_map.keys()))
                filt_user = user_map[sel_user]
            else:
                st.caption(f"Assegnatario: {users_dict.get(rbac_email, rbac_email)}")
                filt_user = None  # RBAC filter applied separately below
        with fc3:
            status_opts = ["Tutti", "Attivi", "Completati", "Blocked"]
            sel_status  = st.selectbox("Stato Task", status_opts)
            filt_status = None if sel_status == "Tutti" else sel_status

    # ── Combined task filter (RBAC + explicit filters) ────────────────────────
    def task_matches(t):
        if t.get("is_archived"):
            return False
        # RBAC: user sees only their own tasks
        if rbac_email:
            if t.get("owner_email") != rbac_email and t.get("supervisor_email") != rbac_email:
                return False
        # Project filter
        if filt_proj and t.get("project_id") != filt_proj:
            return False
        # Explicit assignee filter (admin only)
        if filt_user:
            if t.get("owner_email") != filt_user and t.get("supervisor_email") != filt_user:
                return False
        # Status filter
        if filt_status == "Attivi":
            if t.get("status") in ("Completed", "Cancelled"):
                return False
        elif filt_status == "Completati":
            if t.get("status") != "Completed":
                return False
        elif filt_status == "Blocked":
            if t.get("status") != "Blocked":
                return False
        return True

    # ── RBAC-aware hierarchy pruning ──────────────────────────────────────────
    # Collect visible task IDs and their deliverable/project IDs
    visible_tasks = [t for t in tasks if task_matches(t)]
    visible_task_ids     = {t["id"] for t in visible_tasks}
    visible_deliverable_ids = {t["deliverable_id"] for t in visible_tasks if t.get("deliverable_id")}
    visible_project_ids     = {t["project_id"]  for t in visible_tasks if t.get("project_id")}

    # Filter projects and deliverables to only those with visible content
    proj_list = [
        p for p in projects
        if (filt_proj is None or p["id"] == filt_proj)
        and (rbac_email is None or p["id"] in visible_project_ids)
    ]

    # ── PDF export ────────────────────────────────────────────────────────────
    if st.button("📄 Esporta PDF", type="primary"):
        pdf_buf = generate_report_pdf(
            proj_list, deliverables, tasks, subtasks, users_dict,
            filt_proj, filt_user, filt_status,
            rbac_email=rbac_email,
        )
        st.download_button(
            label="⬇️ Scarica il PDF",
            data=pdf_buf,
            file_name=f"report_maic_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=False,
        )

    st.divider()

    if rbac_email and not proj_list:
        st.info("Nessun task assegnato a te nei progetti disponibili.")
        return

    for proj in proj_list:
        pid = proj["id"]

        # ── Project header ────────────────────────────────────────────────────
        st.html(
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:2px'>"
            f"<span style='width:18px;height:18px;background:#F59E0B;border-radius:4px;"
            f"display:inline-block'></span>"
            f"<span style='font-size:1.5rem;font-weight:700'>{proj.get('name')} "
            f"({proj.get('acronym','')})</span></div>"
        )
        caption_parts = []
        if proj.get("funding_agency"):
            caption_parts.append(f"Ente finanziatore: {proj['funding_agency']}")
        if proj.get("start_date"):
            end = proj.get("end_date") or "—"
            caption_parts.append(f"{proj['start_date']} → {end}")
        st.caption("  ·  ".join(caption_parts))
        st.write("")

        # ── Deliverables with RBAC pruning ────────────────────────────────────
        proj_deliverables = [
            d for d in deliverables
            if d.get("project_id") == pid
            and (rbac_email is None or d["id"] in visible_deliverable_ids)
        ]

        if proj_deliverables:
            st.html("<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                    "color:#666'>DELIVERABLES</span>")

            for d in proj_deliverables:
                did     = d["id"]
                d_tasks = [t for t in tasks if t.get("deliverable_id") == did and task_matches(t)]
                total   = len(d_tasks)
                done    = len([t for t in d_tasks if t.get("status") == "Completed"])
                progress  = done / total if total > 0 else 0.0
                d_status  = d.get("status", "Not started")
                d_sl_fg, d_sl_bg = STATUS_COLOURS.get(d_status, ("#888", "#f0f0f0"))

                with st.container(border=True):
                    h1, h2, h3, h4 = st.columns([3, 2, 2, 1.3])
                    with h1:
                        st.write(f"**{d.get('name')}**")
                        st.caption(f"{d.get('type')} · scadenza {d.get('deadline') or '—'}")
                    with h2:
                        st.progress(progress)
                    with h3:
                        st.caption(f"{done} / {total} task completati")
                    with h4:
                        st.html(_badge(d_status, d_sl_fg, d_sl_bg))

                    st.divider()

                    if d_tasks:
                        for t in d_tasks:
                            _render_task_row(t, users_dict)
                    else:
                        st.caption("Nessun task corrispondente ai filtri.")

        # ── Task senza deliverable (RBAC-pruned) ──────────────────────────────
        unassigned = [
            t for t in tasks
            if t.get("project_id") == pid
            and not t.get("deliverable_id")
            and task_matches(t)
        ]

        if unassigned:
            st.html(
                "<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                "color:#666;margin-top:16px;display:block'>TASK SENZA DELIVERABLE</span>"
            )
            with st.container(border=True):
                st.html(
                    "<p style='font-style:italic;color:#888;font-size:0.85rem;margin:0 0 8px 0'>"
                    "Task generali — non associati a un deliverable specifico</p>"
                )
                for t in unassigned:
                    _render_task_row(t, users_dict)

        st.divider()
