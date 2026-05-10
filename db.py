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
    "expiring_threshold_days": 14,
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
