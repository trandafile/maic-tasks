"""utils/email_templates.py — Branded HTML e-mails.

The markup is deliberately old-school: nested tables, inline styles, no
flexbox/grid, no <style> block, no external images. That is what survives
Outlook and Gmail — modern CSS silently collapses there.

Colours mirror the app (brand navy, the urgency tints of the dashboard, the
same project-chip palette via ``stable_colour``) so a mail reads as the site.
Depends only on the standard library, so the GitHub Actions cron can import it
without installing Streamlit.
"""

from __future__ import annotations

import datetime
import html as _html

from utils.helpers import stable_colour

# ── Palette (kept in sync with the dashboard) ─────────────────────────────────
BRAND = "#1A3E8B"
BRAND_DARK = "#122C63"
PAGE_BG = "#F4F6F8"
CARD_BG = "#FFFFFF"
BORDER = "#E3E7EB"
TEXT = "#202124"
MUTED = "#7A8290"

URGENCY = {
    "overdue":  ("#C62828", "#FDECEC"),
    "due_soon": ("#B26A00", "#FFF4E5"),
    "blocked":  ("#D93025", "#FDEDEC"),
    "normal":   ("#5F6368", "#F1F3F4"),
}
STATUS = {
    "Not started": ("#5F6368", "#F1F3F4"),
    "Working on":  ("#1565C0", "#E8F1FC"),
    "Blocked":     ("#D93025", "#FDEDEC"),
    "Completed":   ("#2E7D32", "#E8F5E9"),
    "Cancelled":   ("#B71C1C", "#FFEBEE"),
}

FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "Helvetica,Arial,sans-serif")


def esc(v) -> str:
    return _html.escape(str(v or ""))


def _tint(hex_colour: str, weight: float = 0.12) -> str:
    """Mix a colour with white. `weight` = how much of the colour survives."""
    h = (hex_colour or "#000000").lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#F1F3F4"
    mix = lambda c: round(c * weight + 255 * (1 - weight))  # noqa: E731
    return "#{:02X}{:02X}{:02X}".format(mix(r), mix(g), mix(b))


def _fmt(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(str(d)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(d)


def _days_to(d: str | None):
    try:
        return (datetime.date.fromisoformat(str(d)[:10]) - datetime.date.today()).days
    except Exception:
        return None


# ── Atoms ─────────────────────────────────────────────────────────────────────

def chip(text: str, fg: str, bg: str | None = None, bold: bool = True) -> str:
    """A pill that stays legible even when the client strips backgrounds.

    Gmail drops the inline `background` of a <span> (a <span> cannot carry the
    bgcolor attribute that survives sanitising). So a chip is NEVER white text
    on a colour — it is coloured text on a pale tint, inside a coloured border.
    Lose the fill and you still read dark-on-white inside an outline.
    """
    if not text:
        return ""
    bg = bg or _tint(fg, 0.12)
    return (
        f'<span style="display:inline-block;background-color:{bg};'
        f'border:1px solid {_tint(fg, 0.40)};color:{fg};border-radius:4px;'
        f'padding:1px 7px;font-size:11px;'
        f"font-weight:{'700' if bold else '400'};font-family:{FONT};"
        f'white-space:nowrap;">{esc(text)}</span>'
    )


def project_chip(acronym: str | None) -> str:
    """Same hue as the app's project chip, but as coloured text on a tint."""
    if not acronym:
        return ""
    colour = stable_colour(acronym)
    return chip(acronym, colour, _tint(colour, 0.14))


def status_chip(status: str | None) -> str:
    s = status or "Not started"
    fg, bg = STATUS.get(s, STATUS["Not started"])
    return chip(s, fg, bg)


def deadline_chip(deadline: str | None, threshold: int = 14) -> str:
    if not deadline:
        return chip("no deadline", MUTED, "#F1F3F4", bold=False)
    days = _days_to(deadline)
    date_txt = _fmt(deadline)
    if days is None:
        return chip(date_txt, MUTED, "#F1F3F4", bold=False)
    if days < 0:
        fg, bg = URGENCY["overdue"]
        return chip(f"{date_txt} · scaduto da {abs(days)}g", fg, bg)
    if days <= threshold:
        fg, bg = URGENCY["due_soon"]
        label = "oggi" if days == 0 else f"tra {days}g"
        return chip(f"{date_txt} · {label}", fg, bg)
    fg, bg = URGENCY["normal"]
    return chip(date_txt, fg, bg, bold=False)


def button(url: str, label: str) -> str:
    # White-on-navy is safe here ONLY because the fill sits on a <td bgcolor=...>,
    # an HTML attribute the sanitiser keeps (unlike a CSS background on a span).
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:18px auto 4px auto;">'
        f'<tr><td align="center" bgcolor="{BRAND}" '
        f'style="background-color:{BRAND};border-radius:6px;">'
        f'<a href="{esc(url)}" target="_blank" '
        f'style="display:inline-block;padding:11px 26px;font-family:{FONT};'
        f'font-size:14px;font-weight:700;color:#FFFFFF;text-decoration:none;'
        f'border-radius:6px;">{esc(label)}</a>'
        f"</td></tr></table>"
    )


def stat_tiles(tiles: list[tuple[str, int, str]]) -> str:
    """tiles = [(label, value, urgency_key)] — rendered as one row of boxes."""
    if not tiles:
        return ""
    cells = []
    width = f"{100 // len(tiles)}%"
    for label, value, key in tiles:
        fg, bg = URGENCY.get(key, URGENCY["normal"])
        # bgcolor= (HTML attribute) survives Gmail's CSS sanitiser; the inline
        # background-color is the belt to that braces. The text is coloured, not
        # white, so the tile reads even if both are dropped.
        cells.append(
            f'<td width="{width}" align="center" style="padding:4px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0"><tr>'
            f'<td align="center" bgcolor="{bg}" style="background-color:{bg};'
            f'border:1px solid {_tint(fg, 0.30)};border-radius:6px;'
            f'padding:10px 4px;font-family:{FONT};">'
            f'<div style="font-size:22px;font-weight:800;color:{fg};line-height:1.1;">{value}</div>'
            f'<div style="font-size:11px;color:{fg};text-transform:uppercase;'
            f'letter-spacing:0.04em;font-weight:700;margin-top:2px;">{esc(label)}</div>'
            f"</td></tr></table></td>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:6px 0 2px 0;"><tr>{"".join(cells)}</tr></table>'
    )


def item_row(item: dict, threshold: int = 14) -> str:
    """One task/subtask line: project chip · name · status — deadline right."""
    name = item.get("name") or ""
    seq = item.get("sequence_id") or ""
    proj = item.get("project_acronym") or item.get("project_name") or ""
    is_sub = bool(item.get("task_id"))
    # "↳" (U+21B3) is missing from several e-mail fonts and rendered as garbage.
    # "›" (U+203A) is Latin-1 supplement territory: it renders everywhere.
    prefix = '<span style="color:#9AA3AF;">&rsaquo;&nbsp;</span>' if is_sub else ""

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="border-bottom:1px solid #EEF1F4;">'
        f'<tr>'
        f'<td style="padding:9px 10px;font-family:{FONT};vertical-align:top;">'
        f'{project_chip(proj)} '
        f'<span style="font-size:14px;font-weight:700;color:{TEXT};">'
        f"{prefix}{esc(name)}</span> {status_chip(item.get('status'))}"
        f'<div style="font-size:11px;color:{MUTED};margin-top:2px;">'
        f"{esc(seq)}</div>"
        f"</td>"
        f'<td align="right" style="padding:9px 10px;white-space:nowrap;vertical-align:top;">'
        f"{deadline_chip(item.get('deadline'), threshold)}"
        f"</td></tr></table>"
    )


