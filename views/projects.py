import streamlit as st
import datetime
from core.supabase_client import supabase
from utils.modals import get_status_color_map, render_priority_badge, task_details_modal, subtask_details_modal
from utils.notifications import send_task_assigned

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

def fetch_hierarchy(show_archived=False):
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

        users = supabase.table("users").select("email, name").eq("is_approved", True).execute().data

        return projects, deliverables, tasks, subtasks, users
    except Exception as e:
        st.error(f"Errore nel caricamento dati: {e}")
        return [], [], [], [], []


# ─── Modals ─────────────────────────────────────────────────────────────────────

@st.dialog("Aggiungi Nuovo Deliverable")
def add_deliverable_modal(project_id):
    with st.form("new_deliv_form"):
        name     = st.text_input("Nome Deliverable*")
        type_val = st.selectbox("Tipologia", ["paper", "layout", "prototype"])
        deadline = st.date_input("Scadenza", value=None)
        if st.form_submit_button("Crea Deliverable", type="primary"):
            if not name:
                st.error("Nome obbligatorio.")
                return
            try:
                supabase.table("deliverables").insert({
                    "project_id": project_id, "name": name, "type": type_val,
                    "status": "Not started",
                    "deadline": str(deadline) if deadline else None
                }).execute()
                st.success("Creato!")
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")


