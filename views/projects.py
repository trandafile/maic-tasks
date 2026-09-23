import streamlit as st
import datetime as _dt
import json
from core.supabase_client import supabase
from utils.modals import task_details_modal, subtask_details_modal, deliverable_details_modal
from db import delete_task_cascade, log_status_change
from utils.pdf_generator import generate_projects_pdf
from utils.notifications import send_task_assigned
from utils.helpers import parse_deliverable_tag_styles, deliverable_chip_html
from utils.md_editor import markdown_editor
from db import get_settings
from utils import codes as K
from utils.rows import (
    ROW_COLS, INACTIVE, row_html, header_html, urgency_sort, fmt, esc, project_chip,
    deliverable_head_html, chip, status_chip, deliverable_card_css, loose_band_html,
    type_colours, PROJECT_BOX_CSS,
)

# ─── Data fetching ──────────────────────────────────────────────────────────────

def fetch_hierarchy(show_archived=False, user_email=None, is_admin=False, only_mine=False):
    """Load the project → deliverable → task → subtask hierarchy.

    only_mine: keep only tasks/subtasks where ``user_email`` is owner or
    supervisor, then prune the deliverables and projects left without any
    visible item. Used by the admin "my tasks" default scope.
    """
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
        user_map = {u["email"]: u for u in (users or [])}

        # RBAC: for non-admin users, only keep projects where they are involved.
        if not is_admin and user_email:
            tasks_by_id = {t["id"]: t for t in (tasks or [])}
            involved_project_ids = {
                t.get("project_id")
                for t in (tasks or [])
                if t.get("project_id")
                and (
                    t.get("owner_email") == user_email
                    or t.get("supervisor_email") == user_email
                )
            }
            involved_project_ids.update(
                tasks_by_id.get(s.get("task_id"), {}).get("project_id")
                for s in (subtasks or [])
                if (s.get("owner_email") == user_email or s.get("supervisor_email") == user_email)
                and tasks_by_id.get(s.get("task_id"), {}).get("project_id")
            )
            projects = [p for p in (projects or []) if p.get("id") in involved_project_ids]

        # "My tasks" scope: narrow tasks/subtasks to the ones I own or supervise,
        # then drop the deliverables and projects that end up with nothing to show.
        if only_mine and user_email:
            def _mine(item: dict) -> bool:
                return (
                    item.get("owner_email") == user_email
                    or item.get("supervisor_email") == user_email
                )

            all_tasks = tasks or []
            all_subtasks = subtasks or []

            # A task is visible when it is mine, or when it carries a subtask of mine.
            my_subtask_parent_ids = {s.get("task_id") for s in all_subtasks if _mine(s)}
            tasks = [t for t in all_tasks if _mine(t) or t.get("id") in my_subtask_parent_ids]

            visible_tasks_by_id = {t["id"]: t for t in tasks}
            # Show my subtasks, plus every subtask of a task that is mine (context).
            subtasks = [
                s for s in all_subtasks
                if s.get("task_id") in visible_tasks_by_id
                and (_mine(s) or _mine(visible_tasks_by_id[s["task_id"]]))
            ]

            task_deliv_ids = {t.get("deliverable_id") for t in tasks if t.get("deliverable_id")}
            deliverables = [
                d for d in (deliverables or [])
                if d.get("id") in task_deliv_ids or _mine(d)
            ]

            visible_project_ids = {t.get("project_id") for t in tasks if t.get("project_id")}
            visible_project_ids.update(
                d.get("project_id") for d in deliverables if d.get("project_id")
            )
            projects = [p for p in (projects or []) if p.get("id") in visible_project_ids]

        return projects, deliverables, tasks, subtasks, users, user_map
    except Exception as e:
        st.error(f"Errore nel caricamento dati: {e}")
        return [], [], [], [], [], {}


# ─── Modals ─────────────────────────────────────────────────────────────────────

