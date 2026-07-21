"""utils/pptx_export.py — slide decks from the MAIC LAB template.

Two decks, deliberately different, because they answer to different audiences:

* **Meeting** (weekly lab meeting) — the *delta*: what closed, what got stuck,
  what has gone quiet, one slide per person. Whoever is in the room already
  knows the context; a full list would kill the meeting.
* **Review** (SAL / MIUR / partners) — the *cumulative* state per deliverable,
  with completion and risks. A funder does not care what moved last week; they
  need "WP2 at 70%, D2.1 delivered, one open risk".

Both are generated on top of ``assets/maic_template.pptx`` so they inherit the
real master, logo and theme. Colours come from the template's own palette, not
from the app's, so the output looks like MAIC LAB rather than like a tool.
"""

from __future__ import annotations

import datetime
from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "maic_template.pptx"

# ── Template palette (read from the theme of Es.pptx) ─────────────────────────
CRIMSON = RGBColor(0xB8, 0x0D, 0x48)   # accent1 — late / blocked
ORANGE  = RGBColor(0xF2, 0x97, 0x24)   # accent2 — at risk / stale
TEAL    = RGBColor(0x2B, 0x6A, 0x6C)   # accent3 — headings
CYAN    = RGBColor(0x00, 0xAD, 0xDC)   # accent4 — in progress
GREEN   = RGBColor(0x5C, 0x99, 0x29)   # accent5 — done
INK     = RGBColor(0x33, 0x3F, 0x4F)   # dk1 — body text
MUTED   = RGBColor(0x86, 0x8E, 0x99)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
RULE    = RGBColor(0xE0, 0xE3, 0xE7)

FONT_H = "Calibri Light"
FONT_B = "Calibri"

# The decks are in English: the team is international and the same deck is
# shown at the lab meeting and to partners.
MONTHS_EN = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
             7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}


def _d(v):
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _fmt(v) -> str:
    d = _d(v)
    return d.strftime("%d/%m/%Y") if d else "—"


def _long_date(d: datetime.date) -> str:
    return f"{d.day} {MONTHS_EN[d.month]} {d.year}"


# ── Low-level drawing ─────────────────────────────────────────────────────────

def _blank(prs: Presentation):
    """A layout with as little furniture as possible, so we own the canvas."""
    for name in ("Solo titolo", "Sine numero", "Tabula solita"):
        for lay in prs.slide_layouts:
            if lay.name == name:
                return lay
    return prs.slide_layouts[0]


def _clear_placeholders(slide):
    """Drop the layout's empty placeholders: an unfilled one prints as
    'Click to add title' in some viewers."""
    for shp in list(slide.shapes):
        if shp.is_placeholder and not (shp.has_text_frame and shp.text_frame.text.strip()):
            shp._element.getparent().remove(shp._element)


def _text(slide, x, y, w, h, text, *, size=14, bold=False, color=INK,
          font=FONT_B, align=PP_ALIGN.LEFT, wrap=True, space_after=0):
    box = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    p.space_after = Pt(space_after)
    r = p.add_run()
    r.text = str(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = font
    return box


def _rect(slide, x, y, w, h, fill, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(x)), Emu(int(y)),
                               Emu(int(w)), Emu(int(h)))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
    s.shadow.inherit = False
    return s


def _bar(slide, x, y, w, h, pct, colour):
    """Progress bar: track + fill. pct in 0..1."""
    _rect(slide, x, y, w, h, RULE)
    if pct > 0:
        _rect(slide, x, y, max(int(w * min(pct, 1.0)), Emu(20000)), h, colour)


def _header(slide, prs, title, subtitle=""):
    W = prs.slide_width
    _rect(slide, 0, 0, W, Inches(0.06), TEAL)
    _text(slide, Inches(0.6), Inches(0.34), W - Inches(1.2), Inches(0.55),
          title, size=28, bold=True, color=INK, font=FONT_H)
    if subtitle:
        _text(slide, Inches(0.6), Inches(0.92), W - Inches(1.2), Inches(0.34),
              subtitle, size=13, color=MUTED)


def _footer(slide, prs, note):
    _text(slide, Inches(0.6), prs.slide_height - Inches(0.5),
          prs.slide_width - Inches(1.2), Inches(0.3), note, size=9, color=MUTED)