@st.dialog("Aggiungi Nuovo Task")
def add_task_modal(project_id, deliverables, users, prefill_deliverable_id=None):
    """Generic add-task modal; if prefill_deliverable_id is set that deliverable
    is pre-selected in the dropdown."""
    with st.form("new_task_form"):
        name = st.text_input("Titolo del Task*")

        deliv_options = {"Nessuno": None}
        deliv_options.update({d["name"]: d["id"] for d in deliverables if d["project_id"] == project_id})

        # Pre-select deliverable if requested
        prefill_name = "Nessuno"
        if prefill_deliverable_id:
            for k, v in deliv_options.items():
                if v == prefill_deliverable_id:
                    prefill_name = k
                    break

        sel_deliv = st.selectbox(
            "Collega a Deliverable",
            list(deliv_options.keys()),
            index=list(deliv_options.keys()).index(prefill_name)
        )

        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner    = st.selectbox("Owner*", list(user_opts.keys()),
                                     index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
            priority = st.selectbox("Priorità", ["none", "low", "medium", "high", "urgent"], index=2)
        with c2:
            supervisor = st.selectbox("Supervisor", ["Nessuno"] + list(user_opts.keys()))
            deadline   = st.date_input("Scadenza", value=None)

        notes = st.text_area("Note/Descrizione (Markdown)", height=120)

        if st.form_submit_button("Crea Task", type="primary"):
            if not name:
                st.error("Il titolo è obbligatorio.")
                return
            new_task = {
                "project_id":     project_id,
                "deliverable_id": deliv_options[sel_deliv],
                "name":           name,
                "owner_email":    user_opts[owner],
                "supervisor_email": user_opts[supervisor] if supervisor != "Nessuno" else None,
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

                # Notify owner and supervisor
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                proj_name = p_res.data[0].get("name", "") if p_res.data else ""
                enriched_task = {**new_task, "id": t_id, "sequence_id": seq_id, "project_name": proj_name}
                owner_email = user_opts[owner]
                sup_email   = user_opts[supervisor] if supervisor != "Nessuno" else None
                send_task_assigned(enriched_task, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(enriched_task, sup_email, assigner)

                st.success("Creato!")
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")


@st.dialog("Aggiungi Subtask")
def add_subtask_modal(task_id, users):
    with st.form("new_subtask_form"):
        name      = st.text_input("Titolo del Subtask*")
        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me        = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner      = st.selectbox("Owner*", list(user_opts.keys()),
                                       index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
        with c2:
            supervisor = st.selectbox("Supervisor", ["Nessuno"] + list(user_opts.keys()))
        deadline = st.date_input("Scadenza", value=None)

        if st.form_submit_button("Crea Subtask", type="primary"):
            if not name:
                st.error("Titolo obbligatorio.")
                return
            try:
                owner_email = user_opts[owner]
                sup_email   = user_opts[supervisor] if supervisor != "Nessuno" else None
                res = supabase.table("subtasks").insert({
                    "task_id":          task_id,
                    "name":             name,
                    "owner_email":      owner_email,
                    "supervisor_email": sup_email,
                    "status":           "Not started",
                    "deadline":         str(deadline) if deadline else None,
                    "sort_order":       999,
                }).execute()

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

                st.success("Creato!")
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")


@st.dialog("Crea Nuovo Progetto")
def add_project_modal():
    with st.form("new_proj_form"):
        name       = st.text_input("Nome Progetto*")
        c1, c2     = st.columns(2)
        with c1:
            acronym    = st.text_input("Acronimo", help="Es. HIPA2")
            identifier = st.text_input("Modello ID Task*", help="Es. HIP → HIP-1, HIP-2…")
        with c2:
            start_date = st.date_input("Data Inizio", value=datetime.date.today())
            end_date   = st.date_input("Data Fine Stimata", value=None)
        funding = st.text_input("Ente Finanziatore")

        if st.form_submit_button("Crea Progetto", type="primary"):
            if not name or not identifier:
                st.error("Nome e Modello ID sono obbligatori.")
                return
            try:
                supabase.table("projects").insert({
                    "name":            name,
                    "acronym":         acronym,
                    "identifier":      identifier.upper(),
                    "funding_agency":  funding,
                    "start_date":      str(start_date) if start_date else None,
                    "end_date":        str(end_date) if end_date else None,
                    "is_archived":     False,
                }).execute()
                st.success("Progetto Creato!")
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")


# ─── Task row renderer ──────────────────────────────────────────────────────────

def _render_task_row(t, subtasks, users, user_email, is_admin, key_prefix):
    t_id      = t["id"]
    is_owner  = t.get("owner_email") == user_email
    is_sup    = t.get("supervisor_email") == user_email
    can_edit  = is_admin or is_owner or is_sup
    opacity   = "1" if can_edit else "0.45"
    seq_id    = t.get("sequence_id") or f"T-{t_id}"
    status    = t.get("status", "Not started")
    priority  = (t.get("priority") or "none").lower()

    st.html(
        f"<div style='margin-bottom:0;padding:2px 0;opacity:{opacity}'>"
        f"  <span style='font-family:monospace;font-size:0.82rem;color:#888'>{seq_id}</span>"
        f"</div>"
    )

    c1, c2, c3, c4 = st.columns([4, 1.6, 1.4, 2.2])
    with c1:
        st.markdown(
            f"<span style='opacity:{opacity};font-size:0.95rem'><b>{t.get('name')}</b></span>",
            unsafe_allow_html=True
        )
    with c2:
        st.html(_status_badge(status))
    with c3:
        st.html(_priority_badge(priority))
    with c4:
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("🔍 Dettaglio", key=f"{key_prefix}_det_{t_id}"):
                task_details_modal(t, can_edit)
        with btn2:
            if st.button("➕ Sub", key=f"{key_prefix}_addsub_{t_id}", disabled=not can_edit):
                add_subtask_modal(t_id, users)

    # ── Nested subtasks ──────────────────────────────────────────────────────
    t_subtasks = [s for s in subtasks if s.get("task_id") == t_id]
    for s in t_subtasks:
        s_id        = s["id"]
        s_is_owner  = s.get("owner_email") == user_email
        s_can_edit  = is_admin or s_is_owner or (s.get("supervisor_email") == user_email)
        s_opacity   = "1" if s_can_edit else "0.45"
        s_status    = s.get("status", "Not started")

        sc1, sc2, sc3, sc4 = st.columns([4, 1.6, 1.4, 2.2])
        with sc1:
            st.markdown(
                f"<span style='opacity:{s_opacity};padding-left:28px;font-size:0.88rem'>"
                f"↳ 🖇️ {s.get('name')}</span>",
                unsafe_allow_html=True
            )
        with sc2:
            st.html(_status_badge(s_status))
        with sc3:
            st.write("")  # subtasks have no priority field, keep aligned
        with sc4:
            stc1, _ = st.columns(2)
            with stc1:
                if st.button("🔍 Vista", key=f"{key_prefix}_vistaS_{s_id}"):
                    subtask_details_modal(s, s_can_edit)


# ─── Main view ──────────────────────────────────────────────────────────────────

def show_projects():
    st.title("Progetti e Workspace")

    col_tools, c_arch = st.columns([1, 3])
    with col_tools:
        if st.session_state.get('user_role') == 'admin':
            if st.button("➕ Nuovo Progetto", type="primary", use_container_width=True):
                add_project_modal()
    with c_arch:
        show_archived = st.checkbox("Mostra Archiviati", value=False)

    st.divider()

    projects, deliverables, tasks, subtasks, users = fetch_hierarchy(show_archived)

    if not projects:
        st.info("Nessun progetto trovato. Crea un nuovo progetto per iniziare.")
        return

    user_email = st.session_state.get('user_email')
    is_admin   = st.session_state.get('user_role') == 'admin'

    for proj in projects:
        proj_id   = proj["id"]
        proj_name = proj.get("name", "Progetto")
        acronym   = proj.get("acronym", "")
        arch_tag  = " 🗄️ ARCHIVIATO" if proj.get("is_archived") else ""

        # ── Collapsed by default ──────────────────────────────────────────────
        with st.expander(f"📁 {proj_name} ({acronym}){arch_tag}", expanded=False):

            # ── Top-bar: add deliverable + add generic task ───────────────────
            tc1, tc2, _ = st.columns([2, 2, 6])
            with tc1:
                if is_admin:
                    if st.button("➕ Deliverable", key=f"add_del_{proj_id}", use_container_width=True):
                        add_deliverable_modal(proj_id)
            with tc2:
                if st.button("➕ Task Generico", key=f"add_generic_t_{proj_id}", use_container_width=True):
                    add_task_modal(proj_id, deliverables, users, prefill_deliverable_id=None)

            st.write("")

            proj_deliverables = [d for d in deliverables if d.get("project_id") == proj_id]

            if not proj_deliverables:
                st.caption("*Nessun deliverable definito per questo progetto.*")

            # ── One styled block per deliverable ──────────────────────────────
            for d in proj_deliverables:
                d_id     = d["id"]
                d_name   = d.get("name", "")
                d_type   = d.get("type", "")
                d_status = d.get("status", "Not started")
                arch_d   = " (archiviato)" if d.get("is_archived") else ""
                
                deliv_tasks = [t for t in tasks if t.get("deliverable_id") == d_id]

                with st.container(border=True):
                    # Deliverable header
                    h1, h2 = st.columns([8, 1])
                    with h1:
                        st.html(
                            f"<div style='background:#F5F5F5;border-radius:6px;padding:6px 10px;"
                            f"margin-bottom:4px'>"
                            f"<b>{d_name}</b><i style='color:#888;font-size:0.85rem'>"
                            f"  {d_type}{arch_d}</i>"
                            f"&nbsp;&nbsp;"
                            f"<span style='float:right'>{_status_badge(d_status)}</span>"
                            f"</div>"
                        )
                    with h2:
                        if is_admin and not d.get("is_archived"):
                            if st.button("🗑️", key=f"arch_del_{d_id}", help="Archivia Deliverable"):
                                supabase.table("deliverables").update({"is_archived": True}).eq("id", d_id).execute()
                                st.rerun()

                    # Task rows
                    if not deliv_tasks:
                        st.caption("    *Nessun task per questo deliverable.*")
                    else:
                        for t in deliv_tasks:
                            _render_task_row(t, subtasks, users, user_email, is_admin,
                                             key_prefix=f"d{d_id}")
                            st.divider()

                    # Per-deliverable "+ Nuovo Task" button
                    if st.button(f"➕ Nuovo Task in «{d_name}»", key=f"add_dt_{d_id}",
                                 use_container_width=True):
                        add_task_modal(proj_id, deliverables, users, prefill_deliverable_id=d_id)

            # ── Unassigned tasks section ──────────────────────────────────────
            unassigned = [
                t for t in tasks
                if t.get("project_id") == proj_id and not t.get("deliverable_id")
            ]

            if unassigned:
                st.write("")
                st.html(
                    "<span style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;"
                    "color:#666;text-transform:uppercase'>Task senza Deliverable</span>"
                )
                with st.container(border=True):
                    st.html(
                        "<p style='font-style:italic;color:#888;font-size:0.83rem;margin:0 0 6px 0'>"
                        "Task generali — non associati a un deliverable specifico</p>"
                    )
                    for t in unassigned:
                        _render_task_row(t, subtasks, users, user_email, is_admin,
                                         key_prefix=f"p{proj_id}_u")
                        st.divider()
