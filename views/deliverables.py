"""views/deliverables.py — Deliverables overview.

A single compact table, sorted by deadline, so the page answers one question at
a glance: *what has to be delivered next?* Headers are shown once at the top;
each row is tinted by urgency (overdue / due soon) and the deliverable name is
the dominant element typographically.
"""

import datetime
import html

import streamlit as st

from core.supabase_client import supabase
from db import get_settings
from utils.helpers import fmt_date, deliverable_chip_html
from utils.modals import person_pill_html
from utils.pdf_generator import generate_deliverables_pdf


# The deliverable name outranks a task name (14px/600), so it goes one step up.
_DELIV_NAME_STYLE = "font-size:15px;font-weight:700;color:#111;line-height:1.35;"

_STATUS_COLOURS = {
    "Not started": ("#5F6368", "#F1F3F4"),
    "Working on":  ("#1565C0", "#E3F2FD"),
    "Blocked":     ("#E65100", "#FFF3E0"),
    "Completed":   ("#2E7D32", "#E8F5E9"),
    "Cancelled":   ("#B71C1C", "#FFEBEE"),
}
_INACTIVE = ("Completed", "Cancelled")

# Urgency tiers → (row background, left accent border)
_URGENCY_STYLE = {
    "overdue":  ("#FDECEC", "#C62828"),
    "due_soon": ("#FFF8E9", "#E65100"),
    "normal":   ("transparent", "transparent"),
    "done":     ("transparent", "#2E7D32"),
}

_PROJECT_PALETTE = [
    "#1565C0", "#2E7D32", "#E65100", "#6A1B9A",
    "#00695C", "#AD1457", "#0277BD", "#4527A0",
]


def _proj_colour(label: str) -> str:
    return _PROJECT_PALETTE[abs(hash(label or "?")) % len(_PROJECT_PALETTE)]


def _parse_date(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _fetch_deliverables_overview():
    """Fetch projects + deliverables + users, applying RBAC on deliverables."""
    try:
        projects = (
            supabase.table("projects")
            .select("*")
            .eq("is_archived", False)
            .order("name")
            .execute()
            .data
            or []
        )

        role = st.session_state.get("user_role")
        email = st.session_state.get("user_email")

        dq = (
            supabase.table("deliverables")
            .select("*")
            .eq("is_archived", False)
            .order("deadline")
        )
        if role != "admin" and email:
            dq = dq.or_(f"owner_email.eq.{email},supervisor_email.eq.{email}")
        deliverables = dq.execute().data or []

        users = (
            supabase.table("users")
            .select("email, name, avatar_color")
            .eq("is_approved", True)
            .order("name")
            .execute()
            .data
            or []
        )
        user_map = {u["email"]: u for u in users}
        return projects, deliverables, user_map
    except Exception as e:
        st.error(f"Error loading deliverables: {e}")
        return [], [], {}


def _owner_sup_html(d: dict, user_map: dict) -> str:
    owner_e = d.get("owner_email")
    sup_e = d.get("supervisor_email")
    pills = ""
    if owner_e:
        u = user_map.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
        pills += person_pill_html(
            u.get("name", owner_e),
            u.get("avatar_color", "#534AB7"),
            role="owner",
            compact=True,
        )
    if sup_e and sup_e != owner_e:
        u = user_map.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
        pills += person_pill_html(
            u.get("name", sup_e),
            u.get("avatar_color", "#BA7517"),
            role="sup",
            compact=True,
        )
    return pills or "<span style='color:#aaa'>—</span>"


def _urgency(d: dict, threshold: int, today: datetime.date) -> tuple[str, int | None]:
    """Return (tier, days_to_deadline). Completed/cancelled never raise alarms."""
    dl = _parse_date(d.get("deadline"))
    if (d.get("status") or "Not started") in _INACTIVE:
        return "done", (dl - today).days if dl else None
    if not dl:
        return "normal", None
    days = (dl - today).days
    if days < 0:
        return "overdue", days
    if days <= threshold:
        return "due_soon", days
    return "normal", days


def _deadline_cell(d: dict, tier: str, days: int | None) -> str:
    dl = d.get("deadline")
    if not dl:
        return "<span style='color:#aaa;font-size:12px'>no deadline</span>"
    date_txt = fmt_date(dl)
    if tier == "overdue":
        return (
            f"<span style='font-weight:700;color:#C62828;font-size:13px'>{date_txt}</span>"
            f"<div style='font-size:11px;color:#C62828'>overdue {abs(days)}d</div>"
        )
    if tier == "due_soon":
        label = "today" if days == 0 else f"in {days}d"
        return (
            f"<span style='font-weight:700;color:#B26A00;font-size:13px'>{date_txt}</span>"
            f"<div style='font-size:11px;color:#B26A00'>{label}</div>"
        )
    return f"<span style='color:#444;font-size:13px'>{date_txt}</span>"


def _status_chip(status: str) -> str:
    fg, bg = _STATUS_COLOURS.get(status, ("#5F6368", "#F1F3F4"))
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 8px;border-radius:4px;"
        f"font-size:11px;font-weight:600;white-space:nowrap'>{html.escape(status)}</span>"
    )


def _project_chip(label: str) -> str:
    c = _proj_colour(label)
    return (
        f"<span style='background:{c};color:#fff;padding:1px 7px;border-radius:4px;"
        f"font-size:10px;font-weight:700;white-space:nowrap'>{html.escape(label)}</span>"
    )


