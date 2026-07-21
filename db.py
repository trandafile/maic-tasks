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

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;

ALTER TABLE subtasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;
------------------------------------------------------------------
"""

from core.supabase_client import supabase
import json
from datetime import date as _dt_date

from utils.helpers import DEFAULT_DELIVERABLE_TAG_STYLES

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

def rbac_or_filter(user_email: str) -> str:
    """PostgREST `or` expression matching rows owned or supervised by the user."""
    return f"owner_email.eq.{user_email},supervisor_email.eq.{user_email}"


def get_tasks(show_archived: bool = False, user_email: str | None = None) -> list:
    """Return tasks with optional RBAC filter (applied server-side)."""
    q = supabase.table("tasks").select("*").order("sort_order", desc=False)
    if not show_archived:
        q = q.eq("is_archived", False)
    if user_email is not None:
        q = q.or_(rbac_or_filter(user_email))
    return q.execute().data


# ── Subtasks ──────────────────────────────────────────────────────────────────

def get_subtasks(show_archived: bool = False, user_email: str | None = None) -> list:
    """Return subtasks with optional RBAC filter (applied server-side)."""
    q = supabase.table("subtasks").select("*").order("sort_order", desc=False)
    if not show_archived:
        q = q.eq("is_archived", False)
    if user_email is not None:
        q = q.or_(rbac_or_filter(user_email))
    return q.execute().data


# ── Users ────────────────────────────────────────────────────────────────────

def get_users(approved_only: bool = True) -> list:
    q = supabase.table("users").select("*")
    if approved_only:
        q = q.eq("is_approved", True)
    return q.execute().data


# ── Settings ─────────────────────────────────────────────────────────────────

_SETTINGS_DEFAULTS = {
    "expiring_threshold_days": 14,
    "stale_threshold_days": 14,
    "deliverable_types": json.dumps([s["name"] for s in DEFAULT_DELIVERABLE_TAG_STYLES]),
    "deliverable_tag_styles": json.dumps(DEFAULT_DELIVERABLE_TAG_STYLES),
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
    ADD COLUMN IF NOT EXISTS deliverable_types      TEXT    DEFAULT '["paper", "layout", "prototype"]',
    ADD COLUMN IF NOT EXISTS deliverable_tag_styles JSONB   DEFAULT '[{"name":"paper","color":"#0F766E"},{"name":"layout","color":"#1E3A8A"},{"name":"prototype","color":"#4A044E"}]'::jsonb,
  ADD COLUMN IF NOT EXISTS smtp_host             TEXT    DEFAULT 'smtp.gmail.com',
  ADD COLUMN IF NOT EXISTS smtp_port             INTEGER DEFAULT 587,
  ADD COLUMN IF NOT EXISTS smtp_user             TEXT    DEFAULT 'maiclab@unical.it',
  ADD COLUMN IF NOT EXISTS smtp_password         TEXT    DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_from_name        TEXT    DEFAULT 'MAIC LAB',
  ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS app_url               TEXT    DEFAULT 'http://localhost:8501';

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;

ALTER TABLE subtasks
  ADD COLUMN IF NOT EXISTS last_reminder_sent DATE;
"""


DELIVERABLES_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → add missing deliverables fields
ALTER TABLE deliverables
  ADD COLUMN IF NOT EXISTS description TEXT;

ALTER TABLE deliverables
    ADD COLUMN IF NOT EXISTS owner_email TEXT;

ALTER TABLE deliverables
    ADD COLUMN IF NOT EXISTS supervisor_email TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'deliverables_owner_email_fkey'
    ) THEN
        ALTER TABLE deliverables
            ADD CONSTRAINT deliverables_owner_email_fkey
            FOREIGN KEY (owner_email) REFERENCES users(email);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'deliverables_supervisor_email_fkey'
    ) THEN
        ALTER TABLE deliverables
            ADD CONSTRAINT deliverables_supervisor_email_fkey
            FOREIGN KEY (supervisor_email) REFERENCES users(email);
    END IF;
END $$;
"""


PROJECTS_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → add description field to projects
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS description TEXT;
"""


SCOPUS_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → adds Scopus + PhD tracking fields to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS scopus_id      TEXT,
    ADD COLUMN IF NOT EXISTS is_phd_student BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS phd_start_date DATE,
    ADD COLUMN IF NOT EXISTS phd_end_date   DATE;
"""


PAPER_DRAFTS_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → adds the deliverable_drafts table
-- used by the "My Paper Drafts" view to store the markdown working copy
-- of each paper deliverable.
CREATE TABLE IF NOT EXISTS deliverable_drafts (
    deliverable_id   INTEGER PRIMARY KEY REFERENCES deliverables(id) ON DELETE CASCADE,
    content          TEXT,
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_by_email TEXT REFERENCES users(email) ON UPDATE CASCADE ON DELETE SET NULL
);

-- Match the project-wide pattern: the app authenticates with the publishable
-- key, which enforces RLS. Other tables in this schema have RLS disabled,
-- so we do the same here. Without this line, INSERT/UPDATE on
-- deliverable_drafts fails with "new row violates row-level security policy".
ALTER TABLE deliverable_drafts DISABLE ROW LEVEL SECURITY;
"""


