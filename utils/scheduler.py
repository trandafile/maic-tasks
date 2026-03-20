"""utils/scheduler.py — Weekly briefing and overdue alert scheduler.

Call check_and_send_deadline_reminders() once per session from app.py.
Users.last_reminder_sent deduplicates Monday briefings.
Tasks/Subtasks.last_reminder_sent deduplicate the one-shot overdue alert.
"""

import datetime

from db import get_settings
from utils.notifications import send_overdue_alert, send_weekly_briefing


_CLOSED = {"Completed", "Cancelled"}


def check_and_send_deadline_reminders():
    try:
        from core.supabase_client import supabase

        today = datetime.date.today()
        today_str = today.isoformat()
        cfg = get_settings()

        if not cfg.get("notifications_enabled"):
            return
        if not cfg.get("smtp_password"):
            return

        threshold = int(cfg.get("expiring_threshold_days", 14))
        is_monday = today.weekday() == 0
        yesterday = (today - datetime.timedelta(days=1)).isoformat()

        users = (
            supabase.table("users")
            .select("email, name, last_reminder_sent, avatar_color")
            .eq("is_approved", True)
            .execute()
            .data
            or []
        )
        tasks = supabase.table("tasks").select("*").eq("is_archived", False).execute().data or []
        subtasks = supabase.table("subtasks").select("*").eq("is_archived", False).execute().data or []
        projects = supabase.table("projects").select("id, name, acronym").execute().data or []
        deliverables = supabase.table("deliverables").select("id, name").execute().data or []

        proj_map = {project["id"]: project for project in projects}
        deliv_map = {deliverable["id"]: deliverable for deliverable in deliverables}
        task_map = {task["id"]: task for task in tasks}
        user_map = {user.get("email"): user for user in users}
        approved_emails = {user.get("email") for user in users if user.get("email")}

        def enrich(item: dict, is_subtask: bool = False) -> dict:
            enriched = dict(item)
            if is_subtask:
                parent = task_map.get(enriched.get("task_id"), {})
                proj = proj_map.get(parent.get("project_id"), {})
                deliv = deliv_map.get(parent.get("deliverable_id"), {})
                enriched["project_id"] = parent.get("project_id")
                enriched["deliverable_id"] = parent.get("deliverable_id")
                enriched["sequence_id"] = enriched.get("sequence_id") or f"SUB-{enriched['id']}"
            else:
                proj = proj_map.get(enriched.get("project_id"), {})
                deliv = deliv_map.get(enriched.get("deliverable_id"), {})
                enriched["sequence_id"] = enriched.get("sequence_id") or f"T-{enriched['id']}"

            enriched["project_name"] = proj.get("name", "")
            enriched["project_acronym"] = proj.get("acronym") or proj.get("name", "")
            enriched["deliverable_name"] = deliv.get("name", "")

            owner = user_map.get(enriched.get("owner_email"), {})
            enriched["owner_name"] = owner.get("name") or enriched.get("owner_email") or ""
            return enriched

        all_active = [
            enrich(task)
            for task in tasks
            if task.get("status") not in _CLOSED
        ] + [
            enrich(subtask, is_subtask=True)
            for subtask in subtasks
            if subtask.get("status") not in _CLOSED
        ]

        if is_monday:
            for user in users:
                email = user.get("email")
                if not email or user.get("last_reminder_sent") == today_str:
                    continue

                owned_items = [item for item in all_active if item.get("owner_email") == email]
                overdue = [item for item in owned_items if _deadline_before(item.get("deadline"), today)]
                upcoming = [
                    item for item in owned_items
                    if _deadline_within(item.get("deadline"), today, threshold)
                ]
                overdue_keys = {_item_key(item) for item in overdue}
                upcoming_keys = {_item_key(item) for item in upcoming}
                active = [
                    item for item in owned_items
                    if _item_key(item) not in overdue_keys and _item_key(item) not in upcoming_keys
                ]
                supervised_blocked = [
                    item for item in all_active
                    if item.get("supervisor_email") == email
                    and item.get("status") == "Blocked"
                    and item.get("owner_email") != email
                ]

                if send_weekly_briefing(
                    to_email=email,
                    name=user.get("name") or email,
                    overdue=overdue,
                    upcoming=upcoming,
                    active=active,
                    supervised_blocked=supervised_blocked,
                    threshold=threshold,
                ):
                    _update_user_last_reminder(supabase, email, today_str)

        for table_name, records, is_subtask in (
            ("tasks", tasks, False),
            ("subtasks", subtasks, True),
        ):
            for record in records:
                if record.get("status") in _CLOSED:
                    continue
                if record.get("deadline") != yesterday:
                    continue
                if record.get("last_reminder_sent") == today_str:
                    continue

                enriched = enrich(record, is_subtask=is_subtask)
                recipients = [
                    email
                    for email in {record.get("owner_email"), record.get("supervisor_email")}
                    if email and email in approved_emails
                ]
                if not recipients:
                    continue

                sent_any = False
                for email in recipients:
                    sent_any = send_overdue_alert(enriched, email) or sent_any

                if sent_any:
                    _update_item_last_reminder(supabase, table_name, record["id"], today_str)

    except Exception as e:
        print(f"[scheduler] Errore durante il check scadenze: {e}")


def _item_key(item: dict) -> tuple:
    return (item.get("id"), item.get("task_id"), item.get("sequence_id"), item.get("name"))


def _deadline_before(deadline_str: str | None, today: datetime.date) -> bool:
    if not deadline_str:
        return False
    try:
        return datetime.date.fromisoformat(deadline_str) < today
    except Exception:
        return False


def _deadline_within(deadline_str: str | None, today: datetime.date, threshold: int) -> bool:
    if not deadline_str:
        return False
    try:
        delta = (datetime.date.fromisoformat(deadline_str) - today).days
    except Exception:
        return False
    return 0 <= delta <= threshold


def _update_user_last_reminder(supabase, email: str, date_str: str):
    try:
        supabase.table("users").update({"last_reminder_sent": date_str}).eq("email", email).execute()
    except Exception as e:
        print(f"[scheduler] Impossibile aggiornare last_reminder_sent per user {email}: {e}")


def _update_item_last_reminder(supabase, table: str, record_id: int, date_str: str):
    try:
        supabase.table(table).update({"last_reminder_sent": date_str}).eq("id", record_id).execute()
    except Exception as e:
        print(f"[scheduler] Impossibile aggiornare last_reminder_sent ({table} #{record_id}): {e}")