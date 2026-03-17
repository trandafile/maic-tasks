"""
views/dashboard.py
──────────────────
Dashboard bottom-up: lista piatta di azioni atomiche raggruppate per urgenza.
Due tab: "To Do" (owner) e "To Review" (supervisor, non owner).
"""

import datetime
import streamlit as st
from core.supabase_client import supabase
from utils.modals import task_details_modal, subtask_details_modal, person_pill_html

# ── Costanti badge ────────────────────────────────────────────────────────────
_STATUS_BADGE = {
    "Not started": ("⚪", "#888888"),
    "Working on":  ("🔵", "#1a73e8"),
    "Blocked":     ("🔴", "#d93025"),
    "Completed":   ("🟢", "#188038"),
    "Cancelled":   ("⚫", "#444444"),
}

_PRIORITY_BADGE = {
    "urgent": ("🔴", "Urgent"),
    "high":   ("🟠", "High"),
    "medium": ("🔵", "Medium"),
    "low":    ("🟢", "Low"),
    "none":   ("⚪", "None"),
}

_INACTIVE = {"Completed", "Cancelled"}


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_data():
    """Carica tutti i dati necessari dalla DB in un solo blocco."""
    # Settings
    try:
        s_res = supabase.table("settings").select("expiring_threshold_days").limit(1).execute()
        threshold = s_res.data[0]["expiring_threshold_days"] if s_res.data else 7
    except Exception:
        threshold = 7

    proj_res  = supabase.table("projects").select("id, name, acronym").execute()
    projects  = {p["id"]: p for p in (proj_res.data or [])}

    deliv_res    = supabase.table("deliverables").select("id, project_id, name").execute()
    deliverables = {d["id"]: d for d in (deliv_res.data or [])}

    t_res      = supabase.table("tasks").select("*").eq("is_archived", False).execute()
    all_tasks  = t_res.data or []

    st_res       = supabase.table("subtasks").select("*").eq("is_archived", False).execute()
    all_subtasks = st_res.data or []

    u_res    = supabase.table("users").select("email, name, avatar_color").eq("is_approved", True).execute()
    user_map = {u["email"]: u for u in (u_res.data or [])}

    return threshold, projects, deliverables, all_tasks, all_subtasks, user_map


# ── Leaf-rule builder ─────────────────────────────────────────────────────────

def _build_flat_list(email, mode, all_tasks, all_subtasks):
    """
    Costruisce la lista piatta di foglie per una tab.

    mode = "todo"   → l'utente è owner
    mode = "review" → l'utente è supervisor AND NOT owner

    Restituisce una lista di dict:
        { kind: "task"|"subtask", item: {...}, parent_task: {...}|None,
          suggest_close: bool }
    """
    if mode == "todo":
        user_tasks = [
            t for t in all_tasks
            if t.get("owner_email") == email
            and t.get("status") not in _INACTIVE
        ]
        # subtask attivi assegnati come owner
        user_subtasks_active = [
            s for s in all_subtasks
            if s.get("owner_email") == email
            and s.get("status") not in _INACTIVE
        ]
        # tutti i subtask dell'utente (inclusi completati) per il check "chiudi il task"
        user_subtasks_all = [
            s for s in all_subtasks
            if s.get("owner_email") == email
        ]
    else:
        user_tasks = [
            t for t in all_tasks
            if t.get("supervisor_email") == email
            and t.get("owner_email") != email
            and t.get("status") not in _INACTIVE
        ]
        user_subtasks_active = [
            s for s in all_subtasks
            if s.get("supervisor_email") == email
            and s.get("owner_email") != email
            and s.get("status") not in _INACTIVE
        ]
        user_subtasks_all = user_subtasks_active  # no suggest_close in review

    # Indicizza subtask attivi per task_id
    active_subs_by_task = {}
    for s in user_subtasks_active:
        tid = s.get("task_id")
        active_subs_by_task.setdefault(tid, []).append(s)

    # Indicizza TUTTI i subtask dell'utente per task_id (per suggest_close)
    all_subs_by_task = {}
    for s in user_subtasks_all:
        tid = s.get("task_id")
        all_subs_by_task.setdefault(tid, []).append(s)

    # Mappa id → oggetto task per recuperare il parent_task dei subtask
    tasks_by_id = {t["id"]: t for t in all_tasks}

    result = []

    for task in user_tasks:
        tid = task["id"]
        active_subs = active_subs_by_task.get(tid, [])

        if active_subs:
            # Regola foglia: mostra i subtask, NON il task padre
            for s in active_subs:
                result.append({
                    "kind": "subtask",
                    "item": s,
                    "parent_task": task,
                    "suggest_close": False,
                })
        else:
            # Nessun subtask attivo: mostra il task direttamente
            suggest_close = False
            if mode == "todo":
                all_subs = all_subs_by_task.get(tid, [])
                if all_subs and all(s.get("status") == "Completed" for s in all_subs):
                    suggest_close = True
            result.append({
                "kind": "task",
                "item": task,
                "parent_task": None,
                "suggest_close": suggest_close,
            })

    return result


