"""utils/rows.py — ONE row style for deliverables, tasks and subtasks.

Every list of work items in the app (Projects tree, the review queue, Reports,
later the Dashboard) renders its rows through this module, so they look and
read the same everywhere:

    name (+ priority, path)  |  status  |  deadline  |  owner / supervisor  | actions

* The row BAND is tinted by urgency — light red when overdue, light orange when
  due within the threshold — via marker classes styled in app.py (``ROW_CSS``),
  so the tint spans the action buttons too.
* Completed and cancelled work is struck through and muted, not hidden.
* People are always full names: owner on top, supervisor underneath.
* The sequence id (PRJ-40) is not a column: it lives in the hover tooltip. It is
  still the reference used in e-mails, PDFs and the details dialog.

Layout contract for callers (Streamlit cannot put a button inside HTML, so a
row is two columns):

    c_row, c_act = st.columns(ROW_COLS, vertical_alignment="center")
    with c_row:
        st.html(row_html(item, ...))
    with c_act:
        ...icon buttons (type="tertiary")...
"""

from __future__ import annotations

import datetime as _dt
import html as _html

# ── Palette ───────────────────────────────────────────────────────────────────
# Row tints are deliberately pale: they must read as a wash behind black text,
# not as a warning panel. The left accent carries the colour.
ROW_BG = {
    "overdue": "#FFF6F6",
    "soon":    "#FFFCF7",
}
ROW_ACCENT = {
    "overdue": "#EBA3A3",
    "soon":    "#F8DDB5",
}
TEXT_OVERDUE = "#B3261E"
TEXT_SOON    = "#A15C00"
TEXT_MUTED   = "#80868B"
TEXT_SOFT    = "#5F6368"
TEXT_MAIN    = "#1F2328"

STATUS_STYLE = {                      # fg, bg
    "Not started": ("#5F6368", "#F1F3F4"),
    "Working on":  ("#1558B0", "#E8F0FE"),
    "Blocked":     ("#B3261E", "#FCE8E6"),
    "Completed":   ("#1E7E34", "#E6F4EA"),
    "Cancelled":   ("#80868B", "#F1F3F4"),
}
PRIORITY_STYLE = {                    # fg, border — outlined, never a filled block
    "low":    ("#5F6368", "#DADCE0"),
    "medium": ("#A15C00", "#F3D19C"),
    "high":   ("#B3261E", "#F1B0AB"),
    "urgent": ("#7B1FA2", "#D7AEE5"),
}
INACTIVE = ("Completed", "Cancelled")

# Column share between the HTML row and its action buttons.
ROW_COLS = [12, 1.7]

# Grid of the HTML part. Kept in one place so header and rows always align.
# Every cell is ONE line: owner and supervisor side by side, date and delta
# side by side, the path muted after the name. Height comes from rhythm (CSS
# below), never from wrapped cells.
_GRID = "grid-template-columns:minmax(0,1fr) 96px 150px 290px;"

# Injected once by app.py. Marker classes inside st.html let the CSS reach the
# whole Streamlit row (both columns), which inline styles alone cannot do.
#
# Vertical rhythm, as in typesetting:
#   subtasks  — set solid: no rule, no gap (the lines of a paragraph)
#   task      — a hairline and a small gap above (a new paragraph)
#   deliverable — its own bordered block with the larger gap (a section)
#   flat lists (dashboard, review) — every row a thin rule, no grouping
#
# app.py pads EVERY column block by 10px top and bottom — including the
# nested block of icon buttons inside a row. Both must be zeroed here, or a
# one-line row grows to 60px.
ROW_CSS = f"""
    div[data-testid='stHorizontalBlock']:has(.maic-row),
    div[data-testid='stHorizontalBlock']:has(.maic-row-head),
    div[data-testid='stHorizontalBlock']:has(.maic-deliv-head) {{
        padding-top: 0 !important; padding-bottom: 0 !important;
        font-weight: normal !important; border-radius: 0 !important;
        min-height: 0;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row) div[data-testid='stHorizontalBlock'],
    div[data-testid='stHorizontalBlock']:has(.maic-deliv-head) div[data-testid='stHorizontalBlock'] {{
        padding-top: 0 !important; padding-bottom: 0 !important;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row) {{
        background-color: #FFFFFF !important;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row-task) {{
        margin-top: 7px; border-top: 1px solid #E6E8EB;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row-flat) {{
        border-top: 1px solid #EEF0F2;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row-overdue) {{
        background-color: {ROW_BG['overdue']} !important;
        box-shadow: inset 3px 0 0 {ROW_ACCENT['overdue']};
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row-soon) {{
        background-color: {ROW_BG['soon']} !important;
        box-shadow: inset 3px 0 0 {ROW_ACCENT['soon']};
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-deliv-head) {{
        background-color: #EEF7F3 !important;
        border-radius: 6px !important;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row-head) {{
        background-color: transparent !important;
    }}
    /* icon buttons: as tall as a line of text */
    div[data-testid='stHorizontalBlock']:has(.maic-row) button,
    div[data-testid='stHorizontalBlock']:has(.maic-deliv-head) button {{
        min-height: 0 !important; height: 22px; padding: 0 4px !important;
        line-height: 1 !important;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row) button p,
    div[data-testid='stHorizontalBlock']:has(.maic-deliv-head) button p {{
        font-size: 0.88rem; line-height: 1; margin: 0;
    }}
    div[data-testid='stHorizontalBlock']:has(.maic-row) div[data-testid='stCheckbox'] {{
        min-height: 0;
    }}
"""


