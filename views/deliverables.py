"""views/deliverables.py — Deliverables, grouped by project.

Each project is a group with its acronym on a vertical band; inside it one
compact line per deliverable: name and type, status, deadline, task progress
(with the active tasks on hover), owner and supervisor. Rows use the app-wide
row style (utils/rows.py), so lateness reads the same as in Projects and on the
Dashboard. The most pressing project comes first.
"""

import datetime

import streamlit as st

from core.supabase_client import supabase
from db import get_settings
from utils.helpers import deliverable_chip_html, stable_colour
from utils.modals import deliverable_details_modal
from utils.rows import (
    TEXT_MUTED, esc, chip, status_chip, deadline_cell, people_cell, progress_bar, urgency,
)
from utils.pdf_generator import generate_deliverables_pdf
from utils.codes import fmt as code_fmt


_INACTIVE = ("Completed", "Cancelled")

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


def _fetch_task_progress(deliverable_ids: list[int]) -> dict[int, dict]:
    """{deliverable_id: {total, done, active, active_names}} from live tasks.
    Cancelled tasks count as neither done nor to do."""
    out: dict[int, dict] = {}
    if not deliverable_ids:
        return out
    try:
        tasks = (
            supabase.table("tasks")
            .select("deliverable_id, name, status")
            .in_("deliverable_id", deliverable_ids)
            .eq("is_archived", False)
            .execute()
            .data
            or []
        )
    except Exception as e:
        print(f"[deliverables] task progress: {e}")
        return out
    for t in tasks:
        p = out.setdefault(t["deliverable_id"], {"total": 0, "done": 0, "active": 0,
                                                "active_names": []})
        s = t.get("status") or "Not started"
        if s == "Cancelled":
            continue
        p["total"] += 1
        if s == "Completed":
            p["done"] += 1
        else:
            p["active"] += 1
            p["active_names"].append(t.get("name") or "?")
    return out


# ── One deliverable, one line ─────────────────────────────────────────────────
# Same row system as Projects and the Dashboard (utils/rows.py): tinted light
# red when late and pale orange when due soon, single-line cells.

_GRID = "grid-template-columns:minmax(0,1fr) 92px 140px 180px 215px;"


def _progress_cell(p: dict | None) -> str:
    p = p or {"total": 0, "done": 0, "active": 0, "active_names": []}
    if not p["total"]:
        return f"<span style='font-size:11px;color:{TEXT_MUTED}'>no tasks yet</span>"
    tip = esc("Active: " + ", ".join(p["active_names"])) if p["active_names"] else "All done"
    active = (f"<span title='{tip}' style='font-size:11px;color:#1558B0;font-weight:600;"
              f"white-space:nowrap;cursor:help'>{p['active']} active</span>"
              if p["active"] else
              "<span style='font-size:11px;color:#1E7E34;font-weight:600'>all done</span>")
    return (f"<div style='display:flex;align-items:center;gap:8px;white-space:nowrap'>"
            f"{progress_bar(p['done'], p['total'], width=70)}{active}</div>")