# ── Helpers UI ────────────────────────────────────────────────────────────────

def _deadline_group(deadline_str, today, threshold):
    """Ritorna ("overdue"|"soon"|"future", html_label)."""
    if not deadline_str:
        return "future", ""
    try:
        dl = datetime.date.fromisoformat(deadline_str)
    except ValueError:
        return "future", ""

    delta = (dl - today).days
    if delta < 0:
        days_str = f"{abs(delta)} day{'s' if abs(delta) != 1 else ''}"
        html = (f"<span style='color:#d93025;font-size:12px;'>"
                f"Overdue by {days_str}</span>")
        return "overdue", html
    elif delta <= threshold:
        days_str = f"{delta} day{'s' if delta != 1 else ''}"
        html = (f"<span style='color:#e37400;font-size:12px;'>"
                f"Due in {days_str}</span>")
        return "soon", html
    else:
        html = (f"<span style='color:#888;font-size:12px;'>"
                f"Due on {dl.strftime('%Y/%m/%d')}</span>")
        return "future", html


def _render_group_header(group_key, count, threshold):
    cfg = {
        "overdue": ("🔴", "Overdue",                        "#d93025"),
        "soon":    ("🟠", f"Due within {threshold} days",   "#e37400"),
        "future":  ("⚫", "Upcoming",                        "#888888"),
    }
    dot, label, color = cfg[group_key]
    st.markdown(
        f"<div style='margin:18px 0 8px;'>"
        f"<span style='font-size:15px;color:{color};'>{dot} <strong>{label}</strong></span>"
        f"&nbsp;&nbsp;<span style='background:{color};color:white;border-radius:10px;"
        f"padding:1px 9px;font-size:12px;font-weight:600;'>{count}</span></div>",
        unsafe_allow_html=True,
    )


def _render_item(entry, projects, deliverables, mode, today, threshold, user_map=None):
    """Renderizza una singola card item + pulsanti azione."""
    kind         = entry["kind"]
    item         = entry["item"]
    parent_task  = entry.get("parent_task")
    suggest_close = entry.get("suggest_close", False)
    item_id      = item["id"]
    unique_key   = f"{mode}_{kind}_{item_id}"

    # ── Breadcrumb ────────────────────────────────────────────────────────────
    if kind == "task":
        proj_id  = item.get("project_id")
        deliv_id = item.get("deliverable_id")
    else:
        proj_id  = parent_task.get("project_id") if parent_task else None
        deliv_id = parent_task.get("deliverable_id") if parent_task else None

    proj         = projects.get(proj_id, {})
    proj_acronym = proj.get("acronym") or proj.get("name", "?")
    deliv        = deliverables.get(deliv_id)
    deliv_name   = deliv["name"] if deliv else "<em>generic task</em>"

    if kind == "subtask" and parent_task:
        breadcrumb = (
            f"<span style='color:#888;font-size:11px;'>"
            f"{proj_acronym} &rsaquo; {deliv_name} &rsaquo; {parent_task.get('name','')}</span>"
        )
    else:
        breadcrumb = (
            f"<span style='color:#888;font-size:11px;'>"
            f"{proj_acronym} &rsaquo; {deliv_name}</span>"
        )

    # ── Badge tipo ───────────────────────────────────────────────────────────
    type_color = "#7c4dff" if kind == "subtask" else "#1a73e8"
    type_label = "subtask"  if kind == "subtask" else "task"
    type_badge = (
        f"<span style='background:{type_color};color:white;border-radius:3px;"
        f"padding:1px 7px;font-size:10px;font-weight:600;margin-right:7px;'>"
        f"{type_label}</span>"
    )

    # ── Badge status ─────────────────────────────────────────────────────────
    status   = item.get("status", "Not started")
    st_icon, st_color = _STATUS_BADGE.get(status, ("⚪", "#888"))
    status_badge = (
        f"<span style='background:{st_color}22;color:{st_color};"
        f"border-radius:3px;padding:2px 8px;font-size:11px;'>"
        f"{st_icon} {status}</span>"
    )

    # ── Badge priority (solo task; subtask non hanno il campo priority) ───────
    prio_badge = ""
    if kind == "task":
        prio = (item.get("priority") or "none").lower()
        prio_icon, prio_lbl = _PRIORITY_BADGE.get(prio, ("⚪", prio.capitalize()))
        prio_badge = (
            f"<span style='background:#f5f5f5;color:#555;border-radius:3px;"
            f"padding:2px 8px;font-size:11px;border:1px solid #ddd;'>"
            f"{prio_icon} {prio_lbl}</span>"
        )

    # ── Badge "chiudi il task" ────────────────────────────────────────────────
    close_badge = ""
    if suggest_close:
        close_badge = (
            "<span style='background:#fff3e0;color:#e65100;border-radius:3px;"
            "padding:2px 9px;font-size:11px;border:1px solid #ffcc80;margin-left:6px;'>"
            "✅ Subtask completati — chiudi il task?</span>"
        )

    # ── Person pills (owner + supervisor) ────────────────────────────────────
    persons_html = ""
    umap    = user_map or {}
    owner_e = item.get("owner_email")
    sup_e   = item.get("supervisor_email")
    if owner_e:
        u = umap.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
        persons_html += person_pill_html(
            u.get("name", owner_e),
            u.get("avatar_color", "#534AB7"),
            role="owner", compact=True
        )
    if sup_e and sup_e != owner_e:
        u = umap.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
        persons_html += person_pill_html(
            u.get("name", sup_e),
            u.get("avatar_color", "#BA7517"),
            role="sup", compact=True
        )
    persons_row = (
        f"<div style='margin-top:5px;'>{persons_html}</div>" if persons_html else ""
    )

    # ── Scadenza ──────────────────────────────────────────────────────────────
    group_key, deadline_html = _deadline_group(item.get("deadline"), today, threshold)

    border_color = {
        "overdue": "#d93025",
        "soon":    "#e37400",
        "future":  "#cccccc",
    }[group_key]
    opacity = "0.78" if group_key == "future" else "1"

    item_name = item.get("name", "")

    card_html = f"""
    <div style='border-left:3px solid {border_color};padding:10px 14px 10px 14px;
                margin-bottom:6px;background:#ffffff;border-radius:0 6px 6px 0;
                box-shadow:0 1px 3px rgba(0,0,0,.07);opacity:{opacity};'>
      <div style='margin-bottom:4px;'>
        {type_badge}<strong style='font-size:14px;'>{item_name}</strong>{close_badge}
      </div>
      <div style='margin-bottom:5px;'>{breadcrumb}</div>
      <div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>
        {status_badge}
        {prio_badge}
        {deadline_html}
      </div>
      {persons_row}
    </div>
    """

    col_card, col_actions = st.columns([7, 2])
    with col_card:
        st.markdown(card_html, unsafe_allow_html=True)
    with col_actions:
        # "Segna completato" — solo To Do, solo se non già Completed
        if mode == "todo" and status != "Completed":
            if st.button("✓ Mark complete", key=f"done_{unique_key}",
                         use_container_width=True, type="secondary"):
                try:
                    update = {"status": "Completed"}
                    if kind == "task":
                        update["completion_date"] = today.isoformat()
                        supabase.table("tasks").update(update).eq("id", item_id).execute()
                    else:
                        supabase.table("subtasks").update(update).eq("id", item_id).execute()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        # "Dettaglio" — apre il modal esistente
        can_edit = (mode == "todo")
        if st.button("🔍 Detail", key=f"det_{unique_key}", use_container_width=True):
            if kind == "task":
                task_details_modal(item, can_edit=can_edit)
            else:
                subtask_details_modal(item, can_edit=can_edit)