def esc(v) -> str:
    return _html.escape(str(v if v is not None else ""))


def _parse(value) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def fmt(value) -> str:
    d = _parse(value)
    return d.strftime("%d/%m/%Y") if d else "—"


# ── Urgency ───────────────────────────────────────────────────────────────────

def urgency(item: dict, threshold: int = 14,
            today: _dt.date | None = None) -> tuple[str, int | None]:
    """(tier, days_to_deadline). tier ∈ done | overdue | soon | normal."""
    today = today or _dt.date.today()
    dl = _parse(item.get("deadline"))
    days = (dl - today).days if dl else None
    if (item.get("status") or "Not started") in INACTIVE:
        return "done", days
    if days is None:
        return "normal", None
    if days < 0:
        return "overdue", days
    if days <= threshold:
        return "soon", days
    return "normal", days


_PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def urgency_sort(items: list, threshold: int = 14) -> list:
    """Overdue (most late first) → due soon → later → no deadline → done."""
    far = _dt.date(9999, 12, 31)

    def key(it):
        tier, _ = urgency(it, threshold)
        rank = {"overdue": 0, "soon": 1, "normal": 2, "done": 3}[tier]
        dl = _parse(it.get("deadline")) or far
        prio = _PRIORITY_RANK.get((it.get("priority") or "").lower(), 4)
        return (rank, dl, prio, (it.get("name") or "").lower())

    return sorted(items, key=key)


# ── Cells ─────────────────────────────────────────────────────────────────────

def chip(text: str, fg: str, bg: str, border: str | None = None) -> str:
    b = f"border:1px solid {border};" if border else ""
    return (f"<span style='display:inline-block;background:{bg};color:{fg};{b}"
            f"padding:0 6px;border-radius:4px;font-size:10.5px;font-weight:600;"
            f"white-space:nowrap;line-height:1.55'>{esc(text)}</span>")


def status_chip(status: str | None) -> str:
    s = status or "Not started"
    fg, bg = STATUS_STYLE.get(s, ("#5F6368", "#F1F3F4"))
    return chip(s, fg, bg)


def priority_chip(priority: str | None) -> str:
    p = (priority or "").lower()
    if p not in PRIORITY_STYLE:
        return ""
    fg, border = PRIORITY_STYLE[p]
    return chip(p, fg, "#FFFFFF", border)


def deadline_cell(item: dict, threshold: int = 14) -> str:
    tier, days = urgency(item, threshold)
    dl = _parse(item.get("deadline"))
    if not dl:
        return f"<span style='color:{TEXT_MUTED};font-size:12px'>—</span>"
    label = dl.strftime("%d/%m/%Y")
    if tier == "done":
        return f"<span style='color:{TEXT_MUTED};font-size:12px'>{label}</span>"
    if tier == "overdue":
        return (f"<span style='color:{TEXT_OVERDUE};font-size:12px;font-weight:600;"
                f"white-space:nowrap'>{label} <span style='font-weight:400;font-size:11px'>"
                f"· {abs(days)}d late</span></span>")
    if tier == "soon":
        when = "today" if days == 0 else f"in {days}d"
        return (f"<span style='color:{TEXT_SOON};font-size:12px;font-weight:600;"
                f"white-space:nowrap'>{label} <span style='font-weight:400;font-size:11px'>"
                f"· {when}</span></span>")
    return f"<span style='color:{TEXT_SOFT};font-size:12px'>{label}</span>"