def section(title: str, urgency_key: str, items: list[dict], threshold: int = 14) -> str:
    """A titled band followed by its items. Empty sections render nothing."""
    if not items:
        return ""
    fg, bg = URGENCY.get(urgency_key, URGENCY["normal"])
    rows = "".join(item_row(i, threshold) for i in items)
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:16px 0 0 0;">'
        f'<tr><td bgcolor="{bg}" style="background-color:{bg};'
        f'border-left:4px solid {fg};border-radius:5px;padding:7px 10px;'
        f'font-family:{FONT};">'
        f'<span style="font-size:13px;font-weight:800;color:{fg};'
        f'letter-spacing:0.02em;">{esc(title)}</span>'
        f'<span style="font-size:12px;font-weight:700;color:{fg};"> · {len(items)}</span>'
        f"</td></tr>"
        f'<tr><td style="padding:0;">{rows}</td></tr></table>'
    )


def paragraph(text_html: str, size: int = 14, color: str | None = None) -> str:
    return (
        f'<p style="margin:10px 0;font-family:{FONT};font-size:{size}px;'
        f'line-height:1.55;color:{color or TEXT};">{text_html}</p>'
    )


# ── Shell ─────────────────────────────────────────────────────────────────────

def shell(*, preheader: str, heading: str, body_html: str,
          app_url: str | None = None, cta_label: str = "Apri il Task Manager") -> str:
    """Wrap content in the branded frame. `preheader` is the inbox preview line."""
    cta = button(app_url, cta_label) if app_url else ""
    year = datetime.date.today().year
    return f"""<!DOCTYPE html>
<html lang="it">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(heading)}</title></head>
<body style="margin:0;padding:0;background-color:{PAGE_BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="{PAGE_BG}" style="background-color:{PAGE_BG};padding:24px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           bgcolor="{CARD_BG}"
           style="width:600px;max-width:100%;background-color:{CARD_BG};
                  border:1px solid {BORDER};border-radius:10px;overflow:hidden;">

      <tr><td bgcolor="{BRAND}" style="background-color:{BRAND};padding:18px 22px;font-family:{FONT};">
        <div style="font-size:19px;font-weight:800;color:#FFFFFF;letter-spacing:0.08em;">
          MAIC&nbsp;LAB</div>
        <div style="font-size:12px;color:#C3CEE8;margin-top:1px;">Task Manager</div>
      </td></tr>

      <tr><td style="padding:20px 22px 6px 22px;font-family:{FONT};">
        <div style="font-size:18px;font-weight:800;color:{TEXT};">{esc(heading)}</div>
      </td></tr>

      <tr><td style="padding:0 22px 18px 22px;">{body_html}{cta}</td></tr>

      <tr><td bgcolor="#FAFBFC" style="background-color:#FAFBFC;border-top:1px solid {BORDER};
                     padding:14px 22px;font-family:{FONT};">
        <div style="font-size:11px;color:{MUTED};line-height:1.5;">
          MAIC LAB — Università della Calabria, DIMES<br>
          Messaggio automatico del Task Manager · {year}
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""
