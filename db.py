"""db.py — Centralised query helpers with optional RBAC filtering.

user_email=None  → admin mode (no RBAC filter)
user_email=str   → user mode (filter: owner_email OR supervisor_email == user_email)

SQL migrations required in Supabase (run once in SQL Editor):
------------------------------------------------------------------
ALTER TABLE settings
  ADD COLUMN IF NOT EXISTS smtp_host          TEXT    DEFAULT 'smtp.gmail.com',
  ADD COLUMN IF NOT EXISTS smtp_port          INTEGER DEFAULT 587,
  ADD COLUMN IF NOT EXISTS smtp_user          TEXT    DEFAULT 'maiclab@unical.it',
  ADD COLUMN IF NOT EXISTS smtp_password      TEXT    DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_from_name     TEXT    DEFAULT 'MAIC LAB',
  ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS app_url            TEXT    DEFAULT 'http://localhost:8501';

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;

ALTER TABLE subtasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;
------------------------------------------------------------------
"""

from core.supabase_client import supabase

# ── Projects ─────────────────────────────────────────────────────────────────

def get_projects(show_archived: bool = False) -> list:
    q = supabase.table("projects").select("*").order("name")
    if not show_archived:
        q = q.eq("is_archived", False)
    return q.execute().data


# ── Deliverables ─────────────────────────────────────────────────────────────

def get_deliverables(show_archived: bool = False) -> list:
    q = supabase.table("deliverables").select("*")
    if not show_archived:
        q = q.eq("is_archived", False)
    return q.execute().data


# ── Tasks ────────────────────────────────────────────────────────────────────

def get_tasks(show_archived: bool = False, user_email: str | None = None) -> list:
    """Return tasks with optional RBAC filter."""
    q = supabase.table("tasks").select("*").order("sort_order", desc=False)
    if not show_archived:
        q = q.eq("is_archived", False)
    tasks = q.execute().data
    if user_email is not None:
        tasks = [
            t for t in tasks
            if t.get("owner_email") == user_email
            or t.get("supervisor_email") == user_email
        ]
    return tasks


# ── Subtasks ──────────────────────────────────────────────────────────────────

def get_subtasks(show_archived: bool = False, user_email: str | None = None) -> list:
    """Return subtasks with optional RBAC filter."""
    q = supabase.table("subtasks").select("*").order("sort_order", desc=False)
    if not show_archived:
        q = q.eq("is_archived", False)
    subtasks = q.execute().data
    if user_email is not None:
        subtasks = [
            s for s in subtasks
            if s.get("owner_email") == user_email
            or s.get("supervisor_email") == user_email
        ]
    return subtasks


# ── Users ────────────────────────────────────────────────────────────────────

def get_users(approved_only: bool = True) -> list:
    q = supabase.table("users").select("*")
    if approved_only:
        q = q.eq("is_approved", True)
    return q.execute().data


# ── Settings ─────────────────────────────────────────────────────────────────

_SETTINGS_DEFAULTS = {
    "expiring_threshold_days": 7,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "maiclab@unical.it",
    "smtp_password": "",
    "smtp_from_name": "MAIC LAB",
    "notifications_enabled": False,
    "app_url": "http://localhost:8501",
}

SETTINGS_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → Settings tab
ALTER TABLE settings
  ADD COLUMN IF NOT EXISTS smtp_host             TEXT    DEFAULT 'smtp.gmail.com',
  ADD COLUMN IF NOT EXISTS smtp_port             INTEGER DEFAULT 587,
  ADD COLUMN IF NOT EXISTS smtp_user             TEXT    DEFAULT 'maiclab@unical.it',
  ADD COLUMN IF NOT EXISTS smtp_password         TEXT    DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_from_name        TEXT    DEFAULT 'MAIC LAB',
  ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS app_url               TEXT    DEFAULT 'http://localhost:8501';

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;