def _chip(slide, x, y, label, colour, w=None):
    """Coloured count chip: number + caption, used for the summary rows."""
    w = w or Inches(2.1)
    h = Inches(0.86)
    _rect(slide, x, y, w, h, colour)
    return w


def _new_slide(prs):
    s = prs.slides.add_slide(_blank(prs))
    _clear_placeholders(s)
    return s


_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _strip_existing(prs):
    """Remove the template's sample slides, keeping masters, theme and logo.

    Dropping the entry from sldIdLst alone is not enough: the slide *part*
    stays in the package, so the new slides are written under names that
    already exist and the .pptx ends up with duplicate zip entries (PowerPoint
    then offers to "repair" it). Dropping the relationship removes the part too.
    """
    ids = prs.slides._sldIdLst
    for sld in list(ids):
        rid = sld.get(_R_ID)
        ids.remove(sld)
        if rid:
            try:
                prs.part.drop_rel(rid)
            except KeyError:
                pass


def _open() -> Presentation:
    prs = Presentation(str(TEMPLATE)) if TEMPLATE.exists() else Presentation()
    _strip_existing(prs)
    if not TEMPLATE.exists():          # fall back to a plain 16:9 deck
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    return prs


# ── Title slide ───────────────────────────────────────────────────────────────

def _title_slide(prs, title, subtitle, meta):
    s = _new_slide(prs)
    W, H = prs.slide_width, prs.slide_height
    _rect(s, 0, 0, W, H, RGBColor(0xF7, 0xF8, 0xF9))
    _rect(s, 0, 0, Inches(0.18), H, TEAL)
    _text(s, Inches(0.9), H / 2 - Inches(1.1), W - Inches(1.8), Inches(0.4),
          "MAIC LAB", size=13, bold=True, color=TEAL, font=FONT_H)
    _text(s, Inches(0.9), H / 2 - Inches(0.68), W - Inches(1.8), Inches(1.0),
          title, size=40, bold=True, color=INK, font=FONT_H)
    _text(s, Inches(0.9), H / 2 + Inches(0.30), W - Inches(1.8), Inches(0.45),
          subtitle, size=17, color=TEAL)
    _text(s, Inches(0.9), H - Inches(1.15), W - Inches(1.8), Inches(0.35),
          meta, size=11, color=MUTED)
    return s


