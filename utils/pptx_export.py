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

MONTHS_IT = {1:"gennaio",2:"febbraio",3:"marzo",4:"aprile",5:"maggio",6:"giugno",
             7:"luglio",8:"agosto",9:"settembre",10:"ottobre",11:"novembre",12:"dicembre"}


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
    return f"{d.day} {MONTHS_IT[d.month]} {d.year}"


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


# ── Deck 1: weekly meeting (delta) ────────────────────────────────────────────

def build_meeting_deck(delta: dict, since: datetime.date, until: datetime.date) -> BytesIO:
    """delta = {"by_person": {email: {...}}, "totals": {...}} — see db.get_meeting_delta."""
    prs = _open()
    period = f"{_long_date(since)} — {_long_date(until)}"

    _title_slide(prs, "Riunione di laboratorio",
                 "Cosa è cambiato dall'ultima volta", period)

    t = delta.get("totals", {})
    _summary_slide(
        prs, "In sintesi", period,
        [("completati", t.get("completed", 0), GREEN),
         ("avanzati",   t.get("moved", 0),     CYAN),
         ("bloccati",   t.get("blocked", 0),   CRIMSON),
         ("fermi",      t.get("stale", 0),     ORANGE)],
        footer="Fermi = nessun aggiornamento nel periodo di soglia. "
               "Su un task lungo conta più della scadenza.",
    )

    W = prs.slide_width
    for person in delta.get("by_person", []):
        s = _new_slide(prs)
        _header(s, prs, person.get("name", "—"),
                f"{period}   ·   {person.get('active', 0)} task attivi")
        colw = (W - Inches(1.5)) / 2
        left, right = Inches(0.6), Inches(0.6) + colw + Inches(0.3)

        y = _section(s, left, Inches(1.55), colw, "COMPLETATI", GREEN,
                     len(person.get("completed", [])))
        y = _items(s, left, y, colw, person.get("completed", []), GREEN,
                   sub=lambda it: it.get("_project", ""))
        y = _section(s, left, y + Inches(0.15), colw, "AVANZATI", CYAN,
                     len(person.get("moved", [])))
        _items(s, left, y, colw, person.get("moved", []), CYAN,
               sub=lambda it: f"{it.get('_project','')} · {it.get('status','')}")

        y = _section(s, right, Inches(1.55), colw, "BLOCCATI", CRIMSON,
                     len(person.get("blocked", [])))
        y = _items(s, right, y, colw, person.get("blocked", []), CRIMSON,
                   sub=lambda it: f"{it.get('_project','')} · da {it.get('_stale','?')}g")
        y = _section(s, right, y + Inches(0.15), colw, "FERMI", ORANGE,
                     len(person.get("stale", [])))
        _items(s, right, y, colw, person.get("stale", []), ORANGE,
               sub=lambda it: f"{it.get('_project','')} · fermo da {it.get('_stale','?')}g")

        _footer(s, prs, "Bloccati e fermi sono i punti da discutere adesso.")

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


# ── Deck 2: project review (cumulative) ───────────────────────────────────────

def build_review_deck(review: dict) -> BytesIO:
    """review = see db.get_project_review — cumulative status per deliverable."""
    prs = _open()
    proj = review.get("project", {})
    name = proj.get("name", "Progetto")
    acr = proj.get("acronym") or proj.get("identifier") or ""
    today = datetime.date.today()

    period = review.get("period_label") or f"Stato al {_long_date(today)}"
    _title_slide(prs, f"{acr}" if acr else name,
                 name if acr else "Stato di avanzamento", period)

    t = review.get("totals", {})
    done, total = t.get("completed", 0), t.get("total", 0)
    pct = round(100 * done / total) if total else 0
    _summary_slide(
        prs, "Stato di avanzamento", f"{name}   ·   {period}",
        [("completamento", f"{pct}%", GREEN if pct >= 66 else CYAN),
         ("task totali",   total,                 TEAL),
         ("in ritardo",    t.get("overdue", 0),   CRIMSON),
         ("a rischio",     t.get("at_risk", 0),   ORANGE)],
        footer=f"CUP {proj.get('cup') or '—'}   ·   {proj.get('funding_agency') or ''}",
    )

    W = prs.slide_width
    for d in review.get("deliverables", []):
        s = _new_slide(prs)
        dt = d.get("totals", {})
        dpct = dt.get("pct", 0) / 100.0
        _header(s, prs, d.get("name", "Deliverable"),
                f"{d.get('type','')}   ·   scadenza {_fmt(d.get('deadline'))}"
                f"   ·   {dt.get('completed',0)}/{dt.get('total',0)} task completati")

        # progress bar
        _bar(s, Inches(0.6), Inches(1.5), W - Inches(1.2), Inches(0.22), dpct,
             GREEN if dpct >= 0.66 else (CYAN if dpct >= 0.33 else ORANGE))
        _text(s, Inches(0.6), Inches(1.78), W - Inches(1.2), Inches(0.3),
              f"{dt.get('pct',0)}% completato", size=11, bold=True, color=MUTED)

        colw = (W - Inches(1.5)) / 2
        left, right = Inches(0.6), Inches(0.6) + colw + Inches(0.3)

        y = _section(s, left, Inches(2.3), colw, "COMPLETATI", GREEN, len(d.get("completed", [])))
        _items(s, left, y, colw, d.get("completed", []), GREEN, max_rows=7,
               sub=lambda it: f"chiuso il {_fmt(it.get('completion_date'))}")

        y = _section(s, right, Inches(2.3), colw, "IN CORSO", CYAN, len(d.get("in_progress", [])))
        y = _items(s, right, y, colw, d.get("in_progress", []), CYAN, max_rows=5,
                   sub=lambda it: f"scadenza {_fmt(it.get('deadline'))}")
        risks = d.get("risks", [])
        y = _section(s, right, y + Inches(0.15), colw, "RISCHI", CRIMSON, len(risks))
        _items(s, right, y, colw, risks, CRIMSON, max_rows=4,
               sub=lambda it: it.get("_why", ""))

        _footer(s, prs, f"{name}   ·   generato il {_long_date(today)}")

    # Tasks with no deliverable, if any
    orphans = review.get("no_deliverable", [])
    if orphans:
        s = _new_slide(prs)
        _header(s, prs, "Attività non associate a deliverable",
                f"{len(orphans)} task")
        _items(s, Inches(0.6), Inches(1.7), prs.slide_width - Inches(1.2),
               orphans, TEAL, max_rows=12,
               sub=lambda it: f"{it.get('status','')} · scadenza {_fmt(it.get('deadline'))}")

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