def _row_html(d: dict, settings: dict, user_map: dict, progress: dict | None,
              threshold: int) -> str:
    tier, _ = urgency(d, threshold)
    classes = "maic-row maic-row-flat"
    if tier == "overdue":
        classes += " maic-row-overdue"
    elif tier == "soon":
        classes += " maic-row-soon"
    done = tier == "done"
    name_style = (f"font-size:13.5px;font-weight:700;color:{TEXT_MUTED if done else '#1F2328'};"
                  f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0")
    signoff = chip("⏳ sign-off", "#8A5300", "#FFF1D6") \
        if (d.get("completion_state") or "") == "pending" else ""
    code = d.get("_code") or ""
    code_html = (f"<span style='flex:0 0 auto;font-family:ui-monospace,Consolas,monospace;"
                 f"font-size:12.5px;font-weight:700;color:#3C4043'>{esc(code)}</span>") if code else ""
    name_cell = (
        f"<div style='display:flex;align-items:center;gap:7px;min-width:0;overflow:hidden'>"
        f"{code_html}"
        f"<span style='{name_style}' title='{esc(d.get('name', ''))}'>{esc(d.get('name') or '—')}</span>"
        f"{deliverable_chip_html(d.get('type') or 'generic', settings)}{signoff}</div>"
    )
    return (
        f"<div class='{classes}' style='display:grid;{_GRID}gap:10px;padding:4px 8px;"
        f"align-items:center;line-height:1.3'>"
        f"{name_cell}"
        f"<div>{status_chip(d.get('status') or 'Not started')}</div>"
        f"<div style='white-space:nowrap'>{deadline_cell(d, threshold)}</div>"
        f"<div>{_progress_cell(progress)}</div>"
        f"<div style='min-width:0'>{people_cell(d.get('owner_email'), d.get('supervisor_email'), user_map, muted=done)}</div>"
        f"</div>"
    )


def _header_html() -> str:
    cell = f"font-size:10.5px;color:{TEXT_MUTED};letter-spacing:0.03em"
    labels = ("Deliverable", "Status", "Deadline", "Tasks", "Owner / supervisor")
    return (f"<div class='maic-row-head' style='display:grid;{_GRID}gap:10px;"
            f"padding:0 8px;align-items:center'>"
            + "".join(f"<span style='{cell}'>{l}</span>" for l in labels) + "</div>")


# Project group: a vertical band with the acronym, as tall as the group.
# The band is absolutely positioned against the keyed container, so it
# stretches with however many deliverables the project has.
_GROUP_CSS = """
<style>
div[class*="st-key-dvproj_"], div[class*="st-key-dvhead"] {
    position: relative; padding-left: 40px; gap: 0 !important;
}
div[class*="st-key-dvproj_"] { margin-bottom: 14px; }
div[class*="st-key-dvproj_"] div[data-testid='stElementContainer']:has(.dv-band) {
    position: static !important; height: 0; margin: 0;
}
.dv-band {
    position: absolute; left: 0; top: 0; bottom: 0; width: 30px;
    border-radius: 6px; display: flex; align-items: center; justify-content: center;
}
.dv-band span {
    writing-mode: vertical-rl; transform: rotate(180deg); color: #FFFFFF;
    font-size: 12px; font-weight: 700; letter-spacing: 0.08em; white-space: nowrap;
}
</style>
"""


def show_deliverables():
    st.title("Deliverables")
    settings = get_settings()
    try:
        threshold = int(settings.get("expiring_threshold_days", 14))
    except (TypeError, ValueError):
        threshold = 14

    projects, deliverables, user_map = _fetch_deliverables_overview()
    if not projects or not deliverables:
        st.info("No active deliverables found.")
        return

    proj_by_id = {p["id"]: p for p in projects}
    for d in deliverables:
        p = proj_by_id.get(d.get("project_id"), {})
        d["_proj_label"] = p.get("acronym") or p.get("identifier") or p.get("name") or "—"
        d["_proj_name"] = p.get("name") or "—"
        d["_code"] = code_fmt(p.get("code_letter"), d.get("code_no"))
        d["_tier"], _ = urgency(d, threshold)

    n_overdue = sum(1 for d in deliverables if d["_tier"] == "overdue")
    n_soon = sum(1 for d in deliverables if d["_tier"] == "soon")
    m1, m2, m3 = st.columns(3)
    m1.metric("Deliverables", len(deliverables))
    m2.metric("Overdue", n_overdue)
    m3.metric(f"Due within {threshold}d", n_soon)

    # ── Filters ───────────────────────────────────────────────────────────────
    f1, f_type, f2, f3 = st.columns([2, 1.6, 2, 2], vertical_alignment="bottom")
    with f1:
        proj_opts = {"All projects": None}
        proj_opts.update({
            f"{p.get('acronym') or p.get('name')} — {p.get('name')}": p["id"]
            for p in projects
            if any(d.get("project_id") == p["id"] for d in deliverables)
        })
        sel_proj = proj_opts[st.selectbox("Project", list(proj_opts.keys()), key="dv_proj")]
    with f_type:
        types = sorted({(d.get("type") or "generic").strip() or "generic" for d in deliverables})
        sel_type = st.selectbox("Type", ["All types"] + types, key="dv_type")
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
    if sel_type != "All types":
        rows = [d for d in rows if ((d.get("type") or "generic").strip() or "generic") == sel_type]
    if sel_status == "Active only":
        rows = [d for d in rows if (d.get("status") or "Not started") not in _INACTIVE]
    elif sel_status != "All":
        rows = [d for d in rows if (d.get("status") or "Not started") == sel_status]
    if only_urgent:
        rows = [d for d in rows if d["_tier"] in ("overdue", "soon")]
    if not rows:
        st.info("No deliverables match the current filters.")
        return

    progress = _fetch_task_progress([d["id"] for d in rows])

    # ── Group by project: the most pressing project first ─────────────────────
    tier_rank = {"overdue": 0, "soon": 1, "normal": 2, "done": 3}
    groups: dict[int, list] = {}
    for d in rows:
        groups.setdefault(d.get("project_id"), []).append(d)

    def _row_key(d):
        return (tier_rank[d["_tier"]], d.get("deadline") or "9999-12-31",
                (d.get("name") or "").lower())

    for lst in groups.values():
        lst.sort(key=_row_key)
    ordered = sorted(groups.items(), key=lambda kv: (_row_key(kv[1][0]),
                                                    kv[1][0]["_proj_name"].lower()))

    st.caption(f"{len(rows)} deliverable(s) in {len(groups)} project(s) — the most "
               "pressing project first, then by urgency. Hover “active” to see the "
               "open tasks.")
    st.markdown(_GROUP_CSS, unsafe_allow_html=True)

    is_admin = st.session_state.get("user_role") == "admin"
    email = st.session_state.get("user_email")

    with st.container(key="dvhead"):
        hc, _ = st.columns([12, 0.7])
        with hc:
            st.html(_header_html())

    for pid, lst in ordered:
        label, pname = lst[0]["_proj_label"], lst[0]["_proj_name"]
        with st.container(key=f"dvproj_{pid}", gap=None):
            st.html(f"<div class='dv-band' style='background:{stable_colour(label)}'>"
                    f"<span>{esc(label)}</span></div>")
            st.html(f"<div style='font-size:12px;color:{TEXT_MUTED};padding:2px 8px 3px 8px'>"
                    f"{esc(pname)}</div>")
            for d in lst:
                c_row, c_btn = st.columns([12, 0.7], vertical_alignment="center")
                with c_row:
                    st.html(_row_html(d, settings, user_map, progress.get(d["id"]), threshold))
                with c_btn:
                    if st.button("✏️", key=f"dv_edit_{d['id']}", type="tertiary",
                                 help="Details, edit, sign-off and comments"):
                        can_edit = (
                            is_admin
                            or d.get("owner_email") == email
                            or d.get("supervisor_email") == email
                        )
                        deliverable_details_modal(
                            d, can_edit=can_edit,
                            breadcrumb=f"Deliverables / {d.get('_proj_name', '')}",
                        )

    # ── PDF export of exactly what is on screen ──────────────────────────────
    st.write("")
    if st.button("📄 Generate PDF", type="primary", key="deliv_pdf_btn"):
        visible_projects = [p for p in projects if p["id"] in groups]
        buf = generate_deliverables_pdf(visible_projects, rows, user_map)
        st.download_button(
            "⬇️ Download PDF",
            data=buf,
            file_name=f"deliverables_overview_{datetime.date.today().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            key="deliv_pdf_dl",
        )