def _build_table(rows: list[dict], settings: dict, user_map: dict,
                 threshold: int, today: datetime.date) -> str:
    head = (
        "<thead><tr>"
        "<th style='width:34%'>Deliverable</th>"
        "<th style='width:10%'>Project</th>"
        "<th style='width:10%'>Type</th>"
        "<th style='width:12%'>Status</th>"
        "<th style='width:12%'>Deadline</th>"
        "<th style='width:22%'>Owner / Supervisor</th>"
        "</tr></thead>"
    )

    body = []
    for d in rows:
        tier = d["_tier"]
        days = d["_days"]
        bg, accent = _URGENCY_STYLE[tier]
        status = d.get("status") or "Not started"
        name = html.escape(d.get("name") or "—")
        muted = "opacity:0.6;" if tier == "done" else ""

        body.append(
            f"<tr style='background:{bg};{muted}'>"
            f"<td style='border-left:3px solid {accent}'>"
            f"<span style='{_DELIV_NAME_STYLE}'>{name}</span></td>"
            f"<td>{_project_chip(d['_proj_label'])}</td>"
            f"<td>{deliverable_chip_html(d.get('type') or 'generic', settings)}</td>"
            f"<td>{_status_chip(status)}</td>"
            f"<td>{_deadline_cell(d, tier, days)}</td>"
            f"<td>{_owner_sup_html(d, user_map)}</td>"
            f"</tr>"
        )

    return f"<table class='maic-deliv-table'>{head}<tbody>{''.join(body)}</tbody></table>"


# Injected once via st.markdown (the proven pattern for CSS in this app).
_TABLE_CSS = """
<style>
.maic-deliv-table {width:100%;border-collapse:collapse;font-size:13px;}
.maic-deliv-table th {
    position:sticky; top:0; z-index:2; background:#F1F3F5;
    text-align:left; padding:8px 10px; font-size:11px; font-weight:700;
    letter-spacing:0.06em; text-transform:uppercase; color:#5F6368;
    border-bottom:2px solid #DDE1E5;
}
.maic-deliv-table td {padding:8px 10px;border-bottom:1px solid #ECEFF1;vertical-align:middle;}
.maic-deliv-table tr:hover td {background:rgba(0,0,0,0.02);}
</style>
"""


def show_deliverables():
    st.title("Deliverables Overview")
    settings = get_settings()
    try:
        threshold = int(settings.get("expiring_threshold_days", 14))
    except (TypeError, ValueError):
        threshold = 14
    today = datetime.date.today()

    projects, deliverables, user_map = _fetch_deliverables_overview()
    if not projects or not deliverables:
        st.info("No active deliverables found.")
        return

    proj_by_id = {p["id"]: p for p in projects}

    # Annotate each deliverable with project label and urgency.
    for d in deliverables:
        p = proj_by_id.get(d.get("project_id"), {})
        d["_proj_label"] = p.get("acronym") or p.get("identifier") or p.get("name") or "—"
        d["_proj_name"] = p.get("name") or "—"
        tier, days = _urgency(d, threshold, today)
        d["_tier"], d["_days"] = tier, days

    n_overdue = sum(1 for d in deliverables if d["_tier"] == "overdue")
    n_soon = sum(1 for d in deliverables if d["_tier"] == "due_soon")

    m1, m2, m3 = st.columns(3)
    m1.metric("Deliverables", len(deliverables))
    m2.metric("Overdue", n_overdue, delta=None)
    m3.metric(f"Due within {threshold}d", n_soon)

    # ── Filters ───────────────────────────────────────────────────────────────
    f1, f2, f3 = st.columns([2, 2, 2])
    with f1:
        proj_opts = {"All projects": None}
        proj_opts.update({
            f"{p.get('acronym') or p.get('name')} — {p.get('name')}": p["id"]
            for p in projects
            if any(d.get("project_id") == p["id"] for d in deliverables)
        })
        sel_proj = proj_opts[st.selectbox("Project", list(proj_opts.keys()), key="dv_proj")]
    with f2:
        status_opts = ["All", "Active only", "Not started", "Working on", "Blocked", "Completed"]
        sel_status = st.selectbox("Status", status_opts, key="dv_status")
    with f3:
        only_urgent = st.checkbox(
            "Only overdue / due soon", value=False, key="dv_urgent",
            help=f"Deadline passed, or within {threshold} days.",
        )

    rows = list(deliverables)
    if sel_proj is not None:
        rows = [d for d in rows if d.get("project_id") == sel_proj]
    if sel_status == "Active only":
        rows = [d for d in rows if (d.get("status") or "Not started") not in _INACTIVE]
    elif sel_status != "All":
        rows = [d for d in rows if (d.get("status") or "Not started") == sel_status]
    if only_urgent:
        rows = [d for d in rows if d["_tier"] in ("overdue", "due_soon")]

    # Sort: overdue first, then by deadline; undated last; completed sink to the bottom.
    tier_rank = {"overdue": 0, "due_soon": 1, "normal": 2, "done": 3}
    rows.sort(key=lambda d: (
        tier_rank[d["_tier"]],
        d.get("deadline") or "9999-12-31",
        (d.get("name") or "").lower(),
    ))

    if not rows:
        st.info("No deliverables match the current filters.")
        return

    st.caption(
        f"{len(rows)} deliverable(s), most urgent first. "
        "Red = overdue · amber = due soon."
    )

    st.markdown(_TABLE_CSS, unsafe_allow_html=True)
    st.html(_build_table(rows, settings, user_map, threshold, today))

    # ── PDF export of exactly what is on screen ──────────────────────────────
    st.write("")
    if st.button("📄 Generate PDF", type="primary", key="deliv_pdf_btn"):
        visible_projects = [p for p in projects if any(d.get("project_id") == p["id"] for d in rows)]
        buf = generate_deliverables_pdf(visible_projects, rows, user_map)
        st.download_button(
            "⬇️ Download PDF",
            data=buf,
            file_name=f"deliverables_overview_{today.strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            key="deliv_pdf_dl",
        )
