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
    
    # Helper to filter tasks
    def task_matches(t):
        if t.get("is_archived"):
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

        proj_deliverables = [d for d in deliverables if d.get("project_id") == pid]

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
