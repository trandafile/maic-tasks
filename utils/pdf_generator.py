import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)

# ─── Colour maps (text colours only – avoids filled-cell compatibility issues) ──
STATUS_TEXT = {
    "Not started": colors.HexColor("#888888"),
    "Working on":  colors.HexColor("#1565C0"),
    "Blocked":     colors.HexColor("#E65100"),
    "Completed":   colors.HexColor("#2E7D32"),
    "Cancelled":   colors.HexColor("#B71C1C"),
}
PRIORITY_TEXT = {
    "none":   colors.HexColor("#888888"),
    "low":    colors.HexColor("#1565C0"),
    "medium": colors.HexColor("#E65100"),
    "high":   colors.HexColor("#B71C1C"),
    "urgent": colors.HexColor("#6A1B9A"),
}

def _initials(name: str) -> str:
    parts = (name or "?").split()
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()

def _fmt_date(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        return d or "—"


def generate_deliverables_pdf(
    projects: list[dict],
    deliverables: list[dict],
    users_by_email: dict[str, dict],
) -> "BytesIO":
    """Generate a high-level Deliverables overview PDF grouped by project.

    Args:
        projects:       full list of (active) projects
        deliverables:   RBAC-filtered list of deliverables
        users_by_email: {email: user_row} for owner/supervisor names
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("DH1", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
    h2 = ParagraphStyle("DH2", parent=styles["Heading2"], fontSize=11, spaceAfter=2)
    small = ParagraphStyle("DS", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    label = ParagraphStyle(
        "DL",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.grey,
        fontName="Helvetica-BoldOblique",
        spaceAfter=3,
    )

    elements: list = []
    today_str = datetime.date.today().strftime("%d/%m/%Y")

    elements.append(Paragraph("Deliverables Overview — MAIC LAB", h1))
    elements.append(Paragraph(f"Generated on {today_str}", small))
    elements.append(Spacer(1, 8))

    proj_by_id = {p["id"]: p for p in projects}

    # Group deliverables by project id
    by_proj: dict[int, list[dict]] = {}
    for d in deliverables:
        pid = d.get("project_id")
        if not pid:
            continue
        by_proj.setdefault(pid, []).append(d)

    TABLE_HEADER = ["Deliverable", "Type", "Status", "Deadline", "Owner", "Supervisor"]
    COL_WIDTHS = [56 * mm, 24 * mm, 22 * mm, 22 * mm, 30 * mm, 30 * mm]

    for idx, (pid, dels) in enumerate(sorted(by_proj.items(), key=lambda x: proj_by_id.get(x[0], {}).get("name", ""))):
        proj = proj_by_id.get(pid, {})
        if idx > 0:
            elements.append(PageBreak())

        pname = proj.get("name", "Project")
        acr = proj.get("acronym") or proj.get("identifier") or ""
        elements.append(Paragraph(f"{pname} ({acr})", h2))

        caption_parts = []
        if proj.get("funding_agency"):
            caption_parts.append(proj["funding_agency"])
        if proj.get("start_date"):
            caption_parts.append(
                f"{_fmt_date(proj.get('start_date'))} → {_fmt_date(proj.get('end_date'))}"
            )
        if caption_parts:
            elements.append(Paragraph("  ·  ".join(caption_parts), small))
        elements.append(Spacer(1, 4))

        elements.append(Paragraph("DELIVERABLES", label))

        table_data = [TABLE_HEADER]
        for d in sorted(dels, key=lambda dd: dd.get("deadline") or "9999-12-31"):
            status = d.get("status", "Not started")
            stat_col = STATUS_TEXT.get(status, colors.grey)
            owner_e = d.get("owner_email")
            sup_e = d.get("supervisor_email")
            owner_name = users_by_email.get(owner_e, {}).get("name", owner_e or "—")
            sup_name = users_by_email.get(sup_e, {}).get("name", sup_e or "—") if sup_e else "—"

            row = [
                Paragraph(d.get("name") or "—", styles["Normal"]),
            ]
            row.append(Paragraph(d.get("type") or "—", small))
            row.append(
                Paragraph(
                    f"<font color='{stat_col.hexval()}'>{status}</font>",
                    small,
                )
            )
            row.append(Paragraph(_fmt_date(d.get("deadline")), small))
            row.append(Paragraph(owner_name or "—", small))
            row.append(Paragraph(sup_name or "—", small))
            table_data.append(row)

        tbl = Table(table_data, colWidths=COL_WIDTHS, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(tbl)
        elements.append(Spacer(1, 6))

    doc.build(elements)
    buf.seek(0)
    return buf


def generate_projects_pdf(
    projects: list[dict],
    deliverables: list[dict],
    tasks: list[dict],
    subtasks: list[dict],
    users: list[dict],
) -> "BytesIO":
    """The Projects view as a PDF — the same document as the Project Report:
    project tab, deliverable cards in their type colour, readable codes, rows
    tinted by deadline. The lists arrive already filtered as on screen."""
    users_dict = {u["email"]: (u.get("name") or u["email"]) for u in users if u.get("email")}
    return generate_report_pdf(projects, deliverables, tasks, subtasks, users_dict)


def generate_report_pdf(
    projects, deliverables, tasks, subtasks, users_dict,
    filter_proj=None, filter_user=None, filter_status=None,
    rbac_email=None,
):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )
    styles = getSampleStyleSheet()
    
    h1 = ParagraphStyle("PH1", parent=styles["Heading1"], fontSize=16, spaceAfter=2)
    h2 = ParagraphStyle("PH2", parent=styles["Heading2"], fontSize=11, spaceAfter=2)
    caption = ParagraphStyle("Cap", parent=styles["Normal"], fontSize=8, textColor=colors.grey, spaceAfter=6)
    normal  = ParagraphStyle("Norm", parent=styles["Normal"], fontSize=9)
    small   = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    italic  = ParagraphStyle("Italic", parent=styles["Normal"], fontSize=8, textColor=colors.grey, fontName="Helvetica-Oblique")
    label   = ParagraphStyle("Label", parent=styles["Normal"], fontSize=7, textColor=colors.grey, fontName="Helvetica-BoldOblique", spaceAfter=3)

    elements = []
    
    def _assignee_match(item: dict, email: str | None) -> bool:
        if not email:
            return True
        return item.get("owner_email") == email or item.get("supervisor_email") == email

    def _status_match(status_value: str | None) -> bool:
        if not filter_status:
            return True
        status = status_value or "Not started"
        if filter_status == "Active":
            return status not in ("Completed", "Cancelled")
        if filter_status == "Completed":
            return status == "Completed"
        if filter_status == "Blocked":
            return status == "Blocked"
        return True

    # Helper to filter tasks (includes RBAC)
    def task_matches(t):
        if t.get("is_archived"):
            return False
        if filter_proj and t.get("project_id") != filter_proj:
            return False
        if not _assignee_match(t, rbac_email):
            return False
        if not _assignee_match(t, filter_user):
            return False
        if not _status_match(t.get("status")):
            return False
        return True

    visible_task_ids = {t.get("id") for t in tasks if t.get("id") is not None and task_matches(t)}

    visible_deliv_ids = {
        d.get("id")
        for d in deliverables
        if d.get("id") is not None
        and not d.get("is_archived")
        and (not filter_proj or d.get("project_id") == filter_proj)
        and _assignee_match(d, rbac_email)
        and _assignee_match(d, filter_user)
        and (_status_match(d.get("status")) or any(
            t.get("deliverable_id") == d.get("id") and t.get("id") in visible_task_ids
            for t in tasks
        ))
    }

    if filter_user:
        visible_proj_ids = {
            t.get("project_id")
            for t in tasks
            if t.get("id") in visible_task_ids and t.get("project_id") is not None
        }
    else:
        visible_proj_ids = {
            t.get("project_id")
            for t in tasks
            if t.get("id") in visible_task_ids and t.get("project_id") is not None
        }.union({
            d.get("project_id")
            for d in deliverables
            if d.get("id") in visible_deliv_ids and d.get("project_id") is not None
        })

    proj_list = [
        p for p in projects
        if (filter_proj is None or p["id"] == filter_proj)
        and p.get("id") in visible_proj_ids
    ]

    # ── Same look as the Project Report page (utils/rows.py) ───────────────────
    # project tab on a rule · one card per deliverable edged and tinted with its
    # type colour · readable codes · rows tinted by deadline · subtasks set
    # solid under their task, a hairline above each task.
    from utils.rows import urgency as _urgency, tint as _tint, type_colours as _type_colours
    try:
        from db import get_settings as _get_settings
        _settings = _get_settings() or {}
    except Exception:
        _settings = {}
    try:
        threshold = int(_settings.get("expiring_threshold_days", 7))
    except (TypeError, ValueError):
        threshold = 7
    type_colour = _type_colours(_settings)

    W = 170 * mm
    COLS = [15 * mm, 59 * mm, 22 * mm, 30 * mm, 44 * mm]      # code · task · status · deadline · people
    INK, MUTED, SOFT = "#1F2328", "#80868B", "#5F6368"
    ST_COL = {"Not started": "#5F6368", "Working on": "#1558B0", "Blocked": "#B3261E",
              "Completed": "#1E7E34", "Cancelled": "#80868B"}
    code_st = ParagraphStyle("Code", parent=styles["Normal"], fontName="Courier", fontSize=7.5,
                             textColor=colors.HexColor(SOFT), leading=9)
    cell_st = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10)
    task_st = ParagraphStyle("Task", parent=styles["Normal"], fontSize=8.8, leading=11,
                             fontName="Helvetica-Bold", textColor=colors.HexColor(INK))
    sub_st = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=8.2, leading=10,
                            textColor=colors.HexColor("#3C4043"), leftIndent=10)
    band_st = ParagraphStyle("Band", parent=styles["Normal"], fontSize=10, leading=12.5)
    tab_st = ParagraphStyle("Tab", parent=styles["Normal"], fontSize=11.5, leading=14)
    head_st = ParagraphStyle("Head", parent=styles["Normal"], fontSize=7, leading=9,
                             textColor=colors.HexColor(MUTED))

    def _esc(v):
        return (str(v or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _code_of(item):
        seq = str(item.get("sequence_id") or "")
        import re as _re
        return seq if _re.match(r"^[A-Z](\.\d+)+$", seq) else ""

    def _people(item):
        owner = users_dict.get(item.get("owner_email"), item.get("owner_email") or "—")
        sup_e = item.get("supervisor_email")
        sup = users_dict.get(sup_e, sup_e) if sup_e and sup_e != item.get("owner_email") else ""
        return (f"<font size='7.4'>{_esc(owner)}</font>"
                + (f"<font color='{MUTED}' size='6.6'> · sup {_esc(sup)}</font>" if sup else ""))

    def _deadline(item):
        tier, days = _urgency(item, threshold)
        dl = _fmt_date(item.get("deadline")) if item.get("deadline") else "—"
        if tier == "overdue":
            return f"<font color='#B3261E'><b>{dl}</b> · {abs(days)}d late</font>", tier
        if tier == "soon":
            when = "today" if days == 0 else f"in {days}d"
            return f"<font color='#A15C00'><b>{dl}</b> · {when}</font>", tier
        return f"<font color='{MUTED if tier == 'done' else SOFT}'>{dl}</font>", tier

    def _item_row(item, kind):
        status = item.get("status") or "Not started"
        dl_html, tier = _deadline(item)
        name = _esc(item.get("name", ""))
        if tier == "done":
            name = f"<strike><font color='{MUTED}'>{name}</font></strike>"
        prio = (item.get("priority") or "").lower()
        if kind == "task" and prio in ("medium", "high", "urgent") and tier != "done":
            pc = {"medium": "#A15C00", "high": "#B3261E", "urgent": "#7B1FA2"}[prio]
            name += f"  <font color='{pc}' size='6.5'>{prio}</font>"
        text = (f"› {name}" if kind == "subtask" else name)
        return [
            Paragraph(_esc(_code_of(item)), code_st),
            Paragraph(text, sub_st if kind == "subtask" else task_st),
            Paragraph(f"<font color='{ST_COL.get(status, SOFT)}'><b>{_esc(status)}</b></font>",
                      cell_st),
            Paragraph(dl_html, cell_st),
            Paragraph(_people(item), cell_st),
        ], tier, kind

    def _card(band_html, colour, entries):
        """A deliverable card as one table: band row + item rows."""
        data = [[Paragraph(band_html, band_st), "", "", "", ""]]
        meta = []
        for cells, tier, kind in entries:
            data.append(cells)
            meta.append((tier, kind))
        tbl = Table(data, colWidths=COLS)
        style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_tint(colour))),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E3E6EA")),
            ("LINEBEFORE", (0, 0), (0, -1), 3.2, colors.HexColor(colour)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("TOPPADDING", (0, 1), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 1), (-1, -1), 1.6),
        ]
        for i, (tier, kind) in enumerate(meta, start=1):
            if kind == "task":
                style += [("LINEABOVE", (0, i), (-1, i), 0.4, colors.HexColor("#E6E8EB")),
                          ("TOPPADDING", (0, i), (-1, i), 3.2)]
            if tier == "overdue":
                style.append(("BACKGROUND", (1, i), (-1, i), colors.HexColor("#FFF6F6")))
            elif tier == "soon":
                style.append(("BACKGROUND", (1, i), (-1, i), colors.HexColor("#FFFCF7")))
        tbl.setStyle(TableStyle(style))
        return tbl

    def _entries(task_list):
        out = []
        for t in task_list:
            out.append(_item_row(t, "task"))
            for s in subtasks:
                if s.get("task_id") != t.get("id") or s.get("is_archived"):
                    continue
                if not _status_match(s.get("status")):
                    continue
                out.append(_item_row(s, "subtask"))
        return out

    def _sort(ts):
        from utils.rows import urgency_sort as _us
        return _us(ts, threshold)

    header = Table([[Paragraph("CODE", head_st), Paragraph("TASK", head_st),
                     Paragraph("STATUS", head_st), Paragraph("DEADLINE", head_st),
                     Paragraph("OWNER / SUPERVISOR", head_st)]], colWidths=COLS)
    header.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 5),
                                ("TOPPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))

    for proj_idx, proj in enumerate(proj_list):
        if proj_idx > 0:
            elements.append(PageBreak())
        pid = proj["id"]
        letter = proj.get("code_letter") or ""

        # ── project tab sitting on a rule ──────────────────────────────────────
        badge = (f"<font face='Courier-Bold' color='#4527A0' size='12'>{_esc(letter)}</font>  "
                 if letter else "")
        acr = proj.get("acronym") or ""
        title = (f"<b>{_esc(acr)}</b> · {_esc(proj.get('name'))}" if acr and acr != proj.get("name")
                 else f"<b>{_esc(proj.get('name'))}</b>")
        tab = Table([[Paragraph(badge + title, tab_st)]])
        tab.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFBFC")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C9CED4")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.7, colors.HexColor("#FAFBFC")),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        tab.hAlign = "LEFT"
        elements.append(tab)
        elements.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#C9CED4"),
                                   spaceBefore=0, spaceAfter=3))
        capt_parts = []
        if proj.get("funding_agency"):
            capt_parts.append(f"Funding: {proj['funding_agency']}")
        if proj.get("start_date"):
            capt_parts.append(f"{_fmt_date(proj.get('start_date'))} – {_fmt_date(proj.get('end_date'))}")
        if capt_parts:
            elements.append(Paragraph(_esc("  ·  ".join(capt_parts)), caption))
        elements.append(header)

        proj_deliverables = sorted([d for d in deliverables
                                    if d.get("project_id") == pid and d.get("id") in visible_deliv_ids],
                                   key=lambda d: (d.get("code_no") is None, d.get("code_no") or 0, d.get("name") or ""))
        for d in proj_deliverables:
            d_tasks = _sort([t for t in tasks if t.get("deliverable_id") == d["id"]
                             and t.get("id") in visible_task_ids])
            colour = type_colour.get((d.get("type") or "").strip(), "#5F6368")
            counted = [t for t in d_tasks if (t.get("status") or "") != "Cancelled"]
            done = len([t for t in counted if t.get("status") == "Completed"])
            dcode = (f"{letter}.{int(d['code_no'])}" if letter and d.get("code_no") is not None
                     else "")
            status = d.get("status") or "Not started"
            dl_html, _ = _deadline(d)
            owner = users_dict.get(d.get("owner_email"), d.get("owner_email") or "—")
            sup_e = d.get("supervisor_email")
            sup = users_dict.get(sup_e, sup_e) if sup_e and sup_e != d.get("owner_email") else ""
            band = (
                (f"<font face='Courier-Bold' color='{colour}'>{_esc(dcode)}</font>  " if dcode else "")
                + f"<b><font color='{colour}'>{_esc(d.get('name', ''))}</font></b>  "
                f"<font size='8' color='{ST_COL.get(status, SOFT)}'>{_esc(status)}</font>  "
                f"<font size='8' color='{SOFT}'>{done}/{len(counted)} tasks</font>  "
                f"<font size='8'>{dl_html}</font>  "
                f"<font size='7.5' color='{SOFT}'>{_esc(owner)}"
                + (f" · sup {_esc(sup)}" if sup else "") + "</font>  "
                f"<font size='7.5' color='{colour}'><b>{_esc(d.get('type') or '')}</b></font>"
            )
            entries = _entries(d_tasks)
            if not entries:
                entries = [([Paragraph("", code_st),
                             Paragraph(f"<i><font color='{MUTED}'>No tasks matching the "
                                       f"filters.</font></i>", cell_st), "", "", ""], "normal", "note")]
            elements.append(Spacer(1, 6))
            elements.append(_card(band, colour, entries))

        unassigned = _sort([t for t in tasks if t.get("project_id") == pid
                            and not t.get("deliverable_id") and t.get("id") in visible_task_ids])
        if unassigned:
            lcode = f"{letter}.0" if letter else ""
            band = ((f"<font face='Courier-Bold' color='#5F6368'>{lcode}</font>  " if lcode else "")
                    + f"<b><font color='#3C4043'>Tasks without deliverable</font></b>  "
                    f"<font size='8' color='{SOFT}'>{len(unassigned)}</font>")
            elements.append(Spacer(1, 6))
            elements.append(_card(band, "#9AA0A6", _entries(unassigned)))

    doc.build(elements)
    buf.seek(0)
    return buf


# ─── Report: Carico per Persona ───────────────────────────────────────────────

def generate_workload_pdf(workload_data: list) -> "BytesIO":
    """PDF version of the 'Carico per Persona' report.

    Args:
        workload_data: list returned by db.get_workload_per_person()
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )
    styles = getSampleStyleSheet()
    h1     = ParagraphStyle("WH1", parent=styles["Heading1"], fontSize=14, spaceAfter=2)
    h2     = ParagraphStyle("WH2", parent=styles["Heading2"], fontSize=10, spaceAfter=2)
    normal = ParagraphStyle("WN",  parent=styles["Normal"],   fontSize=9)
    small  = ParagraphStyle("WS",  parent=styles["Normal"],   fontSize=8, textColor=colors.grey)
    label  = ParagraphStyle("WL",  parent=styles["Normal"],   fontSize=7,
                             textColor=colors.grey, fontName="Helvetica-BoldOblique", spaceAfter=3)
    italic = ParagraphStyle("WI",  parent=styles["Normal"],   fontSize=8,
                             textColor=colors.grey, fontName="Helvetica-Oblique")

    import datetime as _dt
    elements = []

    elements.append(Paragraph("Carico per Persona — MAIC LAB", h1))
    elements.append(Paragraph(
        f"Generato il {_dt.date.today().strftime('%d/%m/%Y')}", small
    ))
    elements.append(Spacer(1, 8))

    for person in workload_data:
        user        = person["user"]
        name        = user.get("name", "?")
        role        = user.get("role", "user")
        notes       = user.get("notes") or ""
        sub_label   = f"{role} · {notes}" if notes else role

        tasks_active  = person["tasks_active"]
        tasks_overdue = person["tasks_overdue"]
        proj_count    = person["projects_count"]
        est_hours     = person["estimate_hours"]
        hours_str     = f"{int(est_hours)}h" if est_hours else "—"

        all_tasks = person["all_user_tasks"]
        total     = len(all_tasks)

        def _pct(n, t):
            return round(100 * n / t) if t else 0

        pct_c = _pct(sum(1 for t in all_tasks if t.get("status") == "Completed"),  total)
        pct_w = _pct(sum(1 for t in all_tasks if t.get("status") == "Working on"), total)
        pct_b = _pct(sum(1 for t in all_tasks if t.get("status") == "Blocked"),    total)

        elements.append(HRFlowable(width="100%", thickness=1.0, lineCap="butt",
                                    color=colors.HexColor("#CCCCCC")))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(f"{_initials(name)}  {name}", h2))
        elements.append(Paragraph(sub_label, small))
        elements.append(Spacer(1, 4))

        # Stats line
        overdue_txt = f"{tasks_overdue} scaduti" if tasks_overdue > 0 else "0 scaduti"
        elements.append(Paragraph(
            f"Task attivi: <b>{tasks_active}</b>  ·  {overdue_txt}  ·  "
            f"Progetti: <b>{proj_count}</b>  ·  Ore stimate: <b>{hours_str}</b>",
            normal
        ))
        elements.append(Spacer(1, 3))
        elements.append(Paragraph(
            f"Completati: {pct_c}%  ·  In corso: {pct_w}%  ·  Bloccati: {pct_b}%",
            small
        ))
        elements.append(Spacer(1, 6))

        if person["projects"]:
            elements.append(Paragraph("PROGETTI", label))
            proj_table_data = [["Progetto", "Stato task", "Ruolo", "Ore"]]
            for proj in person["projects"]:
                sc        = proj["status_counts"]
                stato_txt = "  ".join(f"{cnt} {s}" for s, cnt in sorted(sc.items()))
                role_p    = proj["role"]
                est_proj  = sum(t.get("estimate_hours") or 0 for t in proj["tasks"])
                hrs_p     = f"{int(est_proj)}h" if est_proj > 0 else "—"
                proj_table_data.append([
                    Paragraph(proj["project_name"], normal),
                    Paragraph(stato_txt or "—", small),
                    Paragraph(role_p, small),
                    Paragraph(hrs_p, small),
                ])
            tbl = Table(proj_table_data, colWidths=[65*mm, 60*mm, 22*mm, 16*mm], repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(tbl)

        elements.append(Spacer(1, 10))

    doc.build(elements)
    buf.seek(0)
    return buf


# ─── Report: Organico per Progetto ───────────────────────────────────────────

def generate_staff_pdf(staff_data: list) -> "BytesIO":
    """PDF version of the 'Organico per Progetto' report.

    Args:
        staff_data: list returned by db.get_staff_per_project()
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )
    styles = getSampleStyleSheet()
    h1     = ParagraphStyle("SH1", parent=styles["Heading1"], fontSize=14, spaceAfter=2)
    h2     = ParagraphStyle("SH2", parent=styles["Heading2"], fontSize=11, spaceAfter=2)
    normal = ParagraphStyle("SN",  parent=styles["Normal"],   fontSize=9)
    small  = ParagraphStyle("SS",  parent=styles["Normal"],   fontSize=8, textColor=colors.grey)
    caption= ParagraphStyle("SC",  parent=styles["Normal"],   fontSize=8, textColor=colors.grey)
    label  = ParagraphStyle("SL",  parent=styles["Normal"],   fontSize=7,
                             textColor=colors.grey, fontName="Helvetica-BoldOblique", spaceAfter=3)

    import datetime as _dt
    elements = []

    elements.append(Paragraph("Organico per Progetto — MAIC LAB", h1))
    elements.append(Paragraph(
        f"Generato il {_dt.date.today().strftime('%d/%m/%Y')}", small
    ))

    for idx, proj_data in enumerate(staff_data):
        if idx > 0:
            elements.append(PageBreak())

        proj       = proj_data["project"]
        people     = proj_data["people"]
        task_count = proj_data["tasks_active_count"]

        acronym = proj.get("acronym", "") or proj.get("identifier", "")
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(f"{proj.get('name')} ({acronym})", h2))

        capt_parts = []
        if proj.get("funding_agency"):
            capt_parts.append(proj["funding_agency"])
        if proj.get("start_date"):
            capt_parts.append(
                f"{_fmt_date(proj.get('start_date'))} → {_fmt_date(proj.get('end_date'))}"
            )
        capt_parts.append(f"{len(people)} ricercatori coinvolti")
        elements.append(Paragraph("  ·  ".join(capt_parts), caption))
        elements.append(Paragraph(f"Task attivi totali: {task_count}", small))
        elements.append(Spacer(1, 6))

        if people:
            elements.append(Paragraph("RICERCATORI COINVOLTI", label))
            table_data = [["Ricercatore", "Task", "Distribuzione stati", "Ruolo", "Ore"]]
            for p in people:
                name     = p["user"].get("name", "?")
                sc       = p["status_counts"]
                stato    = "  ".join(f"{cnt} {s}" for s, cnt in sorted(sc.items()))
                role     = p["role_prevalent"]
                est      = p["estimate_hours"]
                hrs_str  = f"{int(est)}h" if est else "—"
                table_data.append([
                    Paragraph(f"{_initials(name)}  {name}", normal),
                    Paragraph(str(p["tasks_active"]), small),
                    Paragraph(stato or "—", small),
                    Paragraph(role, small),
                    Paragraph(hrs_str, small),
                ])

            tbl = Table(
                table_data,
                colWidths=[52*mm, 16*mm, 58*mm, 22*mm, 16*mm],
                repeatRows=1,
            )
            tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(tbl)

    doc.build(elements)
    buf.seek(0)
    return buf


# ─── Report: Detailed (per progetto) ────────────────────────────────────────

def generate_detailed_report_pdf(
    project: dict,
    deliverables: list,
    tasks: list,
    subtasks_by_task: dict,
    comments_by_task: dict,
    users_dict: dict,
) -> "BytesIO":
    """PDF version of the detailed per-project report.

    Args:
        project:          full projects row
        deliverables:     list of deliverable rows for the project
        tasks:            list of task rows for the project
        subtasks_by_task: {task_id: [subtask, ...]}
        comments_by_task: {task_id: [comment, ...]}
        users_dict:       {email: user_row}
    """
    from utils.helpers import strip_markdown, fmt_date as _fmt_date2

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )
    styles = getSampleStyleSheet()
    h1     = ParagraphStyle("DH1", parent=styles["Heading1"], fontSize=16, spaceAfter=2)
    h2     = ParagraphStyle("DH2", parent=styles["Heading2"], fontSize=12, spaceAfter=2)
    h3     = ParagraphStyle("DH3", parent=styles["Heading3"], fontSize=10, spaceAfter=2)
    normal = ParagraphStyle("DN",  parent=styles["Normal"],   fontSize=9, spaceAfter=4)
    small  = ParagraphStyle("DS",  parent=styles["Normal"],   fontSize=8, textColor=colors.grey)
    label  = ParagraphStyle("DL",  parent=styles["Normal"],   fontSize=7,
                             textColor=colors.grey, fontName="Helvetica-BoldOblique", spaceAfter=3)
    italic = ParagraphStyle("DI",  parent=styles["Normal"],   fontSize=8,
                             textColor=colors.grey, fontName="Helvetica-Oblique")
    body   = ParagraphStyle("DB",  parent=styles["Normal"],   fontSize=9,
                             leftIndent=8, spaceAfter=4)

    import datetime as _dt

    today_str    = _dt.date.today().strftime("%d/%m/%Y")
    active_tasks = [t for t in tasks if t.get("status") not in ("Cancelled",)]
    today_iso    = _dt.date.today().isoformat()
    completed    = [t for t in active_tasks if t.get("status") == "Completed"]
    overdue      = [t for t in active_tasks if t.get("deadline") and t["deadline"] < today_iso and t.get("status") != "Completed"]
    total_hours  = sum(t.get("estimate_hours") or 0 for t in active_tasks)

    def _uname(email):
        if not email:
            return "—"
        u = users_dict.get(email)
        if u:
            return u.get("name", email)
        return email

    elements_d = []

    # ── Header ────────────────────────────────────────────────────────────────
    acronym = project.get("acronym", "") or project.get("identifier", "")
    elements_d.append(Paragraph(f"{project.get('name', '')} ({acronym})", h1))
    capt_parts = []
    if project.get("funding_agency"):
        capt_parts.append(project["funding_agency"])
    if project.get("start_date"):
        capt_parts.append(
            f"{_fmt_date2(project.get('start_date'))} → {_fmt_date2(project.get('end_date'))}"
        )
    capt_parts.append(f"Generated: {today_str}")
    elements_d.append(Paragraph("  ·  ".join(capt_parts), small))
    elements_d.append(Spacer(1, 6))

    # ── Summary table ─────────────────────────────────────────────────────────
    sum_data = [
        ["Total tasks", "Completed", "Overdue", "Est. hours"],
        [
            str(len(active_tasks)),
            str(len(completed)),
            str(len(overdue)),
            f"{int(total_hours)}h" if total_hours else "—",
        ],
    ]
    sum_tbl = Table(sum_data, colWidths=[40*mm, 40*mm, 40*mm, 40*mm], hAlign="LEFT")
    sum_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements_d.append(sum_tbl)
    elements_d.append(Spacer(1, 10))

    # ── Per-deliverable sections ───────────────────────────────────────────────
    sorted_delivs = sorted(deliverables, key=lambda d: d.get("deadline") or "9999-12-31")

    def _render_task_pdf(t: dict):
        seq    = t.get("sequence_id") or f"T-{t['id']}"
        status = t.get("status", "Not started")
        prio   = (t.get("priority") or "none").capitalize()
        dl     = _fmt_date2(t.get("deadline"))
        est    = f"{int(t['estimate_hours'])}h" if t.get("estimate_hours") else "—"
        owner  = _uname(t.get("owner_email"))
        sup    = _uname(t.get("supervisor_email")) if t.get("supervisor_email") else None

        stat_col = STATUS_TEXT.get(status, colors.grey)
        elements_d.append(Spacer(1, 4))
        elements_d.append(Paragraph(f"{seq} — {t.get('name', '')}", h3))

        meta = f"Owner: {owner}"
        if sup and sup != owner:
            meta += f"  ·  Supervisor: {sup}"
        meta += f"  ·  Status: <font color='{stat_col.hexval()}'>{status}</font>"
        meta += f"  ·  Priority: {prio}  ·  Deadline: {dl}  ·  Est: {est}"
        if t.get("completion_date"):
            meta += f"  ·  Completed: {_fmt_date2(t['completion_date'])}"
        elements_d.append(Paragraph(meta, small))

        if t.get("notes"):
            notes_plain = strip_markdown(t["notes"])
            if notes_plain:
                elements_d.append(Paragraph(notes_plain, body))

        t_subs = subtasks_by_task.get(t["id"], [])
        if t_subs:
            elements_d.append(Paragraph("SUBTASKS", label))
            for s in t_subs:
                s_status = s.get("status", "Not started")
                s_seq    = s.get("sequence_id") or f"S-{s['id']}"
                s_owner  = _uname(s.get("owner_email"))
                chk      = "✓" if s_status == "Completed" else "○"
                s_stat_col = STATUS_TEXT.get(s_status, colors.grey)
                sub_line = (
                    f"{chk}  {s_seq} — {s.get('name', '')}  "
                    f"<font color='{s_stat_col.hexval()}'>[{s_status}]</font>"
                    f"  Owner: {s_owner}"
                )
                elements_d.append(Paragraph(sub_line, small))
                if s.get("notes"):
                    sn = strip_markdown(s["notes"])
                    if sn:
                        elements_d.append(Paragraph(sn, ParagraphStyle(
                            "SubN", parent=body, fontSize=8, leftIndent=20
                        )))

        t_comments = [c for c in comments_by_task.get(t["id"], []) if not c.get("is_system_event")]
        if t_comments:
            elements_d.append(Paragraph("ACTIVITY", label))
            for c in t_comments:
                author = "?"
                u_rel = c.get("users")
                if isinstance(u_rel, dict):
                    author = u_rel.get("name", "?")
                elif isinstance(u_rel, list) and u_rel:
                    author = u_rel[0].get("name", "?")
                ts = (c.get("created_at") or "")[:16].replace("T", " ")
                elements_d.append(Paragraph(f"{ts} · {author} — {c.get('body', '')}", italic))

        elements_d.append(HRFlowable(width="100%", thickness=0.3, lineCap="butt",
                                     color=colors.HexColor("#DDDDDD")))

    for d in sorted_delivs:
        did     = d["id"]
        d_tasks = [t for t in tasks if t.get("deliverable_id") == did and t.get("status") != "Cancelled"]
        total_d = len(d_tasks)
        done_d  = len([t for t in d_tasks if t.get("status") == "Completed"])

        elements_d.append(Paragraph(d.get("name", ""), h2))
        elements_d.append(Paragraph(
            f"{d.get('type', '')}  ·  Deadline: {_fmt_date2(d.get('deadline'))}  ·  "
            f"{done_d}/{total_d} tasks completed",
            small
        ))
        elements_d.append(Spacer(1, 4))

        for t in sorted(d_tasks, key=lambda t: t.get("sort_order") or 0):
            _render_task_pdf(t)

        elements_d.append(HRFlowable(width="100%", thickness=1.0, lineCap="butt",
                                     color=colors.HexColor("#CCCCCC")))
        elements_d.append(Spacer(1, 8))

    # ── Generic tasks ──────────────────────────────────────────────────────────
    no_deliv = [t for t in tasks if not t.get("deliverable_id") and t.get("status") != "Cancelled"]
    if no_deliv:
        elements_d.append(Paragraph("GENERIC TASKS (NO DELIVERABLE)", h2))
        for t in sorted(no_deliv, key=lambda t: t.get("sort_order") or 0):
            _render_task_pdf(t)

    doc.build(elements_d)
    buf.seek(0)
    return buf