@st.dialog("Add New Deliverable")
def add_deliverable_modal(project_id, users):
    cfg = get_settings()
    type_options = [
        s["name"].strip()
        for s in parse_deliverable_tag_styles(cfg.get("deliverable_tag_styles"), fallback_to_default=False)
        if str(s.get("name", "")).strip()
    ]
    if not type_options:
        raw_types = cfg.get("deliverable_types")
        if isinstance(raw_types, str):
            try:
                parsed = json.loads(raw_types)
                if isinstance(parsed, list):
                    type_options = [str(v).strip() for v in parsed if str(v).strip()]
            except Exception:
                type_options = []
    if not type_options:
        type_options = ["paper", "layout", "prototype"]

    numbered = K.numbering_available()
    used = K.used_deliverable_nos(project_id) if numbered else set()
    with st.form("new_deliv_form"):
        if numbered:
            c_no, c_name = st.columns([1, 4])
            with c_no:
                code_no = st.number_input(
                    "No.", min_value=1, step=1, value=K.next_free(used),
                    help="Proposed: the first free number. Any free number is accepted.")
            with c_name:
                name = st.text_input("Deliverable Name*")
        else:
            code_no, name = None, st.text_input("Deliverable Name*")
        type_val = st.selectbox("Type", type_options)
        deadline = st.date_input("Deadline", value=None, format="DD/MM/YYYY")
        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me = st.session_state.get('user_email')
        owner = st.selectbox(
            "Owner*",
            list(user_opts.keys()),
            index=list(user_opts.values()).index(me) if me in user_opts.values() else 0,
        )
        supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
        description = markdown_editor(
            value="",
            key=f"new_deliv_notes_{project_id}",
            height=220,
            label="📝 Deliverable Description",
        )
        if st.form_submit_button("Create Deliverable", type="primary"):
            if not name:
                st.error("Name is required.")
                return
            if numbered:
                err = K.check_free(code_no, used)
                if err:
                    st.error(err)
                    return
            try:
                supabase.table("deliverables").insert({
                    **({"code_no": int(code_no)} if numbered else {}),
                    "project_id": project_id, "name": name, "type": type_val,
                    "status": "Not started",
                    "deadline": str(deadline) if deadline else None,
                    "owner_email": user_opts[owner],
                    "supervisor_email": user_opts[supervisor] if supervisor != "None" else None,
                    "description": description or None,
                }).execute()
                # reset editor state for next open
                st.session_state.pop(f"__mde_new_deliv_notes_{project_id}", None)
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

        numbered = K.numbering_available()
        if numbered:
            proposed = K.next_free(K.used_task_nos(project_id, prefill_deliverable_id))
            c_deliv, c_no = st.columns([4, 1])
            with c_deliv:
                sel_deliv = st.selectbox(
                    "Link to Deliverable",
                    list(deliv_options.keys()),
                    index=list(deliv_options.keys()).index(prefill_name)
                )
            with c_no:
                code_no = st.number_input(
                    "No.", min_value=1, step=1, value=proposed,
                    help="Number within the deliverable (tasks without one are E.0.n). "
                         "Proposed: the first free. If you change deliverable and keep "
                         "this proposal, the first free number there is used.")
        else:
            proposed = code_no = None
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
            deadline   = st.date_input("Deadline", value=None, format="DD/MM/YYYY")

        notes = markdown_editor(
            value="",
            key=f"new_task_notes_{project_id}",
            height=280,
            label="📝 Notes / Description",
        )

        if st.form_submit_button("Create Task", type="primary"):
            if not name:
                st.error("Title is required.")
                return
            chosen_no = None
            if numbered:
                parent = deliv_options[sel_deliv]
                used = K.used_task_nos(project_id, parent)
                chosen_no = int(code_no)
                if parent != prefill_deliverable_id and chosen_no == proposed:
                    chosen_no = K.next_free(used)      # the proposal belonged elsewhere
                err = K.check_free(chosen_no, used)
                if err:
                    st.error(err)
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
                **({"code_no": chosen_no} if chosen_no else {}),
            }
            try:
                res   = supabase.table("tasks").insert(new_task).execute()
                t_id  = res.data[0]['id']
                p_res = supabase.table("projects").select("identifier, name").eq("id", project_id).execute()
                seq_id = None
                if numbered and K.resync_project(project_id):
                    row = supabase.table("tasks").select("sequence_id").eq("id", t_id).execute().data
                    seq_id = row[0].get("sequence_id") if row else None
                if not seq_id:   # project without a letter yet: legacy identifier
                    ident = (p_res.data[0]['identifier'] if p_res.data and p_res.data[0]['identifier'] else "TSK")
                    seq_id = f"{ident}-{t_id}"
                    supabase.table("tasks").update({"sequence_id": seq_id}).eq("id", t_id).execute()

                log_status_change(
                    "task", t_id, project_id, None, "Not started",
                    st.session_state.get("user_email"),
                )

                # Notify owner and supervisor
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                proj_name = p_res.data[0].get("name", "") if p_res.data else ""
                enriched_task = {**new_task, "id": t_id, "sequence_id": seq_id, "project_name": proj_name}
                owner_email = user_opts[owner]
                sup_email   = user_opts[supervisor] if supervisor != "None" else None
                send_task_assigned(enriched_task, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(enriched_task, sup_email, assigner)

                # clear task notes editor after successful creation
                st.session_state.pop(f"__mde_new_task_notes_{project_id}", None)
                st.success("Created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


@st.dialog("Add Subtask")
def add_subtask_modal(task_id, users):
    numbered = K.numbering_available()
    used = K.used_subtask_nos(task_id) if numbered else set()
    with st.form("new_subtask_form"):
        if numbered:
            c_no, c_name = st.columns([1, 4])
            with c_no:
                code_no = st.number_input("No.", min_value=1, step=1, value=K.next_free(used),
                                          help="Number within the task. Any free number is accepted.")
            with c_name:
                name = st.text_input("Subtask Title*")
        else:
            code_no, name = None, st.text_input("Subtask Title*")
        user_opts = {f"{u['name']} ({u['email']})": u['email'] for u in users}
        me        = st.session_state.get('user_email')

        c1, c2 = st.columns(2)
        with c1:
            owner      = st.selectbox("Owner*", list(user_opts.keys()),
                                       index=list(user_opts.values()).index(me) if me in user_opts.values() else 0)
        with c2:
            supervisor = st.selectbox("Supervisor", ["None"] + list(user_opts.keys()))
        deadline = st.date_input("Deadline", value=None, format="DD/MM/YYYY")

        notes = markdown_editor(
            value="",
            key=f"new_subtask_notes_{task_id}",
            height=280,
            label="📝 Notes / Description",
        )

        if st.form_submit_button("Create Subtask", type="primary"):
            if not name:
                st.error("Title is required.")
                return
            if numbered:
                err = K.check_free(code_no, used)
                if err:
                    st.error(err)
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
                    "notes":            notes,
                    "sort_order":       999,
                    **({"code_no": int(code_no)} if numbered else {}),
                }).execute()

                sub_seq = None
                if res.data:
                    parent_rows = supabase.table("tasks").select("project_id").eq(
                        "id", task_id
                    ).execute().data
                    if numbered and parent_rows and K.resync_project(parent_rows[0].get("project_id")):
                        r = supabase.table("subtasks").select("sequence_id").eq(
                            "id", res.data[0]["id"]).execute().data
                        sub_seq = r[0].get("sequence_id") if r else None
                    log_status_change(
                        "subtask", res.data[0]["id"],
                        parent_rows[0].get("project_id") if parent_rows else None,
                        None, "Not started",
                        st.session_state.get("user_email"),
                    )

                # Notify owner and supervisor
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                subtask_as_task = {
                    "id": res.data[0]["id"] if res.data else 0,
                    "sequence_id": sub_seq or (f"SUB-{res.data[0]['id']}" if res.data else ""),
                    "name": name,
                    "deadline": str(deadline) if deadline else None,
                    "priority": "none",
                    "project_name": "",
                }
                send_task_assigned(subtask_as_task, owner_email, assigner)
                if sup_email and sup_email != owner_email:
                    send_task_assigned(subtask_as_task, sup_email, assigner)

                # clear subtask notes editor after successful creation
                st.session_state.pop(f"__mde_new_subtask_notes_{task_id}", None)
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
            numbered   = K.numbering_available()
            taken      = K.taken_letters() if numbered else {}
            if numbered:
                letter_sel = st.selectbox(
                    "Project letter", ["Auto (from the acronym)"]
                    + [ch for ch in K.LETTERS if ch not in taken],
                    help="Codes become E.1 (deliverable), E.1.2 (task), E.1.2.1 (subtask). "
                         "One letter per active project; archiving frees it. In use: "
                         + (", ".join(f"{k} {v}" for k, v in sorted(taken.items())) or "none"))
            else:
                letter_sel = None
        with c2:
            start_date = st.date_input("Start Date", value=_dt.date.today(), format="DD/MM/YYYY")
            end_date   = st.date_input("Estimated End Date", value=None, format="DD/MM/YYYY")
        funding = st.text_input("Funding Agency")
        description = markdown_editor(
            value="",
            key="new_proj_notes",
            height=220,
            label="📝 Project Description (optional)",
        )

        if st.form_submit_button("Create Project", type="primary"):
            if not name:
                st.error("Name is required.")
                return
            letter = None
            if numbered:
                letter = (K.propose_letter({"acronym": acronym, "name": name}, taken)
                          if letter_sel.startswith("Auto") else letter_sel)
                if not letter:
                    st.error("Every letter is in use by an active project: archive one first.")
                    return
            try:
                supabase.table("projects").insert({
                    "name":            name,
                    "acronym":         acronym,
                    # legacy text id, still shown in a few reports
                    "identifier":      (acronym or name).upper()[:12],
                    **({"code_letter": letter} if letter else {}),
                    "funding_agency":  funding,
                    "description":     description or None,
                    "start_date":      str(start_date) if start_date else None,
                    "end_date":        str(end_date) if end_date else None,
                    "is_archived":     False,
                }).execute()
                # clear project description editor after successful creation
                st.session_state.pop("__mde_new_proj_notes", None)
                st.success("Project created!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


# ─── Task row renderer ──────────────────────────────────────────────────────────

def _parse_date(value: str | None) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _deadline_window_days(scope: str | None) -> int | None:
    mapping = {
        "week": 7,
        "month": 30,
    }
    return mapping.get(scope or "")


def _matches_people(item: dict, owner_email: str | None, supervisor_email: str | None) -> bool:
    if owner_email and item.get("owner_email") != owner_email:
        return False
    if supervisor_email and item.get("supervisor_email") != supervisor_email:
        return False
    return True


def _matches_deadline(item: dict, deadline_days: int | None) -> bool:
    if deadline_days is None:
        return True
    dl = _parse_date(item.get("deadline"))
    if not dl:
        return False
    delta = (dl - _dt.date.today()).days
    return 0 <= delta <= deadline_days


def _apply_projects_filters(
    projects: list[dict],
    deliverables: list[dict],
    tasks: list[dict],
    subtasks: list[dict],
    *,
    is_admin: bool,
    owner_email: str | None = None,
    supervisor_email: str | None = None,
    deadline_scope: str | None = None,
):
    deadline_days = _deadline_window_days(deadline_scope)
    owner_filter = owner_email if is_admin else None
    supervisor_filter = supervisor_email if is_admin else None

    def _task_visible(task: dict) -> bool:
        return _matches_people(task, owner_filter, supervisor_filter) and _matches_deadline(task, deadline_days)

    def _subtask_visible(subtask: dict) -> bool:
        return _matches_people(subtask, owner_filter, supervisor_filter) and _matches_deadline(subtask, deadline_days)

    visible_subtask_ids = {s["id"] for s in subtasks if s.get("id") is not None and _subtask_visible(s)}
    visible_task_ids = {
        t["id"]
        for t in tasks
        if t.get("id") is not None and (
            _task_visible(t)
            or any(s.get("task_id") == t.get("id") for s in subtasks if s.get("id") in visible_subtask_ids)
        )
    }
    visible_deliv_ids = {
        d["id"]
        for d in deliverables
        if d.get("id") is not None and any(t.get("deliverable_id") == d.get("id") for t in tasks if t.get("id") in visible_task_ids)
    }
    visible_project_ids = {
        t.get("project_id")
        for t in tasks
        if t.get("id") in visible_task_ids and t.get("project_id") is not None
    }

    filtered_projects = [p for p in projects if p.get("id") in visible_project_ids]
    filtered_deliverables = [d for d in deliverables if d.get("id") in visible_deliv_ids]
    filtered_tasks = [t for t in tasks if t.get("id") in visible_task_ids]
    filtered_subtasks = [s for s in subtasks if s.get("task_id") in visible_task_ids]

    return filtered_projects, filtered_deliverables, filtered_tasks, filtered_subtasks


def _is_projects_filter_active(*, is_admin: bool, owner_email: str | None, supervisor_email: str | None, deadline_scope: str | None) -> bool:
    """Return True when at least one Projects filter is actively restricting the view."""
    people_filter_active = is_admin and (owner_email is not None or supervisor_email is not None)
    deadline_filter_active = deadline_scope is not None
    return people_filter_active or deadline_filter_active


def _get_projects_filter_signature(*, is_admin: bool, owner_email: str | None, supervisor_email: str | None, deadline_scope: str | None) -> tuple:
    """Build a stable signature used to detect filter changes across reruns."""
    return (is_admin, owner_email, supervisor_email, deadline_scope)


def _row_actions(n: int = 3):
    """Fixed icon slots, so every row's buttons line up in the same column."""
    return st.columns(n, gap="small")


def _confirm_delete(kind: str, item: dict, key_prefix: str) -> None:
    """Inline confirmation under the row. Deletion is permanent (and for a
    task it takes the subtasks with it), so it is one click to ask, one to do."""
    i_id = item["id"]
    confirm_key = f"_confirm_del_{kind[0]}_{i_id}"
    if not st.session_state.get(confirm_key):
        return
    what = "task and its subtasks" if kind == "task" else "subtask"
    st.warning(f"Permanently delete the {what} **{item.get('name')}**? This cannot be undone.")
    c1, c2, _ = st.columns([1.4, 1.2, 7])
    with c1:
        if st.button("Yes, delete", key=f"{key_prefix}_delyes_{kind}_{i_id}", type="primary"):
            if kind == "task":
                delete_task_cascade(i_id)
            else:
                supabase.table("subtasks").delete().eq("id", i_id).execute()
            st.session_state.pop(confirm_key, None)
            st.rerun()
    with c2:
        if st.button("Cancel", key=f"{key_prefix}_delno_{kind}_{i_id}"):
            st.session_state.pop(confirm_key, None)
            st.rerun()


def _render_task_row(t, subtasks, users, user_map, user_email, is_admin, key_prefix,
                     threshold: int, show_done: bool = True, codes: dict | None = None):
    """A task and its subtasks, in the shared row style (utils/rows.py)."""
    t_id = t["id"]
    can_edit = is_admin or t.get("owner_email") == user_email \
        or t.get("supervisor_email") == user_email
    readonly = not can_edit

    c_row, c_act = st.columns(ROW_COLS, vertical_alignment="center")
    with c_row:
        st.html(row_html(t, kind="task", user_map=user_map, threshold=threshold,
                         readonly=readonly, code=(codes or {}).get(("t", t_id))))
    with c_act:
        if not readonly:
            a_det, a_sub, a_del = _row_actions()
            with a_det:
                if st.button("✏️", key=f"{key_prefix}_det_{t_id}", type="tertiary",
                             help="Details and edit"):
                    task_details_modal(t, can_edit)
            with a_sub:
                if st.button("➕", key=f"{key_prefix}_addsub_{t_id}", type="tertiary",
                             help="Add a subtask"):
                    add_subtask_modal(t_id, users)
            with a_del:
                if is_admin and st.button("🗑️", key=f"{key_prefix}_delx_{t_id}",
                                          type="tertiary", help="Delete permanently"):
                    st.session_state[f"_confirm_del_t_{t_id}"] = True
                    st.rerun()
    _confirm_delete("task", t, key_prefix)

    t_subs = [s for s in subtasks if s.get("task_id") == t_id]
    if not show_done:
        t_subs = [s for s in t_subs if (s.get("status") or "") not in INACTIVE]
    for s in urgency_sort(t_subs, threshold):
        s_id = s["id"]
        s_can_edit = is_admin or s.get("owner_email") == user_email \
            or s.get("supervisor_email") == user_email
        s_readonly = not s_can_edit
        sc_row, sc_act = st.columns(ROW_COLS, vertical_alignment="center")
        with sc_row:
            st.html(row_html(s, kind="subtask", user_map=user_map, threshold=threshold,
                             readonly=s_readonly, code=(codes or {}).get(("s", s_id))))
        with sc_act:
            if not s_readonly:
                a_det, _a_gap, a_del = _row_actions()
                with a_det:
                    if st.button("✏️", key=f"{key_prefix}_vistaS_{s_id}", type="tertiary",
                                 help="Details and edit"):
                        subtask_details_modal(s, s_can_edit)
                with a_del:
                    if is_admin and st.button("🗑️", key=f"{key_prefix}_sdelx_{s_id}",
                                              type="tertiary", help="Delete permanently"):
                        st.session_state[f"_confirm_del_s_{s_id}"] = True
                        st.rerun()
        _confirm_delete("subtask", s, key_prefix)


# ─── Review queue ("To review") ─────────────────────────────────────────────────

_REVIEW_CSS = """
<style>
/* the "[" that groups a deliverable's closed work */
div[class*="st-key-rvgrp_"] {
    position: relative; border-left: 2px solid #AEB4BB;
    padding-left: 10px; margin: 2px 0 12px 4px;
}
div[class*="st-key-rvgrp_"]::before, div[class*="st-key-rvgrp_"]::after {
    content: ""; position: absolute; left: -2px; width: 9px;
    border-top: 2px solid #AEB4BB;
}
div[class*="st-key-rvgrp_"]::before { top: 0; }
div[class*="st-key-rvgrp_"]::after  { bottom: 0; }
/* compact rows: the checkbox must not add height */
div[class*="st-key-rvgrp_"] div[data-testid='stCheckbox'] { min-height: 0; margin: 0; }
div[class*="st-key-rvgrp_"] div[data-testid='stHorizontalBlock']:has(.maic-row) {
    padding-top: 0 !important; padding-bottom: 0 !important;
}
/* reopen: a bigger, unmistakable icon */
div[class*="st-key-rv_reopen_"] button { height: 26px !important; }
div[class*="st-key-rv_reopen_"] button, div[class*="st-key-rv_reopen_"] button * {
    font-size: 1.45rem !important; line-height: 1 !important;
}
</style>
"""


def _rv_key(it: dict) -> str:
    return f"{it['_kind']}_{it['id']}"


def _rv_set_all(keys: list[str]) -> None:
    """Select-all callback: runs before the rerun, so the row boxes follow."""
    value = bool(st.session_state.get("rv_sel_all"))
    for k in keys:
        st.session_state[f"rv_sel_{k}"] = value


def _render_review(queue: dict, user_email: str, is_admin: bool, users: list) -> None:
    """What the supervisor has to look at before it disappears into the archive:
    deliverables awaiting sign-off, and work others have declared closed,
    grouped project → deliverable."""
    from db import archive_items, reopen_item
    from utils.modals import render_signoff_panel
    from utils.notifications import send_item_reopened

    st.markdown(_REVIEW_CSS, unsafe_allow_html=True)
    names = {u["email"]: u.get("name") or u["email"] for u in users if u.get("email")}
    me = st.session_state.get("user_name") or names.get(user_email, user_email)
    pending, items = queue.get("deliverables", []), queue.get("items", [])

    if not pending and not items:
        st.success("Nothing to review. Deliverables awaiting your sign-off and work "
                   "closed under your supervision will appear here.")
        return

    # ── 1 · deliverables awaiting sign-off ───────────────────────────────────
    st.markdown(f"#### ⏳ Deliverables awaiting your sign-off · {len(pending)}")
    if not pending:
        st.caption("None right now.")
    else:
        st.caption("Approving a deliverable also archives its closed tasks and subtasks. "
                   "It cannot be approved while any of its work is still open.")
    for d in pending:
        with st.container(border=True):
            req = names.get(d.get("completion_requested_by"), d.get("completion_requested_by") or "?")
            st.html(
                "<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
                f"{project_chip(d.get('_project'))}"
                f"<span style='font-size:14px;font-weight:700'>{esc(d.get('name', ''))}</span>"
                f"<span style='font-size:12px;color:#5F6368'>asked by {esc(req)} · "
                f"deadline {fmt(d.get('deadline'))}</span></div>"
            )
            render_signoff_panel(d, True, names)

    # ── 2 · closed work, grouped project → deliverable ───────────────────────
    st.write("")
    n_t = len([i for i in items if i["_kind"] == "task"])
    st.markdown(f"#### ✅ Closed work to review · {len(items)}")
    st.caption(
        f"{n_t} tasks, {len(items) - n_t} subtasks closed under your supervision and not "
        "archived yet. Tick what you have checked and archive it; ↩️ sends one item back "
        "to its owner; ✏️ opens its details."
    )
    if not items:
        st.caption("None right now.")
        return

    keys = [_rv_key(it) for it in items]
    selected = [it for it in items if st.session_state.get(f"rv_sel_{_rv_key(it)}")]
    b1, b2, _ = st.columns([1.6, 2.2, 6], vertical_alignment="center")
    with b1:
        st.checkbox(f"Select all ({len(items)})", key="rv_sel_all",
                    on_change=_rv_set_all, args=(keys,))
    with b2:
        if st.button(f"🗄️ Archive selected ({len(selected)})", key="rv_arch_sel",
                     type="primary", disabled=not selected, use_container_width=True):
            n_tasks, n_subs = archive_items(selected)
            for it in selected:
                st.session_state.pop(f"rv_sel_{_rv_key(it)}", None)
            st.session_state.pop("rv_sel_all", None)
            st.toast(f"Archived {n_tasks} tasks and {n_subs} subtasks.")
            st.rerun()

    # project → deliverable, projects by name, deliverables by name, loose tasks last
    groups: dict = {}
    for it in items:
        pkey = (it.get("_project_name") or "~", it.get("_project_id"))
        dkey = (it.get("_deliv_id") is None, it.get("_deliv_name") or "", it.get("_deliv_id"))
        groups.setdefault(pkey, {}).setdefault(dkey, []).append(it)

    for (pname, pid), dgroups in sorted(groups.items(), key=lambda kv: kv[0][0].lower()):
        first = next(iter(dgroups.values()))[0]
        st.html(
            "<div style='display:flex;align-items:center;gap:8px;margin:14px 0 4px 0'>"
            f"{project_chip(first.get('_project'))}"
            f"<span style='font-size:15px;font-weight:700;color:#202124'>{esc(pname.strip('~'))}</span>"
            "</div>"
        )
        for (loose, dname, did), group in sorted(dgroups.items(), key=lambda kv: kv[0][:2]):
            with st.container(key=f"rvgrp_{pid}_{did or 'none'}", gap=None):
                if loose:
                    title = ("<span style='font-size:11px;font-weight:700;letter-spacing:0.05em;"
                             "color:#5F6368'>TASKS WITHOUT DELIVERABLE</span>")
                else:
                    g0 = group[0]
                    extra = ""
                    if g0.get("_deliv_pending"):
                        extra = chip("⏳ awaiting sign-off", "#8A5300", "#FFF1D6")
                    elif g0.get("_deliv_status"):
                        extra = status_chip(g0["_deliv_status"])
                    title = ("<span style='font-size:10px;color:#2E8B6E;font-weight:700;"
                             "letter-spacing:0.05em'>DELIVERABLE</span> "
                             f"<span style='font-size:13.5px;font-weight:700;color:#0F4D3B'>"
                             f"{esc(dname)}</span> {extra}")
                st.html(f"<div style='display:flex;align-items:center;gap:6px;"
                        f"flex-wrap:wrap;padding:2px 0 4px 0'>{title}</div>")

                for it in sorted(group, key=lambda i: i.get("_closed") or "9999"):
                    key = _rv_key(it)
                    c_sel, c_row, c_edit, c_back = st.columns(
                        [0.45, 12, 0.7, 0.8], vertical_alignment="center", gap="small")
                    with c_sel:
                        st.checkbox("Select", key=f"rv_sel_{key}",
                                    label_visibility="collapsed")
                    with c_row:
                        st.html(row_html(
                            it, kind=it["_kind"], user_map=names, path=it.get("_path") or None,
                            strike_done=False, flat=True,
                            date_html=(f"<span style='font-size:12px;color:#5F6368'>"
                                       f"{fmt(it.get('_closed'))}</span>"),
                        ))
                    with c_edit:
                        if st.button("✏️", key=f"rv_edit_{key}", type="tertiary",
                                     help="Details and edit"):
                            if it["_kind"] == "task":
                                task_details_modal(it, True)
                            else:
                                subtask_details_modal(it, True)
                    with c_back:
                        if st.button("↩️", key=f"rv_reopen_{key}", type="tertiary",
                                     help="Reopen: back to 'Working on', owner notified"):
                            st.session_state[f"_rv_reopen_{key}"] = True
                            st.rerun()

                    if st.session_state.get(f"_rv_reopen_{key}"):
                        owner = it.get("owner_email")
                        notify = bool(owner and owner != user_email)
                        r1, r2, r3 = st.columns([6, 1.9, 1.1], vertical_alignment="bottom")
                        with r1:
                            reason = st.text_input(
                                "What still needs work? (optional, sent to the owner)"
                                if notify else "What still needs work? (optional)",
                                key=f"rv_reason_{key}",
                            )
                        with r2:
                            if st.button("↩️ Reopen and notify" if notify else "↩️ Reopen",
                                         key=f"rv_reopen_yes_{key}", type="primary",
                                         use_container_width=True):
                                ok, err = reopen_item(it, user_email)
                                if not ok:
                                    st.error(f"Could not reopen: {err}")
                                else:
                                    if notify:
                                        try:
                                            send_item_reopened(it, owner, me, reason)
                                        except Exception as exc:
                                            print(f"[projects.review] reopen mail failed: {exc}")
                                    st.session_state.pop(f"_rv_reopen_{key}", None)
                                    st.session_state.pop(f"rv_sel_{key}", None)
                                    st.rerun()
                        with r3:
                            if st.button("Cancel", key=f"rv_reopen_no_{key}",
                                         use_container_width=True):
                                st.session_state.pop(f"_rv_reopen_{key}", None)
                                st.rerun()


# ─── Project header ─────────────────────────────────────────────────────────────

def _render_letters_prompt(projects: list[dict], is_admin: bool) -> None:
    """Codes need a project letter. Say so where the codes are missing — here —
    and let an admin assign the proposed letters in one click."""
    if not K.numbering_available():
        if is_admin:
            st.info("Codes like E.1.2 appear once the **Readable codes** migration has "
                    "run: Admin Panel → Settings → Database schema.")
        return
    active = [p for p in projects if not p.get("is_archived")]
    missing = [p for p in active if not p.get("code_letter")]
    if not missing or not is_admin:
        return
    # propose against ALL active projects, not only the ones on screen
    try:
        everyone = supabase.table("projects").select("*").eq("is_archived", False).execute().data or []
    except Exception:
        everyone = active
    proposal = K.propose_all(everyone)
    names = ", ".join(f"**{proposal.get(p['id'], '?')}** {p.get('acronym') or p.get('name')}"
                      for p in missing)
    c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
    with c1:
        st.warning(f"{len(missing)} project(s) have no letter, so their work has no code yet. "
                   f"Proposal: {names}. You can change them later in Admin Panel → Projects.")
    with c2:
        if st.button("Assign letters", key="tree_assign_letters", type="primary",
                     use_container_width=True):
            for pid, ch in proposal.items():
                try:
                    supabase.table("projects").update({"code_letter": ch}).eq("id", pid).execute()
                    K.resync_project(pid)
                except Exception as exc:
                    st.error(f"{ch}: {exc}")
            st.rerun()


def _toggle_project(pid: int) -> None:
    """Runs before the rerun, so the header already shows the new state."""
    state = st.session_state.setdefault("_proj_open", {})
    state[pid] = not state.get(pid, False)


def _shade(hex_colour: str) -> str:
    """Readable text colour from a type colour (kept as is: they are dark)."""
    return hex_colour if hex_colour and hex_colour.startswith("#") else "#3C4043"


# The project title is a tab sitting on the project box (open), or a closed
# pill. The title row stays as low as a line of text: app.py pads every
# column block by 10px and buttons default to ~40px.
_PROJECT_HEAD_CSS = """
<style>
div[class*="st-key-projhead_"] div[data-testid='stHorizontalBlock'] {
    padding-top: 0 !important; padding-bottom: 0 !important;
    background: transparent !important; font-weight: normal !important;
}
div[class*="st-key-projhead_"] button {
    min-height: 0 !important; height: 28px; padding: 0 6px !important;
}
div[class*="st-key-projhead_"] button p { font-size: 0.85rem; white-space: nowrap; }
div[class*="st-key-projtgl_"] button {
    height: 32px !important; padding: 0 14px !important; justify-content: flex-start;
    background: #FFFFFF !important; border: 1px solid #C9CED4 !important;
}
div[class*="st-key-projtgl_o_"] button {
    border-bottom: 1px solid #FAFBFC !important; border-radius: 8px 8px 0 0 !important;
    margin-bottom: -1px; position: relative; z-index: 2; background: #FAFBFC !important;
}
div[class*="st-key-projtgl_c_"] button { border-radius: 8px !important; }
div[class*="st-key-projtgl_"] button p {
    font-size: 0.98rem !important; color: #202124;
}
</style>
"""


# ─── Main view ──────────────────────────────────────────────────────────────────

def show_projects():
    st.title("Projects")
    st.caption(
        "The full work breakdown: project → deliverable → task → subtask. "
        "Create and organise here; the **Dashboard** tells you what is urgent."
    )

    user_email = st.session_state.get('user_email')
    is_admin   = st.session_state.get('user_role') == 'admin'

    col_tools, c_scope, c_actions = st.columns([1.4, 2.2, 2.2])
    with col_tools:
        if is_admin:
            if st.button("➕ New Project", type="primary", use_container_width=True):
                add_project_modal()
    with c_scope:
        if is_admin:
            show_all = st.checkbox(
                "All tasks and projects",
                value=False,
                key="proj_show_all",
                help="Unchecked (default): only tasks where you are the owner or the supervisor.",
            )
        else:
            # Non-admins are already scoped to the projects they are involved in.
            show_all = True
    with c_actions:
        a_exp, a_col, a_arch = st.columns([1.0, 1.0, 1.3])
        with a_exp:
            if st.button("Expand all", key="proj_expand_all", use_container_width=True):
                st.session_state["_projects_expand_mode"] = "all"
                st.rerun()
        with a_col:
            if st.button("Collapse all", key="proj_collapse_all", use_container_width=True):
                st.session_state["_projects_expand_mode"] = "none"
                st.rerun()
        with a_arch:
            show_archived = st.checkbox("Show Archived", value=False)

    # ── Tree / To review ─────────────────────────────────────────────────────
    from db import get_review_queue
    queue = get_review_queue(user_email, is_admin)
    n_review = len(queue["deliverables"]) + len(queue["items"])
    v_col, d_col = st.columns([3, 5], vertical_alignment="center")
    with v_col:
        view = st.segmented_control(
            "View", ["tree", "review"], default="tree", key="proj_view",
            format_func=lambda v: "🌳 Tree" if v == "tree" else f"🔍 To review · {n_review}",
            label_visibility="collapsed",
        ) or "tree"
    with d_col:
        show_done = True
        if view == "tree":
            show_done = st.checkbox("Show completed", value=True, key="proj_show_done",
                                    help="Completed and cancelled items, struck through.")

    projects, deliverables, tasks, subtasks, users, user_map = fetch_hierarchy(
        show_archived,
        user_email=user_email,
        is_admin=is_admin,
        only_mine=is_admin and not show_all,
    )

    if view == "review":
        _render_review(queue, user_email, is_admin, users)
        return

    only_mine = is_admin and not show_all
    if only_mine:
        st.caption("Showing only tasks where you are owner or supervisor.")

    # deadline urgency threshold from settings
    try:
        settings = get_settings()
        threshold = int(settings.get("expiring_threshold_days", 7))
    except Exception:
        settings = {}
        threshold = 7

    if not projects:
        if only_mine:
            st.info(
                "You have no tasks assigned to you as owner or supervisor. "
                "Tick **All tasks and projects** to see everything."
            )
        else:
            st.info("No active tasks found. Create a new task to get started.")
        return

    user_labels = [f"{u['name']} ({u['email']})" for u in users if u.get("email")]
    user_label_to_email = {f"{u['name']} ({u['email']})": u["email"] for u in users if u.get("email")}

    with st.expander("⚙️ View filters", expanded=False):
        if is_admin:
            c_owner, c_sup, c_dead, c_export = st.columns([2.1, 2.1, 1.4, 1.6])
            with c_owner:
                owner_label = st.selectbox(
                    "Owner",
                    ["All owners"] + user_labels,
                    key="proj_filter_owner",
                )
            with c_sup:
                supervisor_label = st.selectbox(
                    "Supervisor",
                    ["All supervisors"] + user_labels,
                    key="proj_filter_supervisor",
                )
        else:
            c_dead, c_export = st.columns([2.0, 1.6])
            owner_label = "All owners"
            supervisor_label = "All supervisors"

        with c_dead:
            deadline_label = st.selectbox(
                "Deadline",
                ["All deadlines", "Within a week", "Within a month"],
                key="proj_filter_deadline",
            )

        owner_email = user_label_to_email.get(owner_label) if is_admin and owner_label != "All owners" else None
        supervisor_email = user_label_to_email.get(supervisor_label) if is_admin and supervisor_label != "All supervisors" else None
        deadline_scope = {
            "Within a week": "week",
            "Within a month": "month",
        }.get(deadline_label)
        filters_active = _is_projects_filter_active(
            is_admin=is_admin,
            owner_email=owner_email,
            supervisor_email=supervisor_email,
            deadline_scope=deadline_scope,
        )
        filter_signature = _get_projects_filter_signature(
            is_admin=is_admin,
            owner_email=owner_email,
            supervisor_email=supervisor_email,
            deadline_scope=deadline_scope,
        )

        prev_signature = st.session_state.get("_projects_last_filter_signature")
        if prev_signature is None:
            st.session_state["_projects_last_filter_signature"] = filter_signature
            st.session_state.setdefault("_projects_expand_all_once", False)
        elif prev_signature != filter_signature:
            st.session_state["_projects_last_filter_signature"] = filter_signature
            st.session_state["_projects_expand_all_once"] = filters_active

        filtered_projects, filtered_deliverables, filtered_tasks, filtered_subtasks = _apply_projects_filters(
            projects,
            deliverables,
            tasks,
            subtasks,
            is_admin=is_admin,
            owner_email=owner_email,
            supervisor_email=supervisor_email,
            deadline_scope=deadline_scope,
        )

        with c_export:
            pdf_buf = generate_projects_pdf(
                filtered_projects,
                filtered_deliverables,
                filtered_tasks,
                filtered_subtasks,
                users,
            )
            st.download_button(
                "📄 Export PDF",
                data=pdf_buf,
                file_name=f"projects_view_{_dt.date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        if is_admin:
            st.caption("Admins can filter by owner and supervisor. Everyone can filter by deadline.")
        else:
            st.caption("You can filter the view by deadline.")

    if filters_active:
        st.caption("🔎 Filters are active — some projects may be hidden.")

    projects = filtered_projects
    deliverables = filtered_deliverables
    tasks = filtered_tasks
    subtasks = filtered_subtasks
    # Progress bars count every task of a deliverable, even when the completed
    # ones are hidden from the list below.
    all_tasks = tasks
    if not show_done:
        tasks = [t for t in tasks if (t.get("status") or "") not in INACTIVE]

    # Open/closed state per project. Not an st.expander: its title cannot hold
    # widgets, and the project actions belong on the title row. A one-shot
    # mode (Expand/Collapse all, or a filter change) overrides every project.
    open_state = st.session_state.setdefault("_proj_open", {})
    mode = st.session_state.pop("_projects_expand_mode", None)
    if st.session_state.pop("_projects_expand_all_once", False):
        mode = "all"
    if mode in ("all", "none"):
        for proj in projects:
            open_state[proj["id"]] = mode == "all"

    st.markdown(_PROJECT_HEAD_CSS, unsafe_allow_html=True)
    st.markdown(PROJECT_BOX_CSS, unsafe_allow_html=True)
    _render_letters_prompt(projects, is_admin)
    with st.container(key="treehead"):
        hc, _ = st.columns(ROW_COLS)
        with hc:
            st.html(header_html(first_label="Code · task"))
    type_colour = type_colours(settings)

    for proj in projects:
        proj_id   = proj["id"]
        proj_name = proj.get("name", "Project")
        acronym   = proj.get("acronym", "")
        letter    = proj.get("code_letter") or ""
        arch_tag  = "  · _archived_" if proj.get("is_archived") else ""
        is_open   = bool(open_state.get(proj_id, False))
        state     = "o" if is_open else "c"

        with st.container(key=f"projwrap_{proj_id}", gap=None):
            # ── Title: a tab sitting on the box, actions on the right ────────
            with st.container(key=f"projhead_{proj_id}"):
                h_title, h_actions = st.columns([6, 4], vertical_alignment="bottom")
                with h_title:
                    badge = f":violet-background[**{letter}**]  " if letter else ""
                    title = (f"**{acronym}** · {proj_name}" if acronym and acronym != proj_name
                             else f"**{proj_name}**")
                    st.button(
                        f"{'▾' if is_open else '▸'}  {badge}{title}{arch_tag}",
                        key=f"projtgl_{state}_{proj_id}", type="tertiary",
                        on_click=_toggle_project, args=(proj_id,),
                    )
                with h_actions:
                    with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
                        if is_admin and st.button("➕ Deliverable", key=f"add_del_{proj_id}",
                                                  type="tertiary"):
                            add_deliverable_modal(proj_id, users)
                        if st.button("➕ Task without deliverable",
                                     key=f"add_generic_t_{proj_id}", type="tertiary"):
                            add_task_modal(proj_id, deliverables, users,
                                           prefill_deliverable_id=None)
            if not is_open:
                continue

            proj_deliverables = sorted(
                [d for d in deliverables if d.get("project_id") == proj_id],
                key=lambda d: (d.get("code_no") is None, d.get("code_no") or 0, d.get("name") or ""))

            # Codes for every row of this project (E.1, E.1.2, E.1.2.1)
            dno = {d["id"]: d.get("code_no") for d in proj_deliverables}
            codes: dict = {}
            proj_tasks = [t for t in all_tasks if t.get("project_id") == proj_id]
            for t in proj_tasks:
                d_no = dno.get(t.get("deliverable_id")) if t.get("deliverable_id") else 0
                codes[("t", t["id"])] = K.fmt(letter, d_no, t.get("code_no"))
                for s in subtasks:
                    if s.get("task_id") == t["id"]:
                        codes[("s", s["id"])] = K.fmt(letter, d_no, t.get("code_no"),
                                                      s.get("code_no"))

            # Card per deliverable, edged and tinted with its type's colour
            css = []
            for d in proj_deliverables:
                c = type_colour.get((d.get("type") or "").strip(), "#5F6368")
                css.append(deliverable_card_css(f"dlv_{d['id']}", c))
            css.append(deliverable_card_css(f"dlv_loose_{proj_id}", "#9AA0A6"))
            st.markdown("<style>" + "".join(css) + "</style>", unsafe_allow_html=True)

            with st.container(key=f"projbox_{proj_id}"):
                # ── One block per deliverable ────────────────────────────────────
                for d in proj_deliverables:
                    d_id = d["id"]
                    d_all = [t for t in all_tasks if t.get("deliverable_id") == d_id]
                    deliv_tasks = urgency_sort(
                        [t for t in tasks if t.get("deliverable_id") == d_id], threshold)

                    d_colour = type_colour.get((d.get("type") or "").strip(), "#5F6368")
                    with st.container(key=f"dlv_{d_id}", gap=None):
                        h_row, h_act = st.columns(ROW_COLS, vertical_alignment="center")
                        with h_row:
                            st.html(deliverable_head_html(
                                d, d_all, user_map, threshold,
                                deliverable_chip_html(d.get('type') or 'generic', settings),
                                code=K.fmt(letter, d.get("code_no")),
                                colour=_shade(d_colour)))
                        with h_act:
                            a_det, _a_gap, a_arch = _row_actions()
                            with a_det:
                                if st.button("✏️", key=f"det_del_{d_id}", type="tertiary",
                                             help="Details, edit and sign-off"):
                                    d_can_edit = (
                                        is_admin
                                        or d.get("owner_email") == user_email
                                        or d.get("supervisor_email") == user_email
                                    ) and not d.get("is_archived")
                                    deliverable_details_modal(d, can_edit=d_can_edit)
                            with a_arch:
                                if is_admin and not d.get("is_archived"):
                                    if st.button("🗑️", key=f"arch_del_{d_id}", type="tertiary",
                                                 help="Archive deliverable"):
                                        supabase.table("deliverables").update(
                                            {"is_archived": True}).eq("id", d_id).execute()
                                        st.rerun()

                        if deliv_tasks:
                            for t in deliv_tasks:
                                _render_task_row(
                                    t, subtasks, users, user_map, user_email, is_admin,
                                    key_prefix=f"d{d_id}", threshold=threshold,
                                    show_done=show_done, codes=codes,
                                )
                        elif d_all:
                            st.caption("All tasks are completed — tick **Show completed** to see them.")
                        else:
                            st.caption("No tasks for this deliverable yet.")

                        if st.button("➕ Add task", key=f"add_dt_{d_id}", type="tertiary"):
                            add_task_modal(proj_id, deliverables, users, prefill_deliverable_id=d_id)

                # ── Tasks without deliverable ────────────────────────────────────
                unassigned = urgency_sort([
                    t for t in tasks
                    if t.get("project_id") == proj_id and not t.get("deliverable_id")
                ], threshold)

                if unassigned:
                    with st.container(key=f"dlv_loose_{proj_id}", gap=None):
                        st.html(loose_band_html(K.fmt(letter, 0), len(unassigned)))
                        for t in unassigned:
                            _render_task_row(
                                t, subtasks, users, user_map, user_email, is_admin,
                                key_prefix=f"p{proj_id}_u", threshold=threshold,
                                show_done=show_done, codes=codes,
                            )