STATUS_HISTORY_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → adds the status_history log (used by the
-- Trend report) and creation timestamps on tasks/subtasks for progress charts.
CREATE TABLE IF NOT EXISTS status_history (
    id SERIAL PRIMARY KEY,
    item_type TEXT NOT NULL CHECK (item_type IN ('task', 'subtask')),
    item_id INTEGER NOT NULL,
    project_id INTEGER,
    old_status TEXT,
    new_status TEXT,
    changed_by_email TEXT,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_status_history_project ON status_history (project_id);
CREATE INDEX IF NOT EXISTS idx_status_history_item ON status_history (item_type, item_id);

-- Same pattern as the rest of the schema: the app authenticates with the
-- publishable key and RLS is disabled on application tables.
ALTER TABLE status_history DISABLE ROW LEVEL SECURITY;

-- NOTE: pre-existing rows get created_at = time of this migration.
ALTER TABLE tasks    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
"""


CONFERENCES_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → adds the conferences calendar table used by
-- the "Conference Calendar" view (manual entry + JSON import). The app degrades
-- gracefully until this is run: the Conference Calendar shows this snippet.
CREATE TABLE IF NOT EXISTS conferences (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    acronym TEXT,
    year INTEGER,
    location TEXT,
    url TEXT,
    topics TEXT,
    rank TEXT,
    submission_deadline DATE,
    notification_date DATE,
    camera_ready_date DATE,
    start_date DATE,
    end_date DATE,
    notes TEXT,
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conferences_submission ON conferences (submission_deadline);

-- Same pattern as the rest of the schema: the app authenticates with the
-- publishable key and RLS is disabled on application tables.
ALTER TABLE conferences DISABLE ROW LEVEL SECURITY;
"""


ENGAGEMENT_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → freshness tracking ("fermo da N giorni").
--
-- Why a column and not status_history: the staleness signal must turn green
-- when someone simply writes where they are. If it only counted status
-- changes, a researcher who posts a detailed note update would still look
-- stale — punishing exactly the behaviour we want. So every save touches
-- updated_at: status, notes, deadline, assignment.
ALTER TABLE tasks    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Existing rows: seed from created_at so nothing shows as "stale forever".
UPDATE tasks    SET updated_at = COALESCE(created_at, NOW()) WHERE updated_at IS NULL;
UPDATE subtasks SET updated_at = COALESCE(created_at, NOW()) WHERE updated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_updated_at    ON tasks (updated_at);
CREATE INDEX IF NOT EXISTS idx_subtasks_updated_at ON subtasks (updated_at);
"""


CONTRACTS_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → contract management + monthly timesheets.
-- Until this runs, the Contracts and Time Sheets pages show this snippet and the
-- rest of the app is unaffected.

-- Reporting metadata that belongs to the PROJECT (printed on every timesheet).
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS cup                TEXT,
    ADD COLUMN IF NOT EXISTS soggetto_attuatore TEXT,
    ADD COLUMN IF NOT EXISTS project_type       TEXT;

-- Fiscal code is a property of the person, printed on the timesheet header.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS fiscal_code TEXT;

-- One row per contract. PhD students ('phd') do NOT fill timesheets;
-- contractors ('contract') do.
CREATE TABLE IF NOT EXISTS contracts (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL REFERENCES users(email) ON UPDATE CASCADE ON DELETE CASCADE,
    contract_type TEXT NOT NULL CHECK (contract_type IN ('phd', 'contract')),
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    start_date DATE,
    end_date DATE,
    annual_hours INTEGER DEFAULT 1500,   -- "Monte ore lavorative annuo previsto"
    daily_hours NUMERIC DEFAULT 8,       -- autofill: hours booked per working day
    hourly_cost NUMERIC,
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contracts_user ON contracts (user_email);
ALTER TABLE contracts DISABLE ROW LEVEL SECURITY;

-- Configurable timesheet rows per project. `counts_to_project` marks the rows
-- imputable to the CUP (their label gets " - <CUP>" appended, as in the MIUR
-- template). `default_share_pct` drives the autofill split.
CREATE TABLE IF NOT EXISTS project_activities (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    counts_to_project BOOLEAN DEFAULT TRUE,
    default_share_pct NUMERIC DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_project_activities_project ON project_activities (project_id);
ALTER TABLE project_activities DISABLE ROW LEVEL SECURITY;

-- One row per (person, project, month). `grid` is {activity_id: {day: hours}}.
CREATE TABLE IF NOT EXISTS timesheets (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    grid JSONB DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'draft',         -- 'draft' | 'completed'
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by_email TEXT,
    UNIQUE (user_email, project_id, year, month)
);
CREATE INDEX IF NOT EXISTS idx_timesheets_user_period ON timesheets (user_email, year, month);
ALTER TABLE timesheets DISABLE ROW LEVEL SECURITY;
"""


USER_EMAIL_FK_MIGRATION_SQL = """\
-- Run once in Supabase SQL Editor → allow user email update/delete without FK errors
-- This keeps task/deliverable/subtask/comment rows, updates references on email change,
-- and sets references to NULL when a user is deleted.

ALTER TABLE deliverables DROP CONSTRAINT IF EXISTS deliverables_owner_email_fkey;
ALTER TABLE deliverables ADD CONSTRAINT deliverables_owner_email_fkey
    FOREIGN KEY (owner_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;

ALTER TABLE deliverables DROP CONSTRAINT IF EXISTS deliverables_supervisor_email_fkey;
ALTER TABLE deliverables ADD CONSTRAINT deliverables_supervisor_email_fkey
    FOREIGN KEY (supervisor_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_owner_email_fkey;
ALTER TABLE tasks ADD CONSTRAINT tasks_owner_email_fkey
    FOREIGN KEY (owner_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_supervisor_email_fkey;
ALTER TABLE tasks ADD CONSTRAINT tasks_supervisor_email_fkey
    FOREIGN KEY (supervisor_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;

ALTER TABLE subtasks DROP CONSTRAINT IF EXISTS subtasks_owner_email_fkey;
ALTER TABLE subtasks ADD CONSTRAINT subtasks_owner_email_fkey
    FOREIGN KEY (owner_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;

ALTER TABLE subtasks DROP CONSTRAINT IF EXISTS subtasks_supervisor_email_fkey;
ALTER TABLE subtasks ADD CONSTRAINT subtasks_supervisor_email_fkey
    FOREIGN KEY (supervisor_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;

ALTER TABLE comments DROP CONSTRAINT IF EXISTS comments_author_email_fkey;
ALTER TABLE comments ADD CONSTRAINT comments_author_email_fkey
    FOREIGN KEY (author_email) REFERENCES users(email)
    ON UPDATE CASCADE ON DELETE SET NULL;
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
    """Upsert settings row. Returns (success, error_message).

    If Supabase schema is partially migrated, retry by dropping missing columns
    found in the error payload so basic settings can still be saved.
    """

    def _upsert(payload: dict):
        existing = supabase.table("settings").select("id").eq("id", 1).execute().data
        if existing:
            supabase.table("settings").update(payload).eq("id", 1).execute()
        else:
            supabase.table("settings").insert({"id": 1, **payload}).execute()

    def _missing_column_from_error(err: Exception) -> str | None:
        msg = str(err)
        token = "Could not find the '"
        if token in msg:
            start = msg.find(token) + len(token)
            end = msg.find("' column", start)
            if end > start:
                return msg[start:end]
        return None

    try:
        _upsert(updates)
        return True, ""
    except Exception as e:
        payload = dict(updates)
        missing = _missing_column_from_error(e)
        removed = []

        while missing and missing in payload:
            removed.append(missing)
            payload.pop(missing, None)
            if not payload:
                return False, str(e)
            try:
                _upsert(payload)
                warn = ""
                if removed:
                    warn = (
                        "Saved with partial schema. Missing columns in Supabase: "
                        + ", ".join(sorted(set(removed)))
                    )
                return True, warn
            except Exception as e2:
                missing = _missing_column_from_error(e2)
                e = e2

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


# ── Status history (audit log for trend reports) ─────────────────────────────

def log_status_change(
    item_type: str,
    item_id: int,
    project_id: int | None,
    old_status: str | None,
    new_status: str | None,
    changed_by_email: str | None,
) -> None:
    """Best-effort append to status_history. Never raises: the table may not
    exist yet (run STATUS_HISTORY_MIGRATION_SQL in the Supabase SQL Editor)
    and a logging failure must not block the save that triggered it."""
    try:
        supabase.table("status_history").insert({
            "item_type":        item_type,
            "item_id":          item_id,
            "project_id":       project_id,
            "old_status":       old_status,
            "new_status":       new_status,
            "changed_by_email": changed_by_email,
        }).execute()
    except Exception as exc:
        print(f"[db.log_status_change] {exc}")


# ── Delay / punctuality metrics ───────────────────────────────────────────────

def compute_delay_stats(tasks: list) -> dict:
    """Punctuality stats over a list of task dicts.

    Evaluates tasks with status == "Completed" that have BOTH a deadline and a
    completion_date. Returns:
      completed_with_deadline – evaluated tasks
      completed_late          – completed after their deadline
      on_time_rate            – % completed on time (None if nothing evaluable)
      avg_delay_days          – mean lateness in days over LATE tasks (None)
    """
    import datetime as _dt

    evaluated = 0
    late = 0
    delays: list[int] = []
    for t in tasks:
        if t.get("status") != "Completed":
            continue
        dl, cd = t.get("deadline"), t.get("completion_date")
        if not dl or not cd:
            continue
        try:
            d_dl = _dt.date.fromisoformat(str(dl)[:10])
            d_cd = _dt.date.fromisoformat(str(cd)[:10])
        except ValueError:
            continue
        evaluated += 1
        delay = (d_cd - d_dl).days
        if delay > 0:
            late += 1
            delays.append(delay)

    return {
        "completed_with_deadline": evaluated,
        "completed_late": late,
        "on_time_rate": round(100 * (evaluated - late) / evaluated) if evaluated else None,
        "avg_delay_days": round(sum(delays) / len(delays), 1) if delays else None,
    }


# ── Admin workload reports ────────────────────────────────────────────────────

def get_workload_per_person() -> list[dict]:
    """Return per-user task stats for the admin 'Carico per Persona' report.

    Each entry:
      user              – full users row
      tasks_active      – tasks where email == owner_email AND status not in (Completed, Cancelled)
      supervises_count  – tasks where email == supervisor_email (not owner), status not Completed/Cancelled
      tasks_overdue     – active owned tasks with deadline < today
      projects_count    – distinct projects with active owned tasks
      estimate_hours    – sum of estimate_hours on owned tasks only (non-cancelled)
      status_counts     – {status: count} over ALL non-cancelled owned tasks (for bars)
      all_user_tasks    – list of all non-cancelled, non-archived task dicts (owned OR supervised)
      owned_tasks       – list of all non-cancelled, non-archived tasks where email == owner_email
      supervised_tasks  – list where email == supervisor_email AND email != owner_email, non-cancelled
      projects          – list of per-project dicts (see below)

    projects entry:
      project_id, project_name, project_acronym, role, tasks, status_counts
    """
    import datetime as _dt

    try:
        users        = supabase.table("users").select("*").eq("is_approved", True).execute().data
        tasks_all    = supabase.table("tasks").select("*").execute().data
        projects     = supabase.table("projects").select("*").execute().data
    except Exception as exc:
        print(f"[db.get_workload_per_person] {exc}")
        return []

    today = _dt.date.today().isoformat()

    proj_map = {p["id"]: p for p in projects}
    # Exclude cancelled from all analysis. Archived tasks are kept aside:
    # they are excluded from the workload lists but still count for the
    # punctuality stats (completed tasks are routinely bulk-archived).
    tasks_all = [t for t in tasks_all if t.get("status") != "Cancelled"]
    tasks = [t for t in tasks_all if not t.get("is_archived")]

    result = []
    for user in users:
        email = user["email"]

        owned_tasks = [
            t for t in tasks
            if t.get("owner_email") == email
        ]
        supervised_tasks = [
            t for t in tasks
            if t.get("supervisor_email") == email and t.get("owner_email") != email
        ]
        user_tasks = owned_tasks + supervised_tasks

        if not user_tasks:
            continue

        # Active = owned and not completed
        active_tasks = [t for t in owned_tasks if t.get("status") != "Completed"]
        overdue      = [t for t in active_tasks if t.get("deadline") and t["deadline"] < today]
        proj_ids     = {t["project_id"] for t in active_tasks if t.get("project_id")}

        supervises_count = len([t for t in supervised_tasks if t.get("status") != "Completed"])

        raw_hours  = sum(t.get("estimate_hours") or 0 for t in owned_tasks)
        est_hours  = raw_hours if raw_hours > 0 else None

        # status_counts over owned tasks only (for progress bars)
        status_counts: dict[str, int] = {}
        for t in owned_tasks:
            s = t.get("status", "Not started")
            status_counts[s] = status_counts.get(s, 0) + 1

        projects_detail = []
        all_proj_ids = {t["project_id"] for t in user_tasks if t.get("project_id")}
        for pid in all_proj_ids:
            proj = proj_map.get(pid, {})
            proj_active = [t for t in active_tasks if t.get("project_id") == pid]
            owner_n = len(proj_active)
            sup_n   = sum(1 for t in supervised_tasks
                          if t.get("project_id") == pid and t.get("status") != "Completed")
            role = "owner" if owner_n >= sup_n else "supervisor"

            sc: dict[str, int] = {}
            for t in [t for t in user_tasks if t.get("project_id") == pid]:
                s = t.get("status", "Not started")
                sc[s] = sc.get(s, 0) + 1

            projects_detail.append({
                "project_id":      pid,
                "project_name":    proj.get("name", ""),
                "project_acronym": proj.get("acronym") or proj.get("identifier", ""),
                "role":            role,
                "tasks":           [t for t in user_tasks if t.get("project_id") == pid],
                "status_counts":   sc,
            })
        projects_detail.sort(key=lambda x: x["project_name"])

        result.append({
            "user":             user,
            "tasks_active":     len(active_tasks),
            "supervises_count": supervises_count,
            "tasks_overdue":    len(overdue),
            "projects_count":   len(proj_ids),
            "estimate_hours":   est_hours,
            "status_counts":    status_counts,
            "all_user_tasks":   user_tasks,
            "owned_tasks":      owned_tasks,
            "supervised_tasks": supervised_tasks,
            "projects":         projects_detail,
            "delay_stats":      compute_delay_stats(
                [t for t in tasks_all if t.get("owner_email") == email]
            ),
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
          role_prevalent, estimate_hours,
          owned_count, supervised_count, owned_hours
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

            owned_tasks = [t for t in proj_tasks if t.get("owner_email") == email]
            supervised_tasks = [
                t for t in proj_tasks
                if t.get("supervisor_email") == email and t.get("owner_email") != email
            ]
            owned_count      = len(owned_tasks)
            supervised_count = len(supervised_tasks)

            owner_hrs = [t.get("estimate_hours") for t in owned_tasks if t.get("estimate_hours")]
            owned_hours = sum(owner_hrs) if owner_hrs else None

            # keep backward-compatible estimate_hours (all tasks)
            all_hrs = [t.get("estimate_hours") for t in person_tasks if t.get("estimate_hours")]
            est_hours = sum(all_hrs) if all_hrs else None

            owner_n = sum(1 for r in task_roles if r["role"] == "owner")
            role_prev = "owner" if owner_n >= len(task_roles) - owner_n else "supervisor"

            people.append({
                "user":             user,
                "task_roles":       task_roles,
                "tasks_active":     len(person_tasks),
                "status_counts":    sc,
                "role_prevalent":   role_prev,
                "estimate_hours":   est_hours,
                "owned_count":      owned_count,
                "supervised_count": supervised_count,
                "owned_hours":      owned_hours,
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


# ── Comments (task discussion thread) ─────────────────────────────────────────

def _comment_author_name(row: dict) -> str:
    """Resolve the author display name from a `users(name)` join (dict or list)."""
    rel = row.get("users")
    if isinstance(rel, dict):
        return rel.get("name") or row.get("author_email") or "?"
    if isinstance(rel, list) and rel:
        return rel[0].get("name") or row.get("author_email") or "?"
    return row.get("author_email") or "?"


def get_comments(task_id: int, include_system: bool = True) -> list[dict]:
    """Return the comment thread of a task, oldest first, with `author_name`."""
    try:
        q = supabase.table("comments").select("*, users(name)").eq("task_id", task_id)
        if not include_system:
            q = q.eq("is_system_event", False)
        rows = q.order("created_at", desc=False).execute().data or []
    except Exception as exc:
        print(f"[db.get_comments] {exc}")
        return []
    for r in rows:
        r["author_name"] = _comment_author_name(r)
    return rows


def add_comment(task_id: int, author_email: str | None, body: str) -> tuple[bool, str]:
    """Insert a user comment. Returns (success, error)."""
    text = (body or "").strip()
    if not text:
        return False, "Empty comment."
    try:
        res = supabase.table("comments").insert({
            "task_id":         task_id,
            "author_email":    author_email,
            "body":            text,
            "is_system_event": False,
        }).execute()
        if not getattr(res, "data", None):
            return False, "The database did not confirm the insert."
        return True, ""
    except Exception as exc:
        return False, str(exc)


def update_comment(comment_id: int, body: str) -> tuple[bool, str]:
    """Edit a comment body. Returns (success, error)."""
    text = (body or "").strip()
    if not text:
        return False, "Empty comment."
    try:
        supabase.table("comments").update({"body": text}).eq("id", comment_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def delete_comment(comment_id: int) -> tuple[bool, str]:
    try:
        supabase.table("comments").delete().eq("id", comment_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def get_comment_counts(task_ids: list[int] | None = None) -> dict[int, int]:
    """Return {task_id: user-comment count} for a badge on task rows.

    One query; system events are excluded so the badge reflects human
    discussion only. Empty/failed → {} (badge simply not shown).
    """
    try:
        q = supabase.table("comments").select("task_id").eq("is_system_event", False)
        if task_ids:
            q = q.in_("task_id", list(task_ids))
        rows = q.execute().data or []
    except Exception as exc:
        print(f"[db.get_comment_counts] {exc}")
        return {}
    counts: dict[int, int] = {}
    for r in rows:
        tid = r.get("task_id")
        if tid is not None:
            counts[tid] = counts.get(tid, 0) + 1
    return counts


# ── Paper drafts (for the "My Paper Drafts" view) ─────────────────────────────

def get_user_paper_deliverables(user_email: str | None, is_admin: bool) -> list[dict]:
    """Return paper-type deliverables visible to the user.

    Admin sees all non-archived paper deliverables.
    Non-admin sees only those where they are owner or supervisor.
    Each row is enriched with `_project` (id, name, acronym) and the
    `draft_updated_at` timestamp if a draft exists.
    """
    try:
        q = (
            supabase.table("deliverables")
            .select("*")
            .eq("is_archived", False)
            .eq("type", "paper")
        )
        delivs = q.execute().data or []
    except Exception as exc:
        print(f"[db.get_user_paper_deliverables] {exc}")
        return []

    if not is_admin and user_email:
        delivs = [
            d for d in delivs
            if d.get("owner_email") == user_email
            or d.get("supervisor_email") == user_email
        ]

    if not delivs:
        return []

    project_ids = sorted({d["project_id"] for d in delivs if d.get("project_id")})
    proj_map: dict[int, dict] = {}
    if project_ids:
        try:
            proj_rows = (
                supabase.table("projects")
                .select("id, name, acronym")
                .in_("id", project_ids)
                .execute()
                .data
                or []
            )
            proj_map = {p["id"]: p for p in proj_rows}
        except Exception as exc:
            print(f"[db.get_user_paper_deliverables] projects fetch: {exc}")

    deliv_ids = [d["id"] for d in delivs]
    draft_ts: dict[int, str] = {}
    try:
        rows = (
            supabase.table("deliverable_drafts")
            .select("deliverable_id, updated_at")
            .in_("deliverable_id", deliv_ids)
            .execute()
            .data
            or []
        )
        draft_ts = {r["deliverable_id"]: r.get("updated_at") for r in rows}
    except Exception as exc:
        print(f"[db.get_user_paper_deliverables] drafts fetch: {exc}")

    for d in delivs:
        d["_project"] = proj_map.get(d.get("project_id"), {})
        d["draft_updated_at"] = draft_ts.get(d["id"])

    return delivs


def get_paper_draft(deliverable_id: int) -> dict | None:
    """Return the draft row for a deliverable, or None if it does not exist."""
    try:
        rows = (
            supabase.table("deliverable_drafts")
            .select("*")
            .eq("deliverable_id", deliverable_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as exc:
        print(f"[db.get_paper_draft] {exc}")
        return None


def save_paper_draft(deliverable_id: int, content: str, user_email: str | None) -> tuple[bool, str]:
    """Upsert a draft row. Returns (success, error)."""
    import datetime as _dt
    payload = {
        "deliverable_id": deliverable_id,
        "content": content,
        "updated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "updated_by_email": user_email,
    }
    try:
        existing = (
            supabase.table("deliverable_drafts")
            .select("deliverable_id")
            .eq("deliverable_id", deliverable_id)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            supabase.table("deliverable_drafts").update(payload).eq(
                "deliverable_id", deliverable_id
            ).execute()
        else:
            supabase.table("deliverable_drafts").insert(payload).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ── Conferences (calendar of target venues) ───────────────────────────────────

# Field set persisted for a conference. Keep in sync with CONFERENCES_MIGRATION_SQL
# and the JSON import/export schema exposed in the Conference Calendar view.
CONFERENCE_FIELDS = [
    "name", "acronym", "year", "location", "url", "topics", "rank",
    "submission_deadline", "notification_date", "camera_ready_date",
    "start_date", "end_date", "notes",
]
_CONFERENCE_DATE_FIELDS = {
    "submission_deadline", "notification_date", "camera_ready_date",
    "start_date", "end_date",
}


def _norm_conf_date(value) -> str | None:
    """Coerce a JSON date value to an ISO 'YYYY-MM-DD' string or None."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    try:
        return _dt_date.fromisoformat(s[:10]).isoformat()
    except Exception:
        return None


def normalize_conference_payload(raw: dict) -> dict | None:
    """Validate/normalize one conference dict (from a form or JSON import).

    Returns a payload with only known columns, or None when the mandatory
    ``name`` is missing. Unknown keys are dropped; dates are coerced to ISO.
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    payload: dict = {"name": name}
    for key in CONFERENCE_FIELDS:
        if key == "name":
            continue
        if key not in raw:
            continue
        val = raw.get(key)
        if key in _CONFERENCE_DATE_FIELDS:
            payload[key] = _norm_conf_date(val)
        elif key == "year":
            try:
                payload[key] = int(val) if val not in (None, "") else None
            except (TypeError, ValueError):
                payload[key] = None
        else:
            payload[key] = (str(val).strip() or None) if val is not None else None
    return payload


def get_conferences(show_archived: bool = False) -> list | None:
    """Return conferences ordered by submission deadline.

    Returns None (not []) when the table does not exist yet, so the caller can
    tell 'run the migration' apart from 'no conferences yet'.
    """
    try:
        q = supabase.table("conferences").select("*")
        if not show_archived:
            q = q.eq("is_archived", False)
        rows = q.order("submission_deadline", desc=False).execute().data
        return rows or []
    except Exception as exc:
        print(f"[db.get_conferences] {exc}")
        return None


def upsert_conference(payload: dict, conference_id: int | None = None) -> tuple[bool, str]:
    """Insert (conference_id is None) or update a conference row."""
    clean = normalize_conference_payload(payload)
    if clean is None:
        return False, "Conference name is required."
    try:
        if conference_id is None:
            supabase.table("conferences").insert(clean).execute()
        else:
            supabase.table("conferences").update(clean).eq("id", conference_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def conference_dedup_key(row: dict) -> tuple:
    """Identity of a conference for duplicate detection: (acronym|name, year).

    Acronym is preferred; name is the fallback when no acronym is given. Year is
    part of the key so the 2026 and 2027 editions are treated as distinct.
    """
    acr = (row.get("acronym") or "").strip().lower()
    name = (row.get("name") or "").strip().lower()
    return (acr or name, row.get("year"))


def import_conferences_json(data) -> tuple[int, int, int, list[str]]:
    """Bulk-insert conferences from a parsed JSON list, skipping duplicates.

    Accepts either a list of dicts or a dict with a top-level 'conferences' key.
    A conference is a duplicate when its (acronym|name, year) key already exists
    in the table (archived rows included) or appears earlier in the same batch.
    Returns (inserted, skipped_invalid, skipped_duplicate, errors).
    """
    if isinstance(data, dict) and "conferences" in data:
        data = data.get("conferences")
    if not isinstance(data, list):
        return 0, 0, 0, ["JSON root must be a list of conferences (or {'conferences': [...]})."]

    # Existing keys (include archived, so we don't resurrect a removed one).
    existing = get_conferences(show_archived=True)
    if existing is None:
        return 0, 0, 0, ["The 'conferences' table does not exist. Run the migration first."]
    seen: set[tuple] = {conference_dedup_key(c) for c in existing}

    rows: list[dict] = []
    skipped_invalid = 0
    skipped_dup = 0
    errors: list[str] = []
    for i, item in enumerate(data):
        clean = normalize_conference_payload(item)
        if clean is None:
            skipped_invalid += 1
            errors.append(f"Entry #{i + 1} skipped: missing 'name'.")
            continue
        key = conference_dedup_key(clean)
        if key in seen:
            skipped_dup += 1
            errors.append(
                f"'{clean.get('acronym') or clean.get('name')}"
                f"{(' ' + str(clean['year'])) if clean.get('year') else ''}' already present — skipped."
            )
            continue
        seen.add(key)
        rows.append(clean)

    if not rows:
        return 0, skipped_invalid, skipped_dup, errors or ["No new conferences to import."]

    try:
        supabase.table("conferences").insert(rows).execute()
        return len(rows), skipped_invalid, skipped_dup, errors
    except Exception as exc:
        return 0, skipped_invalid, skipped_dup, errors + [str(exc)]


def set_conference_archived(conference_id: int, archived: bool = True) -> None:
    try:
        supabase.table("conferences").update({"is_archived": archived}).eq("id", conference_id).execute()
    except Exception as exc:
        print(f"[db.set_conference_archived] {exc}")


def delete_conference(conference_id: int) -> tuple[bool, str]:
    """Hard-delete a conference row (admin cleanup of non-pertinent entries)."""
    try:
        supabase.table("conferences").delete().eq("id", conference_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ── Conference papers (tasks in a dedicated project — no schema change) ────────

CONF_PROJECT_NAME = "Conference Papers"
CONF_PROJECT_IDENTIFIER = "CONF"


def get_or_create_conference_project(create: bool = True) -> dict | None:
    """Return the dedicated 'Conference Papers' project, creating it on demand.

    Conference paper drafts are modelled as ordinary tasks of this project, so
    they reuse the whole task machinery (notes editor, RBAC, status history)
    without any schema change. Matched by the stable CONF identifier, with a
    name fallback for older manually-created rows.
    """
    try:
        rows = supabase.table("projects").select("*").eq(
            "identifier", CONF_PROJECT_IDENTIFIER
        ).limit(1).execute().data
        if rows:
            return rows[0]
        rows = supabase.table("projects").select("*").eq(
            "name", CONF_PROJECT_NAME
        ).limit(1).execute().data
        if rows:
            return rows[0]
        if not create:
            return None
        ins = supabase.table("projects").insert({
            "name":           CONF_PROJECT_NAME,
            "acronym":        CONF_PROJECT_IDENTIFIER,
            "identifier":     CONF_PROJECT_IDENTIFIER,
            "funding_agency": None,
            "is_archived":    False,
        }).execute().data
        return ins[0] if ins else None
    except Exception as exc:
        print(f"[db.get_or_create_conference_project] {exc}")
        return None


def _conference_deliverable_name(conf: dict) -> str:
    acr = (conf.get("acronym") or conf.get("name") or "Conference").strip()
    year = conf.get("year")
    return f"{acr} {year}".strip() if year else acr


def ensure_conference_deliverable(project_id: int, conf: dict) -> int | None:
    """Find or create the deliverable projecting a target conference inside the
    Conference Papers project. Returns its id (paper tasks link to it).

    The deliverable is a lightweight projection of the conferences row: it
    carries the submission deadline so linked paper tasks inherit a meaningful
    due date and show up in the existing Calendar/Reports views.
    """
    name = _conference_deliverable_name(conf)
    try:
        rows = supabase.table("deliverables").select("id").eq(
            "project_id", project_id
        ).eq("name", name).limit(1).execute().data
        if rows:
            return rows[0]["id"]
        ins = supabase.table("deliverables").insert({
            "project_id": project_id,
            "name":       name,
            "type":       "conference",
            "status":     "Not started",
            "deadline":   _norm_conf_date(conf.get("submission_deadline")),
        }).execute().data
        return ins[0]["id"] if ins else None
    except Exception as exc:
        print(f"[db.ensure_conference_deliverable] {exc}")
        return None


def get_conference_paper_tasks(user_email: str | None = None) -> list:
    """Return active tasks of the Conference Papers project (optional RBAC)."""
    proj = get_or_create_conference_project(create=False)
    if not proj:
        return []
    try:
        q = supabase.table("tasks").select("*").eq(
            "project_id", proj["id"]
        ).eq("is_archived", False)
        if user_email is not None:
            q = q.or_(rbac_or_filter(user_email))
        return q.order("sort_order", desc=False).execute().data or []
    except Exception as exc:
        print(f"[db.get_conference_paper_tasks] {exc}")
        return []


# ── Freshness ("fermo da N giorni") ───────────────────────────────────────────
#
# For long research tasks a far-off deadline says nothing for months, while
# "not updated in 34 days" says everything at once. This is the primary
# engagement signal, so it must react to ANY meaningful edit — see
# ENGAGEMENT_MIGRATION_SQL for why it is a column and not derived history.

import datetime as _dt_mod


def now_iso() -> str:
    """UTC timestamp for updated_at, in the format PostgREST accepts."""
    return _dt_mod.datetime.utcnow().isoformat() + "Z"


def parse_ts(value) -> _dt_mod.datetime | None:
    if not value:
        return None
    try:
        return _dt_mod.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def days_since_update(item: dict) -> int | None:
    """Whole days since the item was last touched. None when unknown.

    Falls back to created_at so a freshly created task is never 'stale', and
    returns None (rather than a wrong number) when the migration has not run.
    """
    ts = parse_ts(item.get("updated_at")) or parse_ts(item.get("created_at"))
    if ts is None:
        return None
    return max(0, (_dt_mod.datetime.utcnow() - ts).days)


def is_stale(item: dict, threshold: int) -> bool:
    d = days_since_update(item)
    return d is not None and d >= threshold


def stale_threshold() -> int:
    try:
        return int(get_settings().get("stale_threshold_days", 14))
    except (TypeError, ValueError):
        return 14


# ── "My week" — the low-friction update surface ───────────────────────────────

def get_my_week(user_email: str) -> dict:
    """Everything the user owns and can act on this week, in one round trip."""
    out = {"tasks": [], "subtasks": [], "projects": {}, "task_map": {}}
    try:
        projects = supabase.table("projects").select(
            "id, name, acronym, identifier"
        ).eq("is_archived", False).execute().data or []
        out["projects"] = {p["id"]: p for p in projects}

        tasks = supabase.table("tasks").select("*").eq(
            "is_archived", False
        ).eq("owner_email", user_email).execute().data or []
        all_tasks = supabase.table("tasks").select(
            "id, name, project_id"
        ).eq("is_archived", False).execute().data or []
        out["task_map"] = {t["id"]: t for t in all_tasks}

        subtasks = supabase.table("subtasks").select("*").eq(
            "is_archived", False
        ).eq("owner_email", user_email).execute().data or []

        active = lambda i: (i.get("status") or "Not started") not in ("Completed", "Cancelled")
        out["tasks"] = [t for t in tasks if active(t) and t.get("project_id") in out["projects"]]
        out["subtasks"] = [
            s for s in subtasks
            if active(s) and out["task_map"].get(s.get("task_id"), {}).get("project_id") in out["projects"]
        ]
    except Exception as exc:
        print(f"[db.get_my_week] {exc}")
    return out


def quick_update(table: str, item_id: int, *, status: str | None = None,
                 note_append: str | None = None, current_notes: str = "",
                 project_id: int | None = None, old_status: str | None = None,
                 user_email: str | None = None) -> tuple[bool, str]:
    """One-tap update from the My Week view: status and/or a dated note line.

    Always refreshes updated_at — that is what makes the freshness signal fair:
    writing where you are is enough to clear it, no status change required.
    """
    if table not in ("tasks", "subtasks"):
        return False, "Invalid table."

    payload: dict = {"updated_at": now_iso()}
    if status:
        payload["status"] = status
        if table == "tasks":
            if status == "Completed" and old_status != "Completed":
                payload["completion_date"] = _dt_date.today().isoformat()
            elif status != "Completed" and old_status == "Completed":
                payload["completion_date"] = None

    if (note_append or "").strip():
        stamp = _dt_date.today().strftime("%d/%m/%Y")
        line = f"**{stamp}** — {note_append.strip()}"
        payload["notes"] = (current_notes + "\n\n" + line).strip() if current_notes else line

    ok, err, _ = update_row(table, item_id, payload)
    if not ok:
        return False, err

    if status and status != old_status:
        log_status_change(
            "task" if table == "tasks" else "subtask",
            item_id, project_id, old_status, status, user_email,
        )
    return True, ""


def update_row(table: str, item_id: int, payload: dict) -> tuple[bool, str, object]:
    """Update a row, tolerating columns the database does not have yet.

    PostgREST answers PGRST204 when a column is missing from its schema cache.
    An optional enrichment (updated_at, added by a pending migration) must never
    block the write the user actually asked for, so the offending column is
    dropped and the update retried once. Returns (ok, error, response_data).
    """
    import re as _re

    attempt = dict(payload)
    for _ in range(len(payload) + 1):
        try:
            res = supabase.table(table).update(attempt).eq("id", item_id).execute()
            data = getattr(res, "data", None)
            if not data:
                return False, "The database did not confirm the update.", None
            return True, "", data
        except Exception as exc:
            msg = str(exc)
            if "PGRST204" not in msg and "schema cache" not in msg:
                return False, msg, None
            m = _re.search(r"'([^']+)' column", msg)
            col = m.group(1) if m else None
            if not col or col not in attempt:
                return False, msg, None
            # Drop the unknown column and retry with what the schema supports.
            attempt.pop(col, None)
            print(f"[db.update_row] '{col}' missing on {table} — retrying without it "
                  f"(run the pending migration to enable it)")
            if not attempt:
                return False, "Nothing left to update.", None
    return False, "Could not reconcile the payload with the schema.", None


def touch(table: str, item_id: int) -> None:
    """Mark an item as updated without changing anything else."""
    try:
        supabase.table(table).update({"updated_at": now_iso()}).eq("id", item_id).execute()
    except Exception as exc:
        print(f"[db.touch] {exc}")


# ── Personal + team activity stats (from status_history) ──────────────────────

def get_activity_stats(user_email: str | None = None, weeks: int = 8) -> dict:
    """Status changes grouped by ISO week, optionally for one person.

    Returns {"by_week": {"YYYY-Www": n}, "completed_by_week": {...}, "total": n}.
    Empty dicts when status_history is missing — the caller shows a hint.
    """
    since = (_dt_date.today() - _dt_mod.timedelta(weeks=weeks)).isoformat()
    out = {"by_week": {}, "completed_by_week": {}, "total": 0, "available": True}
    try:
        q = supabase.table("status_history").select(
            "new_status, changed_at, changed_by_email"
        ).gte("changed_at", since)
        if user_email:
            q = q.eq("changed_by_email", user_email)
        rows = q.execute().data or []
    except Exception as exc:
        print(f"[db.get_activity_stats] {exc}")
        out["available"] = False
        return out

    for r in rows:
        ts = parse_ts(r.get("changed_at"))
        if not ts:
            continue
        y, w, _ = ts.isocalendar()
        key = f"{y}-W{w:02d}"
        out["by_week"][key] = out["by_week"].get(key, 0) + 1
        if r.get("new_status") == "Completed":
            out["completed_by_week"][key] = out["completed_by_week"].get(key, 0) + 1
    out["total"] = len(rows)
    return out


def get_engagement_by_person(weeks: int = 4) -> list[dict]:
    """Updates per person over the period — the measure of whether any of the
    engagement work is actually landing. Sorted by activity, least active last."""
    since = (_dt_date.today() - _dt_mod.timedelta(weeks=weeks)).isoformat()
    try:
        rows = supabase.table("status_history").select(
            "changed_by_email, new_status, changed_at"
        ).gte("changed_at", since).execute().data or []
        users = supabase.table("users").select("email, name").eq(
            "is_approved", True
        ).execute().data or []
    except Exception as exc:
        print(f"[db.get_engagement_by_person] {exc}")
        return []

    per: dict[str, dict] = {
        u["email"]: {"email": u["email"], "name": u.get("name", u["email"]),
                     "updates": 0, "completed": 0, "last": None}
        for u in users
    }
    for r in rows:
        e = r.get("changed_by_email")
        if e not in per:
            continue
        per[e]["updates"] += 1
        if r.get("new_status") == "Completed":
            per[e]["completed"] += 1
        ts = parse_ts(r.get("changed_at"))
        if ts and (per[e]["last"] is None or ts > per[e]["last"]):
            per[e]["last"] = ts

    out = list(per.values())
    out.sort(key=lambda x: (-x["updates"], x["name"]))
    return out


def get_supervisor_digest(user_email: str, days: int = 7) -> dict:
    """What moved and what did not, among the items this person supervises."""
    since_dt = _dt_mod.datetime.utcnow() - _dt_mod.timedelta(days=days)
    threshold = stale_threshold()
    res = {"moved": [], "stuck": [], "blocked": [], "completed": []}
    try:
        tasks = supabase.table("tasks").select("*").eq(
            "is_archived", False
        ).eq("supervisor_email", user_email).execute().data or []
    except Exception as exc:
        print(f"[db.get_supervisor_digest] {exc}")
        return res

    for t in tasks:
        status = t.get("status") or "Not started"
        if status == "Cancelled":
            continue
        ts = parse_ts(t.get("updated_at")) or parse_ts(t.get("created_at"))
        recent = bool(ts and ts >= since_dt)
        if status == "Completed":
            if recent:
                res["completed"].append(t)
            continue
        if status == "Blocked":
            res["blocked"].append(t)
        elif recent:
            res["moved"].append(t)
        elif is_stale(t, threshold):
            res["stuck"].append(t)
    return res


# ── Task labels (used for the "tentative" paper flag) ─────────────────────────
#
# The labels / task_labels tables have been in the schema since day one and
# were never used. They are exactly what the "tentative topic" flag needs, so
# no migration: a paper proposed by a student carries the 'tentative' label
# until the supervisor approves it (removes the label).

TENTATIVE_LABEL = "tentative"


def get_label_id(name: str, create: bool = True) -> int | None:
    try:
        rows = supabase.table("labels").select("id").eq("name", name).limit(1).execute().data
        if rows:
            return rows[0]["id"]
        if not create:
            return None
        ins = supabase.table("labels").insert({"name": name, "color": "#1565C0"}).execute().data
        return ins[0]["id"] if ins else None
    except Exception as exc:
        print(f"[db.get_label_id] {exc}")
        return None


def get_labelled_task_ids(name: str) -> set[int]:
    """Task ids carrying the given label. Empty set on any failure."""
    try:
        lid = get_label_id(name, create=False)
        if lid is None:
            return set()
        rows = supabase.table("task_labels").select("task_id").eq("label_id", lid).execute().data or []
        return {r["task_id"] for r in rows}
    except Exception as exc:
        print(f"[db.get_labelled_task_ids] {exc}")
        return set()


def set_task_label(task_id: int, name: str, on: bool) -> bool:
    try:
        lid = get_label_id(name, create=True)
        if lid is None:
            return False
        if on:
            existing = supabase.table("task_labels").select("task_id").eq(
                "task_id", task_id).eq("label_id", lid).execute().data
            if not existing:
                supabase.table("task_labels").insert(
                    {"task_id": task_id, "label_id": lid}).execute()
        else:
            supabase.table("task_labels").delete().eq(
                "task_id", task_id).eq("label_id", lid).execute()
        return True
    except Exception as exc:
        print(f"[db.set_task_label] {exc}")
        return False


# ── My Status deck (personal portfolio for 1:1s and PhD reviews) ──────────────

def get_my_status_pack(email: str, since: _dt_date) -> dict:
    """Everything one person shows at a review: tasks, papers, targets, PhD.

    Scopus publications are fetched by the VIEW (network + API key) and added
    to the pack afterwards; everything here is database-only and degrades to
    empty sections.
    """
    threshold = stale_threshold()
    today = _dt_date.today()
    pack = {"user": {}, "since": since, "until": today,
            "task_rows": [], "completed": [], "counts": {},
            "paper_drafts": [], "conf_papers": [], "conferences": [],
            "publications": None}

    try:
        urows = supabase.table("users").select("*").eq("email", email).execute().data or []
        pack["user"] = urows[0] if urows else {"email": email, "name": email}
        projects = supabase.table("projects").select("id, name, acronym, identifier").eq(
            "is_archived", False).execute().data or []
        tasks = supabase.table("tasks").select("*").eq("owner_email", email).execute().data or []
        subs = supabase.table("subtasks").select("*").eq("owner_email", email).eq(
            "is_archived", False).execute().data or []
        all_tasks = supabase.table("tasks").select("id, name, project_id").execute().data or []
        users = supabase.table("users").select("email, name").execute().data or []
    except Exception as exc:
        print(f"[db.get_my_status_pack] {exc}")
        return pack

    pmap = {p["id"]: p for p in projects}
    tmap = {t["id"]: t for t in all_tasks}
    umap = {u["email"]: u for u in users}
    plabel = lambda pid: (pmap.get(pid, {}).get("acronym")
                          or pmap.get(pid, {}).get("identifier")
                          or pmap.get(pid, {}).get("name") or "")

    conf_proj = get_or_create_conference_project(create=False)
    conf_pid = conf_proj["id"] if conf_proj else None

    live = [t for t in tasks if (t.get("status") or "") != "Cancelled"]
    # Conference papers are shown in their own section, not among the tasks.
    plain = [t for t in live if t.get("project_id") != conf_pid]

    active = [t for t in plain if not t.get("is_archived")
              and (t.get("status") or "") != "Completed"
              and t.get("project_id") in pmap]
    done_period = [t for t in plain
                   if t.get("status") == "Completed"
                   and (cd := _norm_conf_date(t.get("completion_date")))
                   and cd >= since.isoformat()]

    def _row(item, level, kind, pid):
        fresh, sev = _fresh_label(item, threshold)
        return {"level": level, "kind": kind, "name": item.get("name") or "—",
                "status": item.get("status") or "Not started",
                "deadline": item.get("deadline"),
                "people": _people_label(item, umap), "fresh": fresh, "sev": sev}

    # Task tree grouped by project
    by_proj: dict[int, list] = {}
    for t in active:
        by_proj.setdefault(t.get("project_id"), []).append(t)
    for pid in sorted(by_proj, key=lambda p: plabel(p)):
        pack["task_rows"].append({"level": 0, "kind": "group",
                                  "name": f"{plabel(pid)} — {pmap.get(pid, {}).get('name', '')}",
                                  "status": "", "deadline": None, "people": "",
                                  "fresh": "", "sev": "none"})
        for t in sorted(by_proj[pid], key=lambda x: x.get("deadline") or "9999-12-31"):
            pack["task_rows"].append(_row(t, 1, "task", pid))
            for s in [s for s in subs if s.get("task_id") == t["id"]
                      and (s.get("status") or "") not in ("Completed", "Cancelled")]:
                pack["task_rows"].append(_row(s, 2, "subtask", pid))

    pack["completed"] = [
        {"level": 1, "kind": "task",
         "name": f"[{plabel(t.get('project_id'))}] {t.get('name','')}",
         "status": "Completed", "deadline": t.get("completion_date"),
         "people": "", "fresh": "", "sev": "ok"}
        for t in sorted(done_period, key=lambda x: x.get("completion_date") or "")
    ]

    # Paper deliverables (journal drafts etc.) where I am owner or supervisor
    try:
        pd_rows = supabase.table("deliverables").select("*").eq("type", "paper").eq(
            "is_archived", False).or_(rbac_or_filter(email)).execute().data or []
        pack["paper_drafts"] = [
            {**d, "_project": plabel(d.get("project_id"))} for d in pd_rows
        ]
    except Exception as exc:
        print(f"[db.get_my_status_pack] paper drafts: {exc}")

    # Conference papers I own or supervise, with target + tentative flag
    tentative_ids = get_labelled_task_ids(TENTATIVE_LABEL)
    if conf_pid:
        conf_delivs = {}
        try:
            conf_delivs = {d["id"]: d.get("name") or "" for d in
                           supabase.table("deliverables").select("id, name").eq(
                               "project_id", conf_pid).execute().data or []}
        except Exception:
            pass
        mine_conf = [t for t in live if t.get("project_id") == conf_pid
                     and not t.get("is_archived")
                     and (t.get("owner_email") == email or t.get("supervisor_email") == email)]
        for t in mine_conf:
            pack["conf_papers"].append({
                **t,
                "_target": conf_delivs.get(t.get("deliverable_id"), ""),
                "_tentative": t["id"] in tentative_ids,
            })

    confs = get_conferences(show_archived=False) or []
    pack["conferences"] = confs

    pack["counts"] = {
        "active": len(active),
        "completed": len(done_period),
        "papers": len(pack["paper_drafts"]) + len(pack["conf_papers"]),
        "tentative": sum(1 for p in pack["conf_papers"] if p["_tentative"]),
    }
    return pack


# ── Deck data: meeting delta and project review ───────────────────────────────

def get_meeting_delta(since: _dt_date, until: _dt_date | None = None) -> dict:
    """What changed per person between two dates — feeds the meeting deck.

    'moved' means the status changed in the window; 'stale' means nobody has
    touched it for at least the freshness threshold. Those two are the only
    items worth meeting time.
    """
    until = until or _dt_date.today()
    threshold = stale_threshold()
    out = {"by_person": [], "totals": {"completed": 0, "moved": 0, "blocked": 0, "stale": 0}}

    try:
        tasks = supabase.table("tasks").select("*").eq("is_archived", False).execute().data or []
        projects = supabase.table("projects").select("id, name, acronym, identifier").execute().data or []
        users = supabase.table("users").select("email, name").eq("is_approved", True).order("name").execute().data or []
    except Exception as exc:
        print(f"[db.get_meeting_delta] {exc}")
        return out
    pmap = {p["id"]: (p.get("acronym") or p.get("identifier") or p.get("name") or "") for p in projects}

    # Status changes in the window (optional: absent before the migration)
    changed_ids: set[int] = set()
    try:
        hist = supabase.table("status_history").select("item_id, item_type, changed_at").gte(
            "changed_at", since.isoformat()
        ).execute().data or []
        changed_ids = {h["item_id"] for h in hist if h.get("item_type") == "task"}
    except Exception:
        pass

    for u in users:
        email = u["email"]
        mine = [t for t in tasks if t.get("owner_email") == email
                and (t.get("status") or "") != "Cancelled"]
        if not mine:
            continue

        completed, moved, blocked, stale = [], [], [], []
        for t in mine:
            t = {**t, "_project": pmap.get(t.get("project_id"), ""),
                 "_stale": days_since_update(t)}
            status = t.get("status") or "Not started"
            cd = _norm_conf_date(t.get("completion_date"))
            if status == "Completed":
                if cd and since.isoformat() <= cd <= until.isoformat():
                    completed.append(t)
                continue
            if status == "Blocked":
                blocked.append(t)
            elif t["id"] in changed_ids:
                moved.append(t)
            if status != "Blocked" and is_stale(t, threshold):
                stale.append(t)

        active = len([t for t in mine if (t.get("status") or "") not in ("Completed", "Cancelled")])
        if not (completed or moved or blocked or stale):
            continue
        out["by_person"].append({
            "email": email, "name": u.get("name", email), "active": active,
            "completed": completed, "moved": moved, "blocked": blocked, "stale": stale,
        })
        out["totals"]["completed"] += len(completed)
        out["totals"]["moved"] += len(moved)
        out["totals"]["blocked"] += len(blocked)
        out["totals"]["stale"] += len(stale)

    # Chained speaking order: consecutive people talk about related work.
    # Each person gets a dominant project (most frequent among their delta
    # items); people are grouped by it, groups are ordered by how much
    # attention they need (blocked + idle), and the same rule orders people
    # inside a group. The meeting still starts where help is needed most,
    # but similar activities now follow one another.
    from collections import Counter

    def _attention(p: dict) -> int:
        return len(p["blocked"]) + len(p["stale"])

    for p in out["by_person"]:
        items = p["completed"] + p["moved"] + p["blocked"] + p["stale"]
        counts = Counter(i.get("_project") or "" for i in items)
        p["dominant_project"] = counts.most_common(1)[0][0] if counts else ""

    group_attention: dict[str, int] = {}
    for p in out["by_person"]:
        g = p["dominant_project"]
        group_attention[g] = group_attention.get(g, 0) + _attention(p)

    out["by_person"].sort(key=lambda p: (
        -group_attention.get(p["dominant_project"], 0),
        p["dominant_project"],
        -_attention(p),
        p["name"],
    ))
    return out


def _people_label(item: dict, umap: dict) -> str:
    """'Owner / Supervisor' in short form for a dense slide row."""
    def short(email):
        n = umap.get(email, {}).get("name") or email or ""
        parts = n.split()
        return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else n
    o = short(item.get("owner_email")) if item.get("owner_email") else "—"
    s = short(item.get("supervisor_email")) if item.get("supervisor_email") else ""
    return f"{o} / {s}" if s and s != o else o


def _fresh_label(item: dict, threshold: int) -> tuple[str, str]:
    """(text, severity) describing how recently the item was touched."""
    d = days_since_update(item)
    if d is None:
        return "—", "none"
    if d == 0:
        return "today", "ok"
    if d < threshold:
        return f"{d}d", "ok"
    return f"{d}d", "bad" if d >= threshold * 2 else "warn"


def get_upcoming_deliverables(months: int = 3) -> list[dict]:
    """Deliverables due within the horizon — section 1 of the meeting deck."""
    today = _dt_date.today()
    limit = (today + _dt_mod.timedelta(days=int(30.44 * months))).isoformat()
    try:
        delivs = supabase.table("deliverables").select("*").eq(
            "is_archived", False).order("deadline").execute().data or []
        projects = supabase.table("projects").select("id, name, acronym, identifier").execute().data or []
        tasks = supabase.table("tasks").select(
            "id, deliverable_id, status").eq("is_archived", False).execute().data or []
        users = supabase.table("users").select("email, name").execute().data or []
    except Exception as exc:
        print(f"[db.get_upcoming_deliverables] {exc}")
        return []
    pmap = {p["id"]: p for p in projects}
    umap = {u["email"]: u for u in users}

    out = []
    for d in delivs:
        dl = _norm_conf_date(d.get("deadline"))
        if not dl or dl > limit:
            continue
        if (d.get("status") or "") in ("Completed", "Cancelled"):
            continue
        dts = [t for t in tasks if t.get("deliverable_id") == d["id"]
               and (t.get("status") or "") != "Cancelled"]
        done = len([t for t in dts if t.get("status") == "Completed"])
        p = pmap.get(d.get("project_id"), {})
        out.append({
            **d,
            "_project": p.get("acronym") or p.get("identifier") or p.get("name") or "",
            "_people": _people_label(d, umap),
            "_days": (_dt_date.fromisoformat(dl) - today).days,
            "_done": done, "_total": len(dts),
            "_pct": round(100 * done / len(dts)) if dts else 0,
        })
    out.sort(key=lambda x: x["_days"])
    return out


def get_project_trees() -> list[dict]:
    """project → deliverable → task → subtask, flattened into slide rows.

    Section 2 of the deck. Each row carries owner/supervisor, deadline and how
    fresh it is, because on long tasks freshness is the real progress signal.
    """
    threshold = stale_threshold()
    try:
        projects = supabase.table("projects").select("*").eq(
            "is_archived", False).order("name").execute().data or []
        delivs = supabase.table("deliverables").select("*").eq(
            "is_archived", False).execute().data or []
        tasks = supabase.table("tasks").select("*").eq("is_archived", False).execute().data or []
        subs = supabase.table("subtasks").select("*").eq("is_archived", False).execute().data or []
        users = supabase.table("users").select("email, name").execute().data or []
    except Exception as exc:
        print(f"[db.get_project_trees] {exc}")
        return []
    umap = {u["email"]: u for u in users}
    live = lambda i: (i.get("status") or "") != "Cancelled"

    def row(item, level, kind):
        fresh, sev = _fresh_label(item, threshold)
        return {
            "level": level, "kind": kind, "name": item.get("name") or "—",
            "status": item.get("status") or "Not started",
            "deadline": item.get("deadline"),
            "people": _people_label(item, umap),
            "fresh": fresh, "sev": sev,
        }

    out = []
    for p in projects:
        rows = []
        p_delivs = sorted([d for d in delivs if d.get("project_id") == p["id"]],
                          key=lambda d: d.get("deadline") or "9999-12-31")
        p_tasks = [t for t in tasks if t.get("project_id") == p["id"] and live(t)]
        for d in p_delivs:
            rows.append(row(d, 0, "deliverable"))
            d_tasks = sorted([t for t in p_tasks if t.get("deliverable_id") == d["id"]],
                             key=lambda t: t.get("deadline") or "9999-12-31")
            for t in d_tasks:
                rows.append(row(t, 1, "task"))
                for s in [s for s in subs if s.get("task_id") == t["id"] and live(s)]:
                    rows.append(row(s, 2, "subtask"))
        orphans = sorted([t for t in p_tasks if not t.get("deliverable_id")],
                         key=lambda t: t.get("deadline") or "9999-12-31")
        if orphans:
            rows.append({"level": 0, "kind": "group", "name": "No deliverable",
                         "status": "", "deadline": None, "people": "", "fresh": "", "sev": "none"})
            for t in orphans:
                rows.append(row(t, 1, "task"))
                for s in [s for s in subs if s.get("task_id") == t["id"] and live(s)]:
                    rows.append(row(s, 2, "subtask"))
        if rows:
            out.append({
                "name": p.get("name"), "acronym": p.get("acronym") or p.get("identifier") or "",
                "rows": rows,
                "counts": {"deliverables": len(p_delivs), "tasks": len(p_tasks)},
            })
    return out


def get_conference_pack(months: int = 12) -> list[dict]:
    """Upcoming conferences with the paper drafts targeting each — section 4.

    Papers are linked through the deliverable that ``ensure_conference_deliverable``
    creates inside the Conference Papers project, named "<ACRONYM> <year>".
    """
    today = _dt_date.today()
    limit = (today + _dt_mod.timedelta(days=int(30.44 * months))).isoformat()
    threshold = stale_threshold()
    confs = get_conferences(show_archived=False)
    if not confs:
        return []

    proj = get_or_create_conference_project(create=False)
    papers, delivs, umap = [], [], {}
    try:
        users = supabase.table("users").select("email, name").execute().data or []
        umap = {u["email"]: u for u in users}
        if proj:
            delivs = supabase.table("deliverables").select("id, name").eq(
                "project_id", proj["id"]).execute().data or []
            papers = supabase.table("tasks").select("*").eq(
                "project_id", proj["id"]).eq("is_archived", False).execute().data or []
    except Exception as exc:
        print(f"[db.get_conference_pack] {exc}")
    dname = {d["id"]: (d.get("name") or "") for d in delivs}

    out = []
    for c in confs:
        sub = _norm_conf_date(c.get("submission_deadline"))
        if not sub or sub > limit:
            continue
        label = (c.get("acronym") or c.get("name") or "").strip()
        key = f"{label} {c['year']}".strip() if c.get("year") else label
        mine = []
        for t in papers:
            if (t.get("status") or "") == "Cancelled":
                continue
            if dname.get(t.get("deliverable_id"), "").strip().lower() == key.lower():
                fresh, sev = _fresh_label(t, threshold)
                mine.append({
                    "level": 1, "kind": "task", "name": t.get("name") or "—",
                    "status": t.get("status") or "Not started",
                    "deadline": t.get("deadline"), "people": _people_label(t, umap),
                    "fresh": fresh, "sev": sev,
                })
        out.append({
            **c,
            "_label": key or "Conference",
            "_days": (_dt_date.fromisoformat(sub) - today).days,
            "_papers": mine,
        })
    out.sort(key=lambda x: x["_days"])
    return out


def get_project_review(project_id: int, period_label: str = "") -> dict:
    """Cumulative status per deliverable — feeds the review deck.

    Not a delta: a funder needs 'WP2 at 70%, one open risk', not what moved
    last week. Archived tasks are included: a completed-then-archived task is
    still progress that was made.
    """
    today = _dt_date.today()
    threshold = stale_threshold()
    out = {"project": {}, "deliverables": [], "no_deliverable": [],
           "totals": {"total": 0, "completed": 0, "overdue": 0, "at_risk": 0},
           "period_label": period_label}
    try:
        pr = supabase.table("projects").select("*").eq("id", project_id).execute().data or []
        out["project"] = pr[0] if pr else {}
        delivs = supabase.table("deliverables").select("*").eq(
            "project_id", project_id).eq("is_archived", False).order("deadline").execute().data or []
        tasks = supabase.table("tasks").select("*").eq("project_id", project_id).execute().data or []
    except Exception as exc:
        print(f"[db.get_project_review] {exc}")
        return out

    tasks = [t for t in tasks if (t.get("status") or "") != "Cancelled"]

    def bucket(ts: list[dict]) -> dict:
        done = [t for t in ts if t.get("status") == "Completed"]
        prog = [t for t in ts if t.get("status") == "Working on"]
        risks = []
        for t in ts:
            if t.get("status") == "Completed":
                continue
            dl = _norm_conf_date(t.get("deadline"))
            if t.get("status") == "Blocked":
                risks.append({**t, "_why": "blocked"})
            elif dl and dl < today.isoformat():
                days = (today - _dt_date.fromisoformat(dl)).days
                risks.append({**t, "_why": f"{days}d overdue"})
            elif is_stale(t, threshold):
                risks.append({**t, "_why": f"idle {days_since_update(t)}d"})
        total = len(ts)
        return {
            "completed": done, "in_progress": prog, "risks": risks,
            "totals": {"total": total, "completed": len(done),
                       "pct": round(100 * len(done) / total) if total else 0},
        }

    for d in delivs:
        dts = [t for t in tasks if t.get("deliverable_id") == d["id"]]
        b = bucket(dts)
        out["deliverables"].append({**d, **b})

    orphans = [t for t in tasks if not t.get("deliverable_id")]
    out["no_deliverable"] = orphans

    total = len(tasks)
    out["totals"] = {
        "total": total,
        "completed": len([t for t in tasks if t.get("status") == "Completed"]),
        "overdue": len([
            t for t in tasks
            if t.get("status") != "Completed"
            and (dl := _norm_conf_date(t.get("deadline"))) and dl < today.isoformat()
        ]),
        "at_risk": len([
            t for t in tasks
            if t.get("status") == "Blocked" or (t.get("status") != "Completed" and is_stale(t, threshold))
        ]),
    }
    return out


# ── Contracts (PhD students and contractors) ──────────────────────────────────

CONTRACT_TYPES = ("phd", "contract")


def get_contracts(user_email: str | None = None, active_only: bool = False) -> list | None:
    """Contracts, newest first. Returns None when the table is missing."""
    try:
        q = supabase.table("contracts").select("*")
        if user_email:
            q = q.eq("user_email", user_email)
        if active_only:
            q = q.eq("is_active", True)
        return q.order("start_date", desc=True).execute().data or []
    except Exception as exc:
        print(f"[db.get_contracts] {exc}")
        return None


def upsert_contract(payload: dict, contract_id: int | None = None) -> tuple[bool, str]:
    if not payload.get("user_email"):
        return False, "A person is required."
    if payload.get("contract_type") not in CONTRACT_TYPES:
        return False, "Invalid contract type."
    start, end = payload.get("start_date"), payload.get("end_date")
    if start and end and str(end) < str(start):
        return False, "End date is before the start date."
    try:
        if contract_id is None:
            supabase.table("contracts").insert(payload).execute()
        else:
            supabase.table("contracts").update(payload).eq("id", contract_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def delete_contract(contract_id: int) -> tuple[bool, str]:
    try:
        supabase.table("contracts").delete().eq("id", contract_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def contract_covers(contract: dict, day: _dt_date) -> bool:
    """True when `day` falls inside the contract period (open ends allowed)."""
    start = _norm_conf_date(contract.get("start_date"))
    end = _norm_conf_date(contract.get("end_date"))
    if start and day < _dt_date.fromisoformat(start):
        return False
    if end and day > _dt_date.fromisoformat(end):
        return False
    return True


def get_timesheet_contracts(user_email: str) -> list:
    """Active 'contract' contracts of a user — the ones requiring timesheets."""
    rows = get_contracts(user_email=user_email, active_only=True) or []
    return [c for c in rows if c.get("contract_type") == "contract" and c.get("project_id")]


# ── Project activity rows (configurable timesheet lines) ──────────────────────

def get_project_activities(project_id: int) -> list:
    try:
        return (
            supabase.table("project_activities").select("*")
            .eq("project_id", project_id)
            .order("sort_order", desc=False)
            .execute().data or []
        )
    except Exception as exc:
        print(f"[db.get_project_activities] {exc}")
        return []


def upsert_project_activity(payload: dict, activity_id: int | None = None) -> tuple[bool, str]:
    if not (payload.get("name") or "").strip():
        return False, "Activity name is required."
    try:
        if activity_id is None:
            supabase.table("project_activities").insert(payload).execute()
        else:
            supabase.table("project_activities").update(payload).eq("id", activity_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def delete_project_activity(activity_id: int) -> tuple[bool, str]:
    try:
        supabase.table("project_activities").delete().eq("id", activity_id).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ── Timesheets ────────────────────────────────────────────────────────────────

def get_timesheet(user_email: str, project_id: int, year: int, month: int) -> dict | None:
    try:
        rows = (
            supabase.table("timesheets").select("*")
            .eq("user_email", user_email).eq("project_id", project_id)
            .eq("year", year).eq("month", month)
            .limit(1).execute().data
        )
        return rows[0] if rows else None
    except Exception as exc:
        print(f"[db.get_timesheet] {exc}")
        return None


def save_timesheet(user_email: str, project_id: int, year: int, month: int,
                   grid: dict, status: str, updated_by: str | None) -> tuple[bool, str]:
    """Insert or update the monthly timesheet. `grid` = {activity_id: {day: hours}}."""
    import datetime as _dt
    payload = {
        "user_email": user_email,
        "project_id": project_id,
        "year": int(year),
        "month": int(month),
        "grid": grid,
        "status": status,
        "updated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "updated_by_email": updated_by,
    }
    try:
        existing = get_timesheet(user_email, project_id, year, month)
        if existing:
            supabase.table("timesheets").update(payload).eq("id", existing["id"]).execute()
        else:
            supabase.table("timesheets").insert(payload).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def get_pending_timesheets(user_email: str, today: _dt_date | None = None) -> list[dict]:
    """Months the user still has to complete, for the dashboard reminder.

    Looks at the current month and the previous one (the usual reporting lag),
    for every active contractor contract, skipping months outside the contract
    period. Returns [{contract, project_id, year, month, status}].
    """
    import datetime as _dt
    today = today or _dt_date.today()

    periods: list[tuple[int, int]] = []
    prev = (today.replace(day=1) - _dt.timedelta(days=1))
    periods.append((prev.year, prev.month))
    periods.append((today.year, today.month))

    pending: list[dict] = []
    for c in get_timesheet_contracts(user_email):
        for (y, m) in periods:
            # The month is in scope only if the contract covers at least one of its days.
            last_day = _month_last_day(y, m)
            if not (contract_covers(c, _dt_date(y, m, 1)) or contract_covers(c, last_day)):
                continue
            ts = get_timesheet(user_email, c["project_id"], y, m)
            if ts and ts.get("status") == "completed":
                continue
            pending.append({
                "contract": c,
                "project_id": c["project_id"],
                "year": y,
                "month": m,
                "status": (ts or {}).get("status", "missing"),
            })
    return pending


def _month_last_day(year: int, month: int) -> _dt_date:
    import calendar as _cal
    return _dt_date(year, month, _cal.monthrange(year, month)[1])