def person_name(email: str | None, user_map: dict) -> str:
    """Full name for an e-mail. ``user_map`` values may be dicts or plain names."""
    if not email:
        return ""
    u = user_map.get(email)
    if isinstance(u, dict):
        return u.get("name") or email.split("@")[0]
    return u or email.split("@")[0]


def people_cell(owner_email: str | None, sup_email: str | None, user_map: dict,
                muted: bool = False) -> str:
    """'Owner Name · sup Name' on a single line (supervisor muted)."""
    owner = person_name(owner_email, user_map)
    sup = person_name(sup_email, user_map) if sup_email and sup_email != owner_email else ""
    if not owner and not sup:
        return f"<span style='color:{TEXT_MUTED};font-size:12px'>—</span>"
    main = TEXT_MUTED if muted else TEXT_MAIN
    sup_html = (f"<span style='color:{TEXT_MUTED};font-size:11px'> · sup {esc(sup)}</span>"
                if sup else "")
    return (f"<div style='white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
            f"font-size:12.5px;color:{main}'>{esc(owner or '—')}{sup_html}</div>")


def project_chip(label: str | None) -> str:
    if not label:
        return ""
    from utils.helpers import stable_colour
    return (f"<span style='background:{stable_colour(label)};color:#fff;padding:1px 6px;"
            f"border-radius:4px;font-size:10px;font-weight:700;margin-right:6px;"
            f"vertical-align:1px;white-space:nowrap'>{esc(label)}</span>")


# ── Rows ──────────────────────────────────────────────────────────────────────

def header_html(date_label: str = "Deadline", people_label: str = "Owner / supervisor",
                first_label: str = "Item") -> str:
    cell = f"font-size:10.5px;color:{TEXT_MUTED};letter-spacing:0.03em"
    return (f"<div class='maic-row-head' style='display:grid;{_GRID}gap:10px;"
            f"padding:3px 8px 0 8px;align-items:center'>"
            f"<span style='{cell}'>{esc(first_label)}</span>"
            f"<span style='{cell}'>Status</span>"
            f"<span style='{cell}'>{esc(date_label)}</span>"
            f"<span style='{cell}'>{esc(people_label)}</span></div>")


def row_html(item: dict, *, kind: str = "task", user_map: dict | None = None,
             threshold: int = 14, path: str | None = None,
             project_label: str | None = None, meta: str | None = None,
             date_html: str | None = None, readonly: bool = False,
             show_people: bool = True, strike_done: bool = True,
             flat: bool = False) -> str:
    """One work item as a one-line grid row.

    kind: "task" | "subtask". In a tree (default) a task opens a group and its
    subtasks are set solid beneath it; ``flat=True`` is for mixed lists
    (dashboard, review) where every row is separated the same way.
    ``path`` / ``meta`` follow the name, muted. ``date_html`` replaces the
    deadline cell. ``readonly`` = the viewer is not involved: muted, without
    people and deadline, as the rest of the app does.
    """
    user_map = user_map or {}
    status = item.get("status") or "Not started"
    tier, _ = urgency(item, threshold)
    if readonly:
        tier = "done" if tier == "done" else "normal"
    done = tier == "done"
    is_sub = kind == "subtask"

    classes = "maic-row " + ("maic-row-flat" if flat else
                             ("maic-row-sub" if is_sub else "maic-row-task"))
    if tier == "overdue":
        classes += " maic-row-overdue"
    elif tier == "soon":
        classes += " maic-row-soon"

    name_color = TEXT_MAIN if (not strike_done or not (done or readonly)) else TEXT_MUTED
    strike = ("text-decoration:line-through;text-decoration-color:#B8BCC2;"
              if done and strike_done else "")
    weight = "500" if is_sub else "600"
    size = "12.5px" if is_sub else "13.5px"
    indent = "20px" if (is_sub and not flat) else "0"
    prefix = "<span style='color:#9AA0A6;margin-right:3px'>↳</span>" if is_sub else ""
    seq = item.get("sequence_id")
    title = f" title='{esc(seq)}'" if seq else ""
    archived = (" <span style='font-size:10px;color:#80868B'>· archived</span>"
                if item.get("is_archived") else "")
    second = " · ".join(x for x in (path, meta) if x)
    second_html = (f"<span style='flex:1 1 auto;min-width:0;overflow:hidden;"
                   f"text-overflow:ellipsis;font-size:11px;color:{TEXT_MUTED}'>"
                   f"{esc(second)}</span>") if second else ""

    name_cell = (
        f"<div style='min-width:0;padding-left:{indent};display:flex;align-items:center;"
        f"gap:6px;white-space:nowrap;overflow:hidden'>"
        f"{project_chip(project_label)}{prefix}"
        f"<span{title} style='flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;"
        f"font-size:{size};font-weight:{weight};color:{name_color};{strike}'>"
        f"{esc(item.get('name', ''))}</span>"
        f"{'' if (done or readonly) else priority_chip(item.get('priority'))}{archived}"
        f"{second_html}</div>"
    )
    if readonly:
        date_cell, people = "", ""
    else:
        date_cell = date_html if date_html is not None else deadline_cell(item, threshold)
        people = people_cell(item.get("owner_email"), item.get("supervisor_email"),
                             user_map, muted=done and strike_done) if show_people else ""

    pad = "1px 8px" if is_sub else "3px 8px"
    return (f"<div class='{classes}' style='display:grid;{_GRID}gap:10px;"
            f"padding:{pad};align-items:center;line-height:1.3;"
            f"{'opacity:0.55;' if readonly else ''}'>"
            f"{name_cell}"
            f"<div>{status_chip(status)}</div>"
            f"<div style='white-space:nowrap'>{date_cell}</div>"
            f"<div style='min-width:0'>{people}</div>"
            f"</div>")


