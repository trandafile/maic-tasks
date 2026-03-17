"""utils/helpers.py — Shared formatting utilities."""

from datetime import date, datetime
import datetime as _dt
import re


def fmt_date(d) -> str:
    """Return a YYYY/MM/DD string from a date, datetime, ISO string, or None."""
    if d is None:
        return "—"
    if isinstance(d, str):
        if not d:
            return "—"
        try:
            d = date.fromisoformat(d[:10])
        except Exception:
            return d
    if isinstance(d, (date, datetime)):
        return d.strftime("%d/%m/%Y")
    return str(d)


def strip_markdown(text: str) -> str:
    """Remove markdown syntax for PDF plain text output."""
    if not text:
        return ""
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'^[-*+]\s+', '• ', text, flags=re.MULTILINE)
    return text.strip()


# ── Deadline-based sorting for tasks / subtasks ─────────────────────────────────

PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4, None: 4}


def sort_tasks_by_deadline(tasks: list) -> list:
    """
    Sort tasks/subtasks: overdue first → soonest deadline → future → no deadline.
    Secondary sort: priority (urgent → none).
    """
    today = _dt.date.today()

    def sort_key(t):
        dl_str = t.get("deadline")
        priority = (t.get("priority") or "none").lower()
        prio_val = PRIORITY_ORDER.get(priority, 4)

        if not dl_str:
            # No deadline: sort last (use far future date)
            return (1, _dt.date(9999, 12, 31), prio_val)
        try:
            dl = _dt.date.fromisoformat(dl_str)
        except Exception:
            return (1, _dt.date(9999, 12, 31), prio_val)

        if dl < today:
            # Overdue: sort first, most overdue first
            return (0, dl, prio_val)
        else:
            # Today or future: sort by date ASC
            return (0, dl, prio_val)

    return sorted(tasks, key=sort_key)
