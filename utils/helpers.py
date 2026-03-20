"""utils/helpers.py — Shared formatting utilities."""

from datetime import date, datetime
import datetime as _dt
import html
import json
import re


DELIVERABLE_TAG_PALETTE = {
    "Dark Teal": "#0F766E",
    "Navy Blue": "#1E3A8A",
    "Deep Eggplant": "#4A044E",
    "Charcoal Gray": "#334155",
    "Dark Burgundy": "#7F1D1D",
}

DEFAULT_DELIVERABLE_TAG_STYLES = [
    {"name": "paper", "color": "#0F766E"},
    {"name": "layout", "color": "#1E3A8A"},
    {"name": "prototype", "color": "#4A044E"},
]


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


def _normalize_hex_color(value: str | None, fallback: str = "#334155") -> str:
    color = (value or "").strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", color):
        return color
    return fallback


def get_contrast_text_color(bg_hex: str) -> str:
    """Return black or white text color based on WCAG-ish luminance threshold."""
    color = _normalize_hex_color(bg_hex, "#334155")[1:]
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
    return "#111111" if luminance >= 160 else "#FFFFFF"


def parse_deliverable_tag_styles(raw_value, fallback_to_default: bool = True) -> list[dict]:
    """Parse settings value into [{name, color}, ...] using palette-constrained fallback."""
    parsed = raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            parsed = []

    styles = []
    if isinstance(parsed, list):
        for row in parsed:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            color = _normalize_hex_color(row.get("color"), "#334155")
            if name:
                styles.append({"name": name, "color": color})

    if styles:
        return styles
    if fallback_to_default:
        return [dict(item) for item in DEFAULT_DELIVERABLE_TAG_STYLES]
    return []


def get_deliverable_tag_map(settings: dict | None = None) -> dict[str, str]:
    styles = parse_deliverable_tag_styles((settings or {}).get("deliverable_tag_styles"))
    return {s["name"].strip().lower(): s["color"] for s in styles if s.get("name")}


def get_deliverable_tag_color(tag_name: str | None, settings: dict | None = None) -> str:
    tag_map = get_deliverable_tag_map(settings)
    return tag_map.get((tag_name or "").strip().lower(), "#334155")


def deliverable_chip_html(tag_name: str | None, settings: dict | None = None) -> str:
    label = (tag_name or "generic").strip() or "generic"
    bg = get_deliverable_tag_color(label, settings)
    fg = get_contrast_text_color(bg)
    safe_label = html.escape(label)
    return (
        f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
        f"font-size:10px;font-weight:700;line-height:1.2;background:{bg};color:{fg};'>"
        f"{safe_label}</span>"
    )


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