# ── Render tab ────────────────────────────────────────────────────────────────

def _render_tab(entries, projects, deliverables, mode, today, threshold, user_map=None):
    """Raggruppa le entry per urgenza e renderizza ogni gruppo."""
    if not entries:
        st.info("No active items. ✅")
        return

    overdue, soon, future = [], [], []
    for entry in entries:
        group, _ = _deadline_group(entry["item"].get("deadline"), today, threshold)
        if group == "overdue":
            overdue.append(entry)
        elif group == "soon":
            soon.append(entry)
        else:
            future.append(entry)

    for group_key, group_entries in [("overdue", overdue), ("soon", soon), ("future", future)]:
        if not group_entries:
            continue
        _render_group_header(group_key, len(group_entries), threshold)
        for entry in group_entries:
            _render_item(entry, projects, deliverables, mode, today, threshold, user_map=user_map)


# ── Entry point ───────────────────────────────────────────────────────────────

def show_dashboard():
    st.title("Dashboard")

    email = st.session_state.get("user_email")
    if not email:
        st.error("Utente non trovato in sessione.")
        return

    try:
        threshold, projects, deliverables, all_tasks, all_subtasks, user_map = _fetch_data()
    except Exception as e:
        st.error(f"Errore nel caricamento dei dati: {e}")
        return

    today = datetime.date.today()

    todo_entries   = _build_flat_list(email, "todo",   all_tasks, all_subtasks)
    review_entries = _build_flat_list(email, "review", all_tasks, all_subtasks)

    tab1, tab2 = st.tabs([
        f"To Do ({len(todo_entries)})",
        f"To Review ({len(review_entries)})",
    ])

    with tab1:
        _render_tab(todo_entries, projects, deliverables, "todo", today, threshold, user_map=user_map)

    with tab2:
        st.caption(
            "These tasks are assigned to others. "
            "Your role is to monitor, unblock, or approve."
        )
        _render_tab(review_entries, projects, deliverables, "review", today, threshold, user_map=user_map)