def progress_bar(done: int, total: int, width: int = 120) -> str:
    pct = round(100 * done / total) if total else 0
    colour = "#34A853" if pct == 100 else "#4A8BDF"
    return (f"<span style='display:inline-flex;align-items:center;gap:6px'>"
            f"<span style='display:inline-block;width:{width}px;height:5px;border-radius:3px;"
            f"background:#E3E6EA;overflow:hidden'><span style='display:block;width:{pct}%;"
            f"height:5px;background:{colour}'></span></span>"
            f"<span style='font-size:11px;color:{TEXT_SOFT}'>{done}/{total} tasks</span></span>")


# ── Deliverable band (Projects tree, Project Report) ─────────────────────────

def deliverable_head_html(d: dict, d_tasks: list, user_map: dict, threshold: int = 14,
                          type_chip: str = "") -> str:
    """Deliverable band: name, type, status, deadline, progress, people."""
    status = d.get("status") or "Not started"
    tier, days = urgency(d, threshold)
    dl = d.get("deadline")
    if not dl:
        dl_html = ""
    elif tier == "overdue":
        dl_html = (f"<span style='font-size:12px;color:{TEXT_OVERDUE};font-weight:600'>"
                   f"📅 {fmt(dl)} · {abs(days)}d late</span>")
    elif tier == "soon":
        when = "today" if days == 0 else f"in {days}d"
        dl_html = (f"<span style='font-size:12px;color:{TEXT_SOON};font-weight:600'>"
                   f"📅 {fmt(dl)} · {when}</span>")
    else:
        dl_html = f"<span style='font-size:12px;color:#5F6368'>📅 {fmt(dl)}</span>"

    signoff = ""
    if d.get("completion_state") == "pending":
        signoff = chip("⏳ awaiting sign-off", "#8A5300", "#FFF1D6")
    archived = chip("archived", "#80868B", "#F1F3F4") if d.get("is_archived") else ""

    counted = [t for t in d_tasks if (t.get("status") or "") != "Cancelled"]
    done = len([t for t in counted if t.get("status") == "Completed"])
    owner = person_name(d.get("owner_email"), user_map) or "—"
    sup = person_name(d.get("supervisor_email"), user_map)
    people = f"owner {esc(owner)}" + (f" · sup {esc(sup)}" if sup else "")

    return (
        "<div class='maic-deliv-head' style='padding:4px 8px 3px 8px'>"
        "<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
        "<span style='font-size:10px;color:#2E8B6E;font-weight:700;letter-spacing:0.05em'>"
        "DELIVERABLE</span>"
        f"<span style='font-size:15px;font-weight:700;color:#0F4D3B'>{esc(d.get('name', ''))}</span>"
        f"{type_chip}"
        f"{status_chip(status)}{signoff}{archived}{dl_html}</div>"
        "<div style='display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:2px'>"
        f"{progress_bar(done, len(counted))}"
        f"<span style='font-size:12px;color:#3C4043'>{people}</span></div>"
        "</div>"
    )
