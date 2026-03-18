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
    
    # Helper to filter tasks (includes RBAC)
    def task_matches(t):
        if t.get("is_archived"):
            return False
        # RBAC filter: user sees only tasks where they are owner or supervisor
        if rbac_email:
            if t.get("owner_email") != rbac_email and t.get("supervisor_email") != rbac_email:
                return False
        if filter_proj and t.get("project_id") != filter_proj:
            return False
        if filter_user:
            if t.get("owner_email") != filter_user and t.get("supervisor_email") != filter_user:
                return False
        if filter_status == "Attivi":
            if t.get("status") in ("Completed", "Cancelled"):
                return False
        elif filter_status == "Completati":
            if t.get("status") != "Completed":
                return False
        elif filter_status == "Blocked":
            if t.get("status") != "Blocked":
                return False
        return True

    # RBAC-aware project list: only projects that have visible tasks
    if rbac_email:
        visible_proj_ids = {t["project_id"] for t in tasks if task_matches(t)}
        proj_list = [
            p for p in projects
            if (filter_proj is None or p["id"] == filter_proj)
            and p["id"] in visible_proj_ids
        ]
    else:
        proj_list = [p for p in projects if filter_proj is None or p["id"] == filter_proj]

    TABLE_HEADER = ["ID", "Nome Task", "Stato", "Priorità", "Owner", "Scadenza"]
    # Usable width ≈ A4 – margins = 170mm
    COL_WIDTHS = [20*mm, 58*mm, 22*mm, 18*mm, 30*mm, 22*mm]

    for proj_idx, proj in enumerate(proj_list):
        if proj_idx > 0:
            elements.append(PageBreak())

        pid = proj["id"]

        # ── Project header ─────────────────────────────────────────────────────
        elements.append(Paragraph(f"{proj.get('name')} ({proj.get('acronym','')})", h1))
        capt_parts = []
        if proj.get("funding_agency"):
            capt_parts.append(f"Ente finanziatore: {proj['funding_agency']}")
        if proj.get("start_date"):
            capt_parts.append(f"Periodo: {_fmt_date(proj.get('start_date'))} → {_fmt_date(proj.get('end_date'))}")
        elements.append(Paragraph("  ·  ".join(capt_parts), caption))
        elements.append(Spacer(1, 5))

        proj_deliverables = [
            d for d in deliverables
            if d.get("project_id") == pid
            and (rbac_email is None or any(
                t.get("deliverable_id") == d["id"] and task_matches(t)
                for t in tasks
            ))
        ]

        if proj_deliverables:
            elements.append(Paragraph("DELIVERABLES", label))

            for d in proj_deliverables:
                did     = d["id"]
                d_tasks = [t for t in tasks if t.get("deliverable_id") == did and task_matches(t)]
                total   = len(d_tasks)
                done    = len([t for t in d_tasks if t.get("status") == "Completed"])
                d_status = d.get("status", "Not started")
                d_stat_colour = STATUS_TEXT.get(d_status, colors.grey)

                elements.append(Spacer(1, 4))
                elements.append(Paragraph(d.get("name", ""), h2))
                elements.append(Paragraph(
                    f"{d.get('type')}  •  scadenza {_fmt_date(d.get('deadline'))}  •  "
                    f"{done}/{total} task completati  •  Stato: <font color='{d_stat_colour.hexval()}'>{d_status}</font>",
                    small
                ))
                elements.append(Spacer(1, 3))

                if d_tasks:
                    table_data = [TABLE_HEADER]
                    for t in d_tasks:
                        seq    = t.get("sequence_id") or f"T-{t['id']}"
                        tname  = t.get("name", "")
                        tstatus = t.get("status", "Not started")
                        tprio  = (t.get("priority") or "none").lower()
                        owner  = users_dict.get(t.get("owner_email"), t.get("owner_email") or "—")
                        dl     = _fmt_date(t.get("deadline"))
                        
                        stat_col = STATUS_TEXT.get(tstatus, colors.grey)
                        prio_col = PRIORITY_TEXT.get(tprio, colors.grey)
                        
                        row = [
                            Paragraph(f"<font color='grey'>{seq}</font>", small),
                            Paragraph(tname, normal),
                            Paragraph(f"<font color='{stat_col.hexval()}'>{tstatus}</font>", small),
                            Paragraph(f"<font color='{prio_col.hexval()}'>{tprio}</font>", small),
                            Paragraph(f"{_initials(owner)}  {owner}", small),
                            Paragraph(dl, small),
                        ]
                        table_data.append(row)

                    tbl = Table(table_data, colWidths=COL_WIDTHS, repeatRows=1)
                    tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
                        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE",   (0, 0), (-1, 0), 8),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]))
                    elements.append(tbl)
                else:
                    elements.append(Paragraph("Nessun task corrispondente ai filtri.", italic))
                elements.append(Spacer(1, 8))

        # ── Unassigned tasks ───────────────────────────────────────────────────
        unassigned = [
            t for t in tasks
            if t.get("project_id") == pid and not t.get("deliverable_id") and task_matches(t)
        ]

        if unassigned:
            elements.append(HRFlowable(width="100%", thickness=0.5, lineCap="butt",
                                        color=colors.HexColor("#CCCCCC"), dash=(3, 3)))
            elements.append(Spacer(1, 4))
            elements.append(Paragraph("TASK SENZA DELIVERABLE", label))
            elements.append(Paragraph("Task generali — non associati a un deliverable specifico", italic))
            elements.append(Spacer(1, 4))

            table_data = [TABLE_HEADER]
            for t in unassigned:
                seq     = t.get("sequence_id") or f"T-{t['id']}"
                tname   = t.get("name", "")
                tstatus = t.get("status", "Not started")
                tprio   = (t.get("priority") or "none").lower()
                owner   = users_dict.get(t.get("owner_email"), t.get("owner_email") or "—")
                dl      = _fmt_date(t.get("deadline"))
                
                stat_col = STATUS_TEXT.get(tstatus, colors.grey)
                prio_col = PRIORITY_TEXT.get(tprio, colors.grey)

                table_data.append([
                    Paragraph(f"<font color='grey'>{seq}</font>", small),
                    Paragraph(tname, normal),
                    Paragraph(f"<font color='{stat_col.hexval()}'>{tstatus}</font>", small),
                    Paragraph(f"<font color='{prio_col.hexval()}'>{tprio}</font>", small),
                    Paragraph(f"{_initials(owner)}  {owner}", small),
                    Paragraph(dl, small),
                ])

            tbl = Table(table_data, colWidths=COL_WIDTHS, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(tbl)

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

    today_str    = _dt.date.today().strftime("%Y/%m/%d")
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
