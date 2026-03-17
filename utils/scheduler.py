"""utils/scheduler.py — Daily deadline reminder check.

Call check_and_send_deadline_reminders() once per session from app.py.
Requires columns last_reminder_sent (DATE) on tasks and subtasks tables.
See db.py for the required ALTER TABLE migration SQL.
"""

import datetime
from utils.notifications import send_deadline_reminder, send_task_overdue
from db import get_settings


# Statuses that are considered "closed" (no reminders needed)
_CLOSED = {"Completed", "Cancelled"}


def _enrich(item: dict, projects: list, deliverables: list) -> dict:
    """Add project_name and deliverable_name to a task/subtask dict."""
    proj_id = item.get("project_id")
    deliv_id = item.get("deliverable_id")
    item = dict(item)
    item["project_name"] = next(
        (p["name"] for p in projects if p["id"] == proj_id), ""
    )
    item["deliverable_name"] = next(
        (d["name"] for d in deliverables if d["id"] == deliv_id), ""
    ) if deliv_id else ""
    return item


def check_and_send_deadline_reminders():
    """
    For all active tasks/subtasks:
    - If deadline is within [today, today + threshold_days]: send reminder
      (once per day, tracked via last_reminder_sent column).
    - If deadline < today and status not closed: send overdue notice
      (once per day).

    Silently ignores DB errors for last_reminder_sent (column may not exist yet).
    """
    try:
        from core.supabase_client import supabase

        cfg       = get_settings()
        threshold = int(cfg.get("expiring_threshold_days", 7))
        today     = datetime.date.today()
        future    = today + datetime.timedelta(days=threshold)
        today_str = today.isoformat()

        # Load supporting data for enrichment
        projects     = supabase.table("projects").select("id, name").execute().data
        deliverables = supabase.table("deliverables").select("id, name").execute().data

        # ── Tasks ────────────────────────────────────────────────────────────
        tasks = (
            supabase.table("tasks")
            .select("*")
            .eq("is_archived", False)
            .not_.is_("deadline", "null")
            .execute()
            .data
        )

        for t in tasks:
            if t.get("status") in _CLOSED:
                continue
            deadline_str = t.get("deadline")
            if not deadline_str:
                continue
            try:
                deadline = datetime.date.fromisoformat(deadline_str)
            except Exception:
                continue

            last_sent = t.get("last_reminder_sent")
            if last_sent == today_str:
                continue  # already sent today

            enriched = _enrich(t, projects, deliverables)
            sent = False

            if deadline < today:
                # Overdue
                for email in _emails(t):
                    send_task_overdue(enriched, email)
                sent = True
            elif today <= deadline <= future:
                # Upcoming
                days_left = (deadline - today).days
                for email in _emails(t):
                    send_deadline_reminder(enriched, email, days_left)
                sent = True

            if sent:
                _update_last_reminder(supabase, "tasks", t["id"], today_str)

        # ── Subtasks ─────────────────────────────────────────────────────────
        subtasks = (
            supabase.table("subtasks")
            .select("*")
            .eq("is_archived", False)
            .not_.is_("deadline", "null")
            .execute()
            .data
        )

        # Build task → project mapping for subtasks
        task_map = {t["id"]: t for t in tasks}

        for s in subtasks:
            if s.get("status") in _CLOSED:
                continue
            deadline_str = s.get("deadline")
            if not deadline_str:
                continue
            try:
                deadline = datetime.date.fromisoformat(deadline_str)
            except Exception:
                continue

            last_sent = s.get("last_reminder_sent")
            if last_sent == today_str:
                continue

            # Inherit project info from parent task
            parent = task_map.get(s.get("task_id"), {})
            enriched_s = dict(s)
            enriched_s["project_id"] = parent.get("project_id")
            enriched_s["deliverable_id"] = parent.get("deliverable_id")
            enriched_s["sequence_id"] = s.get("sequence_id") or f"SUB-{s['id']}"
            enriched_s = _enrich(enriched_s, projects, deliverables)

            sent = False
            if deadline < today:
                for email in _emails(s):
                    send_task_overdue(enriched_s, email)
                sent = True
            elif today <= deadline <= future:
                days_left = (deadline - today).days
                for email in _emails(s):
                    send_deadline_reminder(enriched_s, email, days_left)
                sent = True

            if sent:
                _update_last_reminder(supabase, "subtasks", s["id"], today_str)

    except Exception as e:
        print(f"[scheduler] Errore durante il check scadenze: {e}")


def _emails(item: dict) -> list[str]:
    out = []
    for field in ("owner_email", "supervisor_email"):
        v = item.get(field)
        if v:
            out.append(v)
    return out


def _update_last_reminder(supabase, table: str, record_id: int, date_str: str):
    try:
        supabase.table(table).update({"last_reminder_sent": date_str}).eq("id", record_id).execute()
    except Exception as e:
        print(f"[scheduler] Impossibile aggiornare last_reminder_sent ({table} #{record_id}): {e}")
