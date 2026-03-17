"""utils/helpers.py — Shared formatting utilities."""

from datetime import date, datetime
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
