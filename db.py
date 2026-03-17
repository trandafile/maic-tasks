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