def _summary_slide(prs, title, subtitle, tiles, footer=""):
    """A row of big coloured numbers — the 'so what' of the deck."""
    s = _new_slide(prs)
    _header(s, prs, title, subtitle)
    W = prs.slide_width
    n = max(len(tiles), 1)
    gap = Inches(0.28)
    total_w = W - Inches(1.2) - gap * (n - 1)
    w = int(total_w / n)
    y = Inches(2.0)
    for i, (label, value, colour) in enumerate(tiles):
        x = Inches(0.6) + i * (w + gap)
        _rect(s, x, y, w, Inches(1.9), colour)
        _text(s, x, y + Inches(0.30), w, Inches(0.8), str(value),
              size=46, bold=True, color=WHITE, font=FONT_H, align=PP_ALIGN.CENTER)
        _text(s, x, y + Inches(1.25), w, Inches(0.4), label.upper(),
              size=11, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    if footer:
        _footer(s, prs, footer)
    return s


# ── Item lists ────────────────────────────────────────────────────────────────

def _section(slide, x, y, w, label, colour, count):
    _rect(slide, x, y, Inches(0.05), Inches(0.28), colour)
    _text(slide, x + Inches(0.15), y + Inches(0.01), w, Inches(0.28),
          f"{label}  ·  {count}", size=12, bold=True, color=colour)
    return y + Inches(0.38)


def _items(slide, x, y, w, items, colour, *, max_rows=6, line=Inches(0.32),
           label=lambda it: it.get("name", ""), sub=lambda it: ""):
    for it in items[:max_rows]:
        _rect(slide, x + Inches(0.16), y + Inches(0.10), Inches(0.07), Inches(0.07), colour)
        _text(slide, x + Inches(0.36), y, w - Inches(0.5), line,
              label(it), size=12, color=INK)
        extra = sub(it)
        if extra:
            _text(slide, x + Inches(0.36), y + Inches(0.17), w - Inches(0.5), Inches(0.2),
                  extra, size=9, color=MUTED)
            y += Inches(0.10)
        y += line
    if len(items) > max_rows:
        _text(slide, x + Inches(0.36), y, w - Inches(0.5), Inches(0.24),
              f"… e altri {len(items) - max_rows}", size=10, color=MUTED)
        y += Inches(0.28)
    if not items:
        _text(slide, x + Inches(0.36), y, w - Inches(0.5), Inches(0.24),
              "—", size=11, color=MUTED)
        y += Inches(0.30)
    return y


# ── Section dividers and tree rendering ───────────────────────────────────────

def _divider_slide(prs, number: int, title: str, subtitle: str = ""):
    """A numbered section break, so the deck reads as an agenda."""
    s = _new_slide(prs)
    W, H = prs.slide_width, prs.slide_height
    _rect(s, 0, 0, W, H, TEAL)
    _text(s, Inches(0.9), H / 2 - Inches(1.05), W - Inches(1.8), Inches(0.5),
          f"{number:02d}", size=54, bold=True, color=RGBColor(0x9F, 0xC4, 0xC5), font=FONT_H)
    _text(s, Inches(0.9), H / 2 - Inches(0.25), W - Inches(1.8), Inches(0.8),
          title, size=34, bold=True, color=WHITE, font=FONT_H)
    if subtitle:
        _text(s, Inches(0.9), H / 2 + Inches(0.6), W - Inches(1.8), Inches(0.5),
              subtitle, size=14, color=RGBColor(0xCB, 0xE0, 0xE1))
    return s


_SEV_COLOUR = {"ok": GREEN, "warn": ORANGE, "bad": CRIMSON, "none": MUTED}
_STATUS_COLOUR = {
    "Completed": GREEN, "Working on": CYAN, "Blocked": CRIMSON,
    "Not started": MUTED, "Cancelled": MUTED,
}
_ROWS_PER_SLIDE = 15


def _tree_header(slide, prs, y):
    """Column captions for the tree table."""
    W = prs.slide_width
    x0 = Inches(0.6)
    cols = _tree_cols(W)
    for label, x in (("ITEM", x0), ("STATUS", cols["status"]),
                     ("DEADLINE", cols["deadline"]), ("OWNER / SUP.", cols["people"]),
                     ("UPDATED", cols["fresh"])):
        _text(slide, x, y, Inches(2.0), Inches(0.22), label,
              size=8, bold=True, color=MUTED)
    _rect(slide, x0, y + Inches(0.24), W - Inches(1.2), Emu(9525), RULE)
    return y + Inches(0.34)


def _tree_cols(W):
    return {
        "status":   W - Inches(6.05),
        "deadline": W - Inches(4.35),
        "people":   W - Inches(3.05),
        "fresh":    W - Inches(1.05),
    }


def _tree_rows(prs, title, subtitle, rows, footer=""):
    """Render an indented tree across as many slides as it needs."""
    slides = []
    pages = [rows[i:i + _ROWS_PER_SLIDE] for i in range(0, len(rows), _ROWS_PER_SLIDE)] or [[]]
    W = prs.slide_width
    cols = _tree_cols(W)

    for pi, page in enumerate(pages):
        s = _new_slide(prs)
        _header(s, prs, title if pi == 0 else f"{title} (cont.)", subtitle)
        y = _tree_header(s, prs, Inches(1.5))

        for r in page:
            lvl = r.get("level", 0)
            indent = Inches(0.6) + Inches(0.28) * lvl
            kind = r.get("kind", "task")

            if kind in ("deliverable", "group"):
                _rect(s, Inches(0.6), y - Inches(0.03), W - Inches(1.2),
                      Inches(0.30), RGBColor(0xEF, 0xF3, 0xF4))
                marker, size, bold, colour = "▸", 12, True, TEAL
            elif kind == "subtask":
                marker, size, bold, colour = "›", 10, False, MUTED
            else:
                marker, size, bold, colour = "•", 11, False, INK

            _text(s, indent, y, Inches(0.2), Inches(0.26), marker,
                  size=size, bold=bold, color=colour)
            _text(s, indent + Inches(0.22), y, cols["status"] - indent - Inches(0.3),
                  Inches(0.26), r.get("name", ""), size=size, bold=bold, color=colour, wrap=False)

            if r.get("status"):
                _text(s, cols["status"], y + Emu(9525), Inches(1.6), Inches(0.24),
                      r["status"], size=9,
                      color=_STATUS_COLOUR.get(r["status"], MUTED), bold=True)
            if r.get("deadline"):
                _text(s, cols["deadline"], y + Emu(9525), Inches(1.2), Inches(0.24),
                      _fmt(r["deadline"]), size=9, color=INK)
            if r.get("people"):
                _text(s, cols["people"], y + Emu(9525), Inches(2.0), Inches(0.24),
                      r["people"], size=9, color=MUTED, wrap=False)
            if r.get("fresh"):
                _text(s, cols["fresh"], y + Emu(9525), Inches(0.9), Inches(0.24),
                      r["fresh"], size=9, bold=r.get("sev") in ("warn", "bad"),
                      color=_SEV_COLOUR.get(r.get("sev", "none"), MUTED))
            y += Inches(0.33)

        if not page:
            _text(s, Inches(0.6), Inches(1.7), W - Inches(1.2), Inches(0.3),
                  "Nothing to show.", size=12, color=MUTED)
        _footer(s, prs, footer or "UPDATED = days since anyone last touched the item.")
        slides.append(s)
    return slides


# ── Deck 1: lab meeting ───────────────────────────────────────────────────────

def build_meeting_deck(pack: dict) -> BytesIO:
    """The weekly lab meeting deck, in four sections:

    1. Deliverables due soon   2. Projects (tree)
    3. Individual work         4. Next deadlines (conferences)
    """
    prs = _open()
    since, until = pack["since"], pack["until"]
    period = f"{_long_date(since)} — {_long_date(until)}"
    W = prs.slide_width

    _title_slide(prs, "Lab meeting", "Status review", period)

    # ── 1. Deliverables due soon ─────────────────────────────────────────────
    horizon = pack.get("horizon_months", 3)
    ups = pack.get("upcoming", [])
    _divider_slide(prs, 1, "Deliverables due soon",
                   f"Next {horizon} months · {len(ups)} deliverables")
    rows = []
    for d in ups:
        days = d["_days"]
        sev = "bad" if days < 0 else ("warn" if days <= 30 else "ok")
        when = f"{abs(days)}d overdue" if days < 0 else (
            "today" if days == 0 else f"in {days}d")
        rows.append({
            "level": 0, "kind": "deliverable",
            "name": f"[{d['_project']}] {d.get('name','')}",
            "status": d.get("status") or "Not started",
            "deadline": d.get("deadline"), "people": d["_people"],
            "fresh": when, "sev": sev,
        })
        rows.append({
            "level": 1, "kind": "task",
            "name": f"{d['_done']}/{d['_total']} tasks completed · {d['_pct']}%",
            "status": "", "deadline": None, "people": "", "fresh": "", "sev": "none",
        })
    _tree_rows(prs, "Deliverables due soon",
               f"Deadline within {horizon} months · sorted by urgency", rows,
               footer="The right-hand column is time to deadline, not freshness.")

    # ── 2. Projects ──────────────────────────────────────────────────────────
    trees = pack.get("trees", [])
    _divider_slide(prs, 2, "Projects",
                   f"{len(trees)} active projects · deliverables, tasks and subtasks")
    for t in trees:
        head = f"{t['acronym']} — {t['name']}" if t["acronym"] else t["name"]
        c = t["counts"]
        _tree_rows(prs, head,
                   f"{c['deliverables']} deliverables · {c['tasks']} tasks",
                   t["rows"])

    # ── 3. Individual work ───────────────────────────────────────────────────
    delta = pack.get("delta", {})
    people = delta.get("by_person", [])
    tot = delta.get("totals", {})
    _divider_slide(prs, 3, "Individual work", f"{period} · {len(people)} people")
    _summary_slide(
        prs, "What changed", period,
        [("completed", tot.get("completed", 0), GREEN),
         ("moved",     tot.get("moved", 0),     CYAN),
         ("blocked",   tot.get("blocked", 0),   CRIMSON),
         ("idle",      tot.get("stale", 0),     ORANGE)],
        footer="Idle = no update for the staleness threshold. On a long task "
               "that matters more than the deadline.",
    )
    for person in people:
        s = _new_slide(prs)
        _header(s, prs, person.get("name", "—"),
                f"{period}   ·   {person.get('active', 0)} active tasks")
        colw = (W - Inches(1.5)) / 2
        left, right = Inches(0.6), Inches(0.6) + colw + Inches(0.3)

        y = _section(s, left, Inches(1.55), colw, "COMPLETED", GREEN,
                     len(person.get("completed", [])))
        y = _items(s, left, y, colw, person.get("completed", []), GREEN,
                   sub=lambda it: it.get("_project", ""))
        y = _section(s, left, y + Inches(0.15), colw, "MOVED", CYAN,
                     len(person.get("moved", [])))
        _items(s, left, y, colw, person.get("moved", []), CYAN,
               sub=lambda it: f"{it.get('_project','')} · {it.get('status','')}")

        y = _section(s, right, Inches(1.55), colw, "BLOCKED", CRIMSON,
                     len(person.get("blocked", [])))
        y = _items(s, right, y, colw, person.get("blocked", []), CRIMSON,
                   sub=lambda it: f"{it.get('_project','')} · idle {it.get('_stale','?')}d")
        y = _section(s, right, y + Inches(0.15), colw, "IDLE", ORANGE,
                     len(person.get("stale", [])))
        _items(s, right, y, colw, person.get("stale", []), ORANGE,
               sub=lambda it: f"{it.get('_project','')} · idle {it.get('_stale','?')}d")

        _footer(s, prs, "Blocked and idle items are what this meeting is for.")

    # ── 4. Next deadlines (conferences) ──────────────────────────────────────
    confs = pack.get("conferences", [])
    ch = pack.get("conf_horizon_months", 12)
    _divider_slide(prs, 4, "Next deadlines",
                   f"Conference submissions · next {ch} months")
    if confs:
        _timeline_slide(prs, confs, ch)
        crows = []
        for c in confs:
            days = c["_days"]
            sev = "bad" if days <= 30 else ("warn" if days <= 90 else "ok")
            loc = f" · {c.get('location')}" if c.get("location") else ""
            crows.append({
                "level": 0, "kind": "deliverable",
                "name": f"{c['_label']}{loc}",
                "status": "", "deadline": c.get("submission_deadline"),
                "people": (c.get("rank") or ""),
                "fresh": f"in {days}d" if days >= 0 else f"{abs(days)}d ago",
                "sev": sev,
            })
            if c["_papers"]:
                crows.extend(c["_papers"])
            else:
                crows.append({"level": 1, "kind": "subtask", "name": "no paper draft yet",
                              "status": "", "deadline": None, "people": "",
                              "fresh": "", "sev": "none"})
        _tree_rows(prs, "Conferences and paper drafts",
                   "Submission deadline, and the papers targeting each",
                   crows, footer="A conference with no draft is a decision waiting to be made.")
    else:
        s = _new_slide(prs)
        _header(s, prs, "Next deadlines", "No conference in the horizon")
        _text(s, Inches(0.6), Inches(1.8), W - Inches(1.2), Inches(0.4),
              "No conference with a submission deadline in the selected window. "
              "Add them under Conference Calendar.", size=13, color=MUTED)

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


def _timeline_slide(prs, confs, months):
    """A wide horizontal timeline: one marker per conference submission."""
    s = _new_slide(prs)
    _header(s, prs, "Submission timeline", f"Next {months} months")
    W, H = prs.slide_width, prs.slide_height
    x0, x1 = Inches(1.0), W - Inches(1.0)
    y = Inches(3.5)
    span = max(months * 30.44, 1)

    _rect(s, x0, y, x1 - x0, Emu(19050), RGBColor(0xC9, 0xD1, 0xD6))

    # month ticks
    today = datetime.date.today()
    for m in range(months + 1):
        d = today + datetime.timedelta(days=int(30.44 * m))
        fx = x0 + (x1 - x0) * (30.44 * m) / span
        _rect(s, fx, y - Inches(0.07), Emu(9525), Inches(0.14), RGBColor(0xC9, 0xD1, 0xD6))
        if m % max(1, months // 6) == 0:
            _text(s, fx - Inches(0.35), y + Inches(0.16), Inches(0.7), Inches(0.2),
                  d.strftime("%b %y"), size=8, color=MUTED, align=PP_ALIGN.CENTER)

    above = True
    for c in confs:
        days = max(c["_days"], 0)
        fx = x0 + (x1 - x0) * min(days / span, 1.0)
        colour = CRIMSON if c["_days"] <= 30 else (ORANGE if c["_days"] <= 90 else TEAL)
        _rect(s, fx - Emu(28575), y - Inches(0.12), Emu(57150), Inches(0.28), colour)
        ly = y - Inches(0.95) if above else y + Inches(0.5)
        _rect(s, fx - Emu(4763), min(ly + Inches(0.4), y), Emu(9525),
              Inches(0.45), RGBColor(0xDD, 0xE2, 0xE5))
        _text(s, fx - Inches(0.95), ly, Inches(1.9), Inches(0.24),
              c["_label"], size=10, bold=True, color=colour, align=PP_ALIGN.CENTER, wrap=False)
        _text(s, fx - Inches(0.95), ly + Inches(0.22), Inches(1.9), Inches(0.2),
              f"{_fmt(c.get('submission_deadline'))} · {len(c['_papers'])} draft"
              f"{'' if len(c['_papers']) == 1 else 's'}",
              size=8, color=MUTED, align=PP_ALIGN.CENTER, wrap=False)
        above = not above

    _footer(s, prs, "Red: within 30 days · orange: within 90 days.")
    return s


# ── Deck 2: project review (cumulative) ───────────────────────────────────────

def build_review_deck(review: dict) -> BytesIO:
    """review = see db.get_project_review — cumulative status per deliverable."""
    prs = _open()
    proj = review.get("project", {})
    name = proj.get("name", "Progetto")
    acr = proj.get("acronym") or proj.get("identifier") or ""
    today = datetime.date.today()

    period = review.get("period_label") or f"Status as of {_long_date(today)}"
    _title_slide(prs, f"{acr}" if acr else name,
                 name if acr else "Progress status", period)

    t = review.get("totals", {})
    done, total = t.get("completed", 0), t.get("total", 0)
    pct = round(100 * done / total) if total else 0
    _summary_slide(
        prs, "Progress status", f"{name}   ·   {period}",
        [("completion", f"{pct}%", GREEN if pct >= 66 else CYAN),
         ("total tasks", total,                 TEAL),
         ("overdue",     t.get("overdue", 0),   CRIMSON),
         ("at risk",     t.get("at_risk", 0),   ORANGE)],
        footer=f"CUP {proj.get('cup') or '—'}   ·   {proj.get('funding_agency') or ''}",
    )

    W = prs.slide_width
    for d in review.get("deliverables", []):
        s = _new_slide(prs)
        dt = d.get("totals", {})
        dpct = dt.get("pct", 0) / 100.0
        _header(s, prs, d.get("name", "Deliverable"),
                f"{d.get('type','')}   ·   due {_fmt(d.get('deadline'))}"
                f"   ·   {dt.get('completed',0)}/{dt.get('total',0)} tasks completed")

        # progress bar
        _bar(s, Inches(0.6), Inches(1.5), W - Inches(1.2), Inches(0.22), dpct,
             GREEN if dpct >= 0.66 else (CYAN if dpct >= 0.33 else ORANGE))
        _text(s, Inches(0.6), Inches(1.78), W - Inches(1.2), Inches(0.3),
              f"{dt.get('pct',0)}% complete", size=11, bold=True, color=MUTED)

        colw = (W - Inches(1.5)) / 2
        left, right = Inches(0.6), Inches(0.6) + colw + Inches(0.3)

        y = _section(s, left, Inches(2.3), colw, "COMPLETED", GREEN, len(d.get("completed", [])))
        _items(s, left, y, colw, d.get("completed", []), GREEN, max_rows=7,
               sub=lambda it: f"closed {_fmt(it.get('completion_date'))}")

        y = _section(s, right, Inches(2.3), colw, "IN PROGRESS", CYAN, len(d.get("in_progress", [])))
        y = _items(s, right, y, colw, d.get("in_progress", []), CYAN, max_rows=5,
                   sub=lambda it: f"due {_fmt(it.get('deadline'))}")
        risks = d.get("risks", [])
        y = _section(s, right, y + Inches(0.15), colw, "RISKS", CRIMSON, len(risks))
        _items(s, right, y, colw, risks, CRIMSON, max_rows=4,
               sub=lambda it: it.get("_why", ""))

        _footer(s, prs, f"{name}   ·   generated {_long_date(today)}")

    # Tasks with no deliverable, if any
    orphans = review.get("no_deliverable", [])
    if orphans:
        s = _new_slide(prs)
        _header(s, prs, "Tasks not linked to a deliverable",
                f"{len(orphans)} tasks")
        _items(s, Inches(0.6), Inches(1.7), prs.slide_width - Inches(1.2),
               orphans, TEAL, max_rows=12,
               sub=lambda it: f"{it.get('status','')} · due {_fmt(it.get('deadline'))}")

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