ALTER TABLE subtasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;
"""


def get_settings() -> dict:
    """Return settings row merged with defaults. Never raises."""
    try:
        rows = supabase.table("settings").select("*").eq("id", 1).execute().data
        if rows:
            merged = _SETTINGS_DEFAULTS.copy()
            merged.update({k: v for k, v in rows[0].items() if v is not None})
            return merged
    except Exception:
        pass
    return _SETTINGS_DEFAULTS.copy()


def save_settings(updates: dict) -> tuple[bool, str]:
    """Upsert settings row. Returns (success, error_message)."""
    try:
        existing = supabase.table("settings").select("id").eq("id", 1).execute().data
        if existing:
            supabase.table("settings").update(updates).eq("id", 1).execute()
        else:
            supabase.table("settings").insert({"id": 1, **updates}).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


# ── Archived records ─────────────────────────────────────────────────────────

def get_archived_projects() -> list:
    return supabase.table("projects").select("*").eq("is_archived", True).execute().data


def get_archived_deliverables() -> list:
    return supabase.table("deliverables").select("*").eq("is_archived", True).execute().data


def get_archived_tasks() -> list:
    return supabase.table("tasks").select("*").eq("is_archived", True).execute().data


def get_archived_subtasks() -> list:
    return supabase.table("subtasks").select("*").eq("is_archived", True).execute().data


# ── Cascade delete ────────────────────────────────────────────────────────────

def delete_task_cascade(task_id: int):
    """Delete task and all dependent records (comments → subtasks → labels → task)."""
    supabase.table("comments").delete().eq("task_id", task_id).execute()
    supabase.table("subtasks").delete().eq("task_id", task_id).execute()
    supabase.table("task_labels").delete().eq("task_id", task_id).execute()
    supabase.table("task_dependencies").delete().eq("task_id", task_id).execute()
    supabase.table("task_dependencies").delete().eq("depends_on_task_id", task_id).execute()
    supabase.table("tasks").delete().eq("id", task_id).execute()


def delete_deliverable_cascade(deliverable_id: int):
    """Delete deliverable and all its tasks (each with full cascade)."""
    rows = supabase.table("tasks").select("id").eq("deliverable_id", deliverable_id).execute().data
    for t in rows:
        delete_task_cascade(t["id"])
    supabase.table("deliverables").delete().eq("id", deliverable_id).execute()


# ── Admin workload reports ────────────────────────────────────────────────────

def get_workload_per_person() -> list[dict]:
    """Return per-user task stats for the admin 'Carico per Persona' report.

    Each entry:
      user              – full users row
      tasks_active      – tasks where status not in (Completed, Cancelled), not archived
      tasks_overdue     – active tasks with deadline < today
      projects_count    – distinct projects with active tasks
      estimate_hours    – sum of estimate_hours on all non-cancelled tasks (or None)
      status_counts     – {status: count} over ALL non-cancelled tasks (for bars)
      all_user_tasks    – list of all non-cancelled, non-archived task dicts
      projects          – list of per-project dicts (see below)

    projects entry:
      project_id, project_name, project_acronym, role, tasks, status_counts
    """
    import datetime as _dt

    try:
        users        = supabase.table("users").select("*").eq("is_approved", True).execute().data
        tasks        = supabase.table("tasks").select("*").eq("is_archived", False).execute().data
        projects     = supabase.table("projects").select("*").execute().data
    except Exception as exc:
        print(f"[db.get_workload_per_person] {exc}")
        return []

    today = _dt.date.today().isoformat()

    proj_map = {p["id"]: p for p in projects}
    # Exclude cancelled from all analysis
    tasks = [t for t in tasks if t.get("status") != "Cancelled"]

    result = []
    for user in users:
        email = user["email"]

        user_tasks = [
            t for t in tasks
            if t.get("owner_email") == email or t.get("supervisor_email") == email
        ]
        if not user_tasks:
            continue

        # Active = not completed (still to do)
        active_tasks = [t for t in user_tasks if t.get("status") != "Completed"]
        overdue      = [t for t in active_tasks if t.get("deadline") and t["deadline"] < today]
        proj_ids     = {t["project_id"] for t in active_tasks if t.get("project_id")}

        raw_hours  = sum(t.get("estimate_hours") or 0 for t in user_tasks)
        est_hours  = raw_hours if raw_hours > 0 else None

        status_counts: dict[str, int] = {}
        for t in user_tasks:
            s = t.get("status", "Not started")
            status_counts[s] = status_counts.get(s, 0) + 1

        projects_detail = []
        for pid in proj_ids:
            proj = proj_map.get(pid, {})
            proj_active = [t for t in active_tasks if t.get("project_id") == pid]
            owner_n = sum(1 for t in proj_active if t.get("owner_email") == email)
            sup_n   = sum(1 for t in proj_active
                          if t.get("supervisor_email") == email and t.get("owner_email") != email)
            role = "owner" if owner_n >= sup_n else "supervisor"

            sc: dict[str, int] = {}
            for t in proj_active:
                s = t.get("status", "Not started")
                sc[s] = sc.get(s, 0) + 1

            projects_detail.append({
                "project_id":      pid,
                "project_name":    proj.get("name", ""),
                "project_acronym": proj.get("acronym") or proj.get("identifier", ""),
                "role":            role,
                "tasks":           proj_active,
                "status_counts":   sc,
            })
        projects_detail.sort(key=lambda x: x["project_name"])

        result.append({
            "user":           user,
            "tasks_active":   len(active_tasks),
            "tasks_overdue":  len(overdue),
            "projects_count": len(proj_ids),
            "estimate_hours": est_hours,
            "status_counts":  status_counts,
            "all_user_tasks": user_tasks,
            "projects":       projects_detail,
        })

    result.sort(key=lambda x: x["tasks_active"], reverse=True)
    return result


def get_staff_per_project() -> list[dict]:
    """Return per-project person matrix for the admin 'Organico per Progetto' report.

    Each entry:
      project           – full projects row
      tasks_active_count – total non-cancelled, non-archived tasks
      people            – list of person dicts:
          user, task_roles, tasks_active, status_counts,
          role_prevalent, estimate_hours
    """
    try:
        projects = supabase.table("projects").select("*").eq("is_archived", False).execute().data
        tasks    = supabase.table("tasks").select("*").eq("is_archived", False).execute().data
        users    = supabase.table("users").select("*").eq("is_approved", True).execute().data
    except Exception as exc:
        print(f"[db.get_staff_per_project] {exc}")
        return []

    tasks    = [t for t in tasks if t.get("status") != "Cancelled"]
    user_map = {u["email"]: u for u in users}

    result = []
    for proj in projects:
        pid        = proj["id"]
        proj_tasks = [t for t in tasks if t.get("project_id") == pid]
        if not proj_tasks:
            continue

        emails: set[str] = set()
        for t in proj_tasks:
            if t.get("owner_email"):      emails.add(t["owner_email"])
            if t.get("supervisor_email"): emails.add(t["supervisor_email"])

        people = []
        for email in emails:
            user = user_map.get(email, {
                "email": email, "name": email,
                "avatar_color": "#888888", "role": "user",
            })
            person_tasks = [
                t for t in proj_tasks
                if t.get("owner_email") == email or t.get("supervisor_email") == email
            ]
            task_roles = [
                {"task": t, "role": "owner" if t.get("owner_email") == email else "supervisor"}
                for t in person_tasks
            ]
            sc: dict[str, int] = {}
            for t in person_tasks:
                s = t.get("status", "Not started")
                sc[s] = sc.get(s, 0) + 1

            owner_n = sum(1 for r in task_roles if r["role"] == "owner")
            role_prev = "owner" if owner_n >= len(task_roles) - owner_n else "supervisor"

            hrs = [t.get("estimate_hours") for t in person_tasks if t.get("estimate_hours")]
            est_hours = sum(hrs) if hrs else None

            people.append({
                "user":           user,
                "task_roles":     task_roles,
                "tasks_active":   len(person_tasks),
                "status_counts":  sc,
                "role_prevalent": role_prev,
                "estimate_hours": est_hours,
            })

        people.sort(key=lambda x: x["tasks_active"], reverse=True)

        result.append({
            "project":            proj,
            "tasks_active_count": len(proj_tasks),
            "people":             people,
        })

    result.sort(key=lambda x: x["project"].get("end_date") or "9999-12-31")
    return result


def delete_project_cascade(project_id: int):
    """Delete project, all its deliverables and tasks."""
    delivs = supabase.table("deliverables").select("id").eq("project_id", project_id).execute().data
    for d in delivs:
        delete_deliverable_cascade(d["id"])
    # Tasks without deliverable
    rows = supabase.table("tasks").select("id").eq("project_id", project_id).execute().data
    for t in rows:
        delete_task_cascade(t["id"])
    supabase.table("projects").delete().eq("id", project_id).execute()


# ── Detail helpers (for modals) ───────────────────────────────────────────────

def get_task_detail(task_id: int) -> dict | None:
    """Return task enriched with _project, _deliverable, _users."""
    try:
        rows = supabase.table("tasks").select("*").eq("id", task_id).execute().data
        if not rows:
            return None
        task = rows[0]
        proj_rows = (
            supabase.table("projects").select("id, name, acronym").eq("id", task["project_id"]).execute().data
            if task.get("project_id") else []
        )
        task["_project"] = proj_rows[0] if proj_rows else {}
        deliv_rows = (
            supabase.table("deliverables").select("id, name").eq("id", task["deliverable_id"]).execute().data
            if task.get("deliverable_id") else []
        )
        task["_deliverable"] = deliv_rows[0] if deliv_rows else {}
        emails = [e for e in [task.get("owner_email"), task.get("supervisor_email")] if e]
        if emails:
            u_rows = supabase.table("users").select("email, name, avatar_color").in_("email", emails).execute().data
            task["_users"] = {u["email"]: u for u in u_rows}
        else:
            task["_users"] = {}
        return task
    except Exception as exc:
        print(f"[db.get_task_detail] {exc}")
        return None


def get_subtask_detail(subtask_id: int) -> dict | None:
    """Return subtask enriched with _parent_task, _project, _deliverable, _users."""
    try:
        rows = supabase.table("subtasks").select("*").eq("id", subtask_id).execute().data
        if not rows:
            return None
        sub = rows[0]
        parent: dict = {}
        proj: dict = {}
        deliv: dict = {}
        if sub.get("task_id"):
            t_rows = supabase.table("tasks").select(
                "id, name, sequence_id, project_id, deliverable_id"
            ).eq("id", sub["task_id"]).execute().data
            parent = t_rows[0] if t_rows else {}
            if parent.get("project_id"):
                p_rows = supabase.table("projects").select("id, name, acronym").eq(
                    "id", parent["project_id"]
                ).execute().data
                proj = p_rows[0] if p_rows else {}
            if parent.get("deliverable_id"):
                d_rows = supabase.table("deliverables").select("id, name").eq(
                    "id", parent["deliverable_id"]
                ).execute().data
                deliv = d_rows[0] if d_rows else {}
        sub["_parent_task"] = parent
        sub["_project"] = proj
        sub["_deliverable"] = deliv
        emails = [e for e in [sub.get("owner_email"), sub.get("supervisor_email")] if e]
        if emails:
            u_rows = supabase.table("users").select("email, name, avatar_color").in_("email", emails).execute().data
            sub["_users"] = {u["email"]: u for u in u_rows}
        else:
            sub["_users"] = {}
        return sub
    except Exception as exc:
        print(f"[db.get_subtask_detail] {exc}")
        return None
