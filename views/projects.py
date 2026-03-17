import streamlit as st
import datetime
from core.supabase_client import supabase
from utils.modals import get_status_color_map, render_priority_badge, task_details_modal, subtask_details_modal, person_pill_html
from db import delete_task_cascade
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

        users = supabase.table("users").select("email, name, avatar_color").eq("is_approved", True).execute().data

        return projects, deliverables, tasks, subtasks, users
    except Exception as e:
        st.error(f"Errore nel caricamento dati: {e}")
        return [], [], [], [], []


# ─── Modals ─────────────────────────────────────────────────────────────────────

@st.dialog("Add New Deliverable")
def add_deliverable_modal(project_id):
    with st.form("new_deliv_form"):
        name     = st.text_input("Deliverable Name*")
        type_val = st.selectbox("Type", ["paper", "layout", "prototype"])
        deadline = st.date_input("Deadline", value=None, format="YYYY/MM/DD")
        if st.form_submit_button("Create Deliverable", type="primary"):
            if not name:
                st.error("Name is required.")
                return
            try:
                supabase.table("deliverables").insert({
                    "project_id": project_id, "name": name, "type": type_val,
                    "status": "Not started",
                    "deadline": str(deadline) if deadline else None
                }).execute()
                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Add New Task")
def add_task_modal(project_id, deliverables, users, prefill_deliverable_id=None):
    """Generic add-task modal; if prefill_deliverable_id is set that deliverable
    is pre-selected in the dropdown."""
    with st.form("new_task_form"):
        name = st.text_input("Task Title*")

        deliv_options = {"None": None}
        deliv_options.update({d["name"]: d["id"] for d in deliverables if d["project_id"] == project_id})

        # Pre-select deliverable if requested
        prefill_name = "None"
        if prefill_deliverable_id:
            for k, v in deliv_options.items():
                if v == prefill_deliverable_id:
                    prefill_name = k
                    break

        sel_deliv = st.selectbox(
            "Link to Deliverable",
            list(deliv_options.keys()),
            index=list(deliv_options.keys()).index(prefill_name)
        )

        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner    = st.selectbox("Owner*", list(user_opts.keys()),
                                     index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
            priority = st.selectbox("Priority", ["none", "low", "medium", "high", "urgent"], index=2)
        with c2:
            supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
            deadline   = st.date_input("Deadline", value=None, format="YYYY/MM/DD")

        notes = st.text_area("Notes/Description (Markdown)", height=120)

        if st.form_submit_button("Create Task", type="primary"):
            if not name:
                st.error("Title is required.")
                return
            new_task = {
                "project_id":     project_id,
                "deliverable_id": deliv_options[sel_deliv],
                "name":           name,
                "owner_email":    user_opts[owner],
                "supervisor_email": user_opts[supervisor] if supervisor != "None" else None,
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
                sup_email   = user_opts[supervisor] if supervisor != "None" else None
                send_task_assigned(enriched_task, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(enriched_task, sup_email, assigner)

                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Add Subtask")
def add_subtask_modal(task_id, users):
    with st.form("new_subtask_form"):
        name      = st.text_input("Subtask Title*")
        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me        = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner      = st.selectbox("Owner*", list(user_opts.keys()),
                                       index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
        with c2:
            supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
        deadline = st.date_input("Deadline", value=None, format="YYYY/MM/DD")

        if st.form_submit_button("Create Subtask", type="primary"):
            if not name:
                st.error("Title is required.")
                return
            try:
                owner_email = user_opts[owner]
                sup_email   = user_opts[supervisor] if supervisor != "None" else None
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

                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Create New Project")
def add_project_modal():
    with st.form("new_proj_form"):
        name       = st.text_input("Project Name*")
        c1, c2     = st.columns(2)
        with c1:
            acronym    = st.text_input("Acronym", help="E.g. HIPA2")
            identifier = st.text_input("Task ID Template*", help="E.g. HIP → HIP-1, HIP-2…")
        with c2:
            start_date = st.date_input("Start Date", value=datetime.date.today(), format="YYYY/MM/DD")
            end_date   = st.date_input("Estimated End Date", value=None, format="YYYY/MM/DD")
        funding = st.text_input("Funding Agency")

        if st.form_submit_button("Create Project", type="primary"):
            if not name or not identifier:
                st.error("Name and ID Template are required.")
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
                st.success("Project created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


# ─── Task row renderer ──────────────────────────────────────────────────────────

def _render_task_row(t, subtasks, users, user_email, is_admin, key_prefix):
    user_map  = {u["email"]: u for u in users}
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

    # columns: name | status | priority | owner+sup | action buttons | [delete]
    c1, c2, c3, c4, c5, c_del = st.columns([3, 1.4, 1.2, 2.8, 2.2, 0.5])
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
        owner_e = t.get("owner_email")
        sup_e   = t.get("supervisor_email")
        pills   = ""
        if owner_e:
            u = user_map.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
            pills += person_pill_html(
                u.get("name", owner_e),
                u.get("avatar_color", "#534AB7"),
                role="owner", compact=True
            )
        if sup_e and sup_e != owner_e:
            u = user_map.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
            pills += person_pill_html(
                u.get("name", sup_e),
                u.get("avatar_color", "#BA7517"),
                role="sup", compact=True
            )
        if pills:
            st.html(f"<div style='opacity:{opacity}'>{pills}</div>")
    with c5:
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("🔍 Detail", key=f"{key_prefix}_det_{t_id}"):
                task_details_modal(t, can_edit)
        with btn2:
            if st.button("➕ Sub", key=f"{key_prefix}_addsub_{t_id}", disabled=not can_edit):
                add_subtask_modal(t_id, users)
    with c_del:
        if is_admin:
            confirm_key = f"_confirm_del_t_{t_id}"
            if st.button("✕", key=f"{key_prefix}_delx_{t_id}", help="Permanently delete"):
                st.session_state[confirm_key] = True
                st.rerun()

    # ── Delete confirmation (inline, full width) ─────────────────────────────
    confirm_key = f"_confirm_del_t_{t_id}"
    if st.session_state.get(confirm_key):
        with st.container():
            st.warning(
                f"Permanently delete **{seq_id} — {t.get('name')}**? "
                f"This action cannot be undone."
            )
            cc1, cc2, cc3 = st.columns([1.5, 1.5, 7])
            with cc1:
                if st.button("Yes, delete", key=f"{key_prefix}_delyes_{t_id}", type="primary"):
                    delete_task_cascade(t_id)
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            with cc2:
                if st.button("Cancel", key=f"{key_prefix}_delno_{t_id}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()

    # ── Nested subtasks ──────────────────────────────────────────────────────
    t_subtasks = [s for s in subtasks if s.get("task_id") == t_id]
    for s in t_subtasks:
        s_id        = s["id"]
        s_is_owner  = s.get("owner_email") == user_email
        s_can_edit  = is_admin or s_is_owner or (s.get("supervisor_email") == user_email)
        s_opacity   = "1" if s_can_edit else "0.45"
        s_status    = s.get("status", "Not started")

        sc1, sc2, sc3, sc4, sc5, sc_del = st.columns([3, 1.4, 1.2, 2.8, 2.2, 0.5])
        with sc1:
            st.markdown(
                f"<span style='opacity:{s_opacity};padding-left:28px;font-size:0.88rem'>"
                f"↳ 🖇️ {s.get('name')}</span>",
                unsafe_allow_html=True
            )
        with sc2:
            st.html(_status_badge(s_status))
        with sc3:
            st.write("")  # no priority on subtasks
        with sc4:
            s_owner_e = s.get("owner_email")
            s_sup_e   = s.get("supervisor_email")
            s_pills   = ""
            if s_owner_e:
                u = user_map.get(s_owner_e, {"name": s_owner_e, "avatar_color": "#534AB7"})
                s_pills += person_pill_html(
                    u.get("name", s_owner_e),
                    u.get("avatar_color", "#534AB7"),
                    role="owner", compact=True
                )
            if s_sup_e and s_sup_e != s_owner_e:
                u = user_map.get(s_sup_e, {"name": s_sup_e, "avatar_color": "#BA7517"})
                s_pills += person_pill_html(
                    u.get("name", s_sup_e),
                    u.get("avatar_color", "#BA7517"),
                    role="sup", compact=True
                )
            if s_pills:
                st.html(f"<div style='opacity:{s_opacity}'>{s_pills}</div>")
        with sc5:
            stc1, _ = st.columns(2)
            with stc1:
                if st.button("🔍 View", key=f"{key_prefix}_vistaS_{s_id}"):
                    subtask_details_modal(s, s_can_edit)
        with sc_del:
            if is_admin:
                s_confirm_key = f"_confirm_del_s_{s_id}"
                if st.button("✕", key=f"{key_prefix}_sdelx_{s_id}", help="Permanently delete"):
                    st.session_state[s_confirm_key] = True
                    st.rerun()

        # subtask delete confirmation
        s_confirm_key = f"_confirm_del_s_{s_id}"
        if st.session_state.get(s_confirm_key):
            with st.container():
                st.warning(
                    f"Permanently delete subtask **{s.get('name')}**? "
                    f"This action cannot be undone."
                )
                scc1, scc2, scc3 = st.columns([1.5, 1.5, 7])
                with scc1:
                    if st.button("Yes, delete", key=f"{key_prefix}_sdelyes_{s_id}", type="primary"):
                        supabase.table("subtasks").delete().eq("id", s_id).execute()
                        st.session_state.pop(s_confirm_key, None)
                        st.rerun()
                with scc2:
                    if st.button("Cancel", key=f"{key_prefix}_sdelno_{s_id}"):
                        st.session_state.pop(s_confirm_key, None)
                        st.rerun()


# ─── Main view ──────────────────────────────────────────────────────────────────

def show_projects():
    st.title("Projects & Workspace")

    # Compact row rhythm for dense task/subtask tables in this page.
    st.markdown(
        """
        <style>
        div[data-testid='stButton'] > button {
            min-height: 1.75rem;
            padding: 0.15rem 0.5rem;
            font-size: 0.78rem;
        }
        div[data-testid='stHorizontalBlock'] {
            padding-top: 3px !important;
            padding-bottom: 3px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_tools, c_arch = st.columns([1, 3])
    with col_tools:
        if st.session_state.get('user_role') == 'admin':
            if st.button("➕ New Project", type="primary", use_container_width=True):
                add_project_modal()
    with c_arch:
        show_archived = st.checkbox("Show Archived", value=False)

    st.divider()

    projects, deliverables, tasks, subtasks, users = fetch_hierarchy(show_archived)

    if not projects:
        st.info("No projects found. Create a new project to get started.")
        return

    user_email = st.session_state.get('user_email')
    is_admin   = st.session_state.get('user_role') == 'admin'

    for proj in projects:
        proj_id   = proj["id"]
        proj_name = proj.get("name", "Project")
        acronym   = proj.get("acronym", "")
        arch_tag  = " 🗄️ ARCHIVED" if proj.get("is_archived") else ""

        # ── Collapsed by default ──────────────────────────────────────────────
        with st.expander(f"📁 {proj_name} ({acronym}){arch_tag}", expanded=False):

            # ── Top-bar: add deliverable + add generic task ───────────────────
            tc1, tc2, _ = st.columns([2, 2, 6])
            with tc1:
                if is_admin:
                    if st.button("➕ Deliverable", key=f"add_del_{proj_id}", use_container_width=True):
                        add_deliverable_modal(proj_id)
            with tc2:
                if st.button("➕ Generic Task", key=f"add_generic_t_{proj_id}", use_container_width=True):
                    add_task_modal(proj_id, deliverables, users, prefill_deliverable_id=None)

            st.write("")

            proj_deliverables = [d for d in deliverables if d.get("project_id") == proj_id]

            if not proj_deliverables:
                st.caption("*No deliverables defined for this project.*")

            # ── One styled block per deliverable ──────────────────────────────
            for d in proj_deliverables:
                d_id     = d["id"]
                d_name   = d.get("name", "")
                d_type   = d.get("type", "")
                d_status = d.get("status", "Not started")
                arch_d   = " (archived)" if d.get("is_archived") else ""

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
                            if st.button("🗑️", key=f"arch_del_{d_id}", help="Archive Deliverable"):
                                supabase.table("deliverables").update({"is_archived": True}).eq("id", d_id).execute()
                                st.rerun()

                    # Task rows
                    if not deliv_tasks:
                        st.caption("    *No tasks for this deliverable.*")
                    else:
                        for t in deliv_tasks:
                            _render_task_row(t, subtasks, users, user_email, is_admin,
                                             key_prefix=f"d{d_id}")
                            st.divider()

                    # Per-deliverable "+ New Task" button
                    if st.button(f"➕ New Task in «{d_name}»", key=f"add_dt_{d_id}",
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
                    "color:#666;text-transform:uppercase'>Generic Tasks (No Deliverable)</span>"
                )
                with st.container(border=True):
                    st.html(
                        "<p style='font-style:italic;color:#888;font-size:0.83rem;margin:0 0 6px 0'>"
                        "General tasks — not linked to a specific deliverable</p>"
                    )
                    for t in unassigned:
                        _render_task_row(t, subtasks, users, user_email, is_admin,
                                         key_prefix=f"p{proj_id}_u")
                        st.divider()
