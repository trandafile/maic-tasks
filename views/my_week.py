"""views/my_week.py — the low-friction update surface.

One screen, every item you own, status changeable **in place** and a one-line
progress note. No modal, no navigation, no save-and-lose-your-place.

The design premise: engagement dies on friction, not on motivation. Updating
five tasks used to cost five modal open/edit/save/close cycles; here it is five
dropdowns on one page. And because a long research task cannot show progress
through its deadline, what this view really collects is the *note* — two lines
on where you are — which is also what clears the "stale" flag.
"""

from __future__ import annotations

import datetime
import html

import streamlit as st

from db import (
    get_my_week, quick_update, days_since_update, stale_threshold,
    get_activity_stats, get_settings,
)
from utils.helpers import PRIORITY_ORDER, stable_colour, TASK_NAME_STYLE, SUBTASK_NAME_STYLE

_STATUSES = ["Not started", "Working on", "Blocked", "Completed"]

_STATUS_COLOUR = {
    "Not started": "#5F6368",
    "Working on": "#1565C0",
    "Blocked": "#D93025",
    "Completed": "#2E7D32",
    "Cancelled": "#B71C1C",
}


def _esc(v) -> str:
    return html.escape(str(v or ""))


def _parse(v):
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _deadline_bit(deadline, threshold: int) -> str:
    d = _parse(deadline)
    if not d:
        return "<span style='color:#aaa;font-size:11px'>senza scadenza</span>"
    delta = (d - datetime.date.today()).days
    if delta < 0:
        return (f"<span style='color:#C62828;font-size:11px;font-weight:700'>"
                f"📅 {d.strftime('%d/%m/%Y')} · scaduto da {abs(delta)}g</span>")
    if delta <= threshold:
        lbl = "oggi" if delta == 0 else f"tra {delta}g"
        return (f"<span style='color:#B26A00;font-size:11px;font-weight:700'>"
                f"📅 {d.strftime('%d/%m/%Y')} · {lbl}</span>")
    return f"<span style='color:#666;font-size:11px'>📅 {d.strftime('%d/%m/%Y')}</span>"


def _stale_bit(item: dict, threshold: int) -> str:
    """The primary signal for long tasks: how long since anyone touched this."""
    d = days_since_update(item)
    if d is None:
        return ""  # migration not run — say nothing rather than something wrong
    if d >= threshold * 2:
        fg, bg = "#B80D48", "#FBE7EE"
    elif d >= threshold:
        fg, bg = "#B26A00", "#FFF4E5"
    else:
        return (f"<span style='color:#5C9929;font-size:11px'>aggiornato "
                f"{'oggi' if d == 0 else f'{d}g fa'}</span>")
    return (f"<span style='background:{bg};color:{fg};border-radius:4px;padding:1px 7px;"
            f"font-size:11px;font-weight:700'>⏳ fermo da {d}g</span>")


def _proj_chip(label: str) -> str:
    if not label:
        return ""
    c = stable_colour(label)
    return (f"<span style='background:{c};color:#fff;border-radius:4px;padding:1px 7px;"
            f"font-size:10px;font-weight:700'>{_esc(label)}</span>")


def _row(item: dict, kind: str, ctx: dict, idx: int):
    """One editable row. Status select + note box + Save, all inline."""
    table = "tasks" if kind == "task" else "subtasks"
    key = f"mw_{kind}_{item['id']}"
    threshold = ctx["threshold"]

    if kind == "task":
        proj = ctx["projects"].get(item.get("project_id"), {})
        parent_bit = ""
    else:
        parent = ctx["task_map"].get(item.get("task_id"), {})
        proj = ctx["projects"].get(parent.get("project_id"), {})
        parent_bit = (f"<span style='color:#999;font-size:11px'>in: "
                      f"{_esc(parent.get('name'))}</span>")

    label = proj.get("acronym") or proj.get("identifier") or proj.get("name") or ""
    status = item.get("status") or "Not started"
    name_style = TASK_NAME_STYLE if kind == "task" else SUBTASK_NAME_STYLE
    prefix = "" if kind == "task" else "› "

    with st.container(border=True):
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
            f"{_proj_chip(label)}"
            f"<span style='{name_style}'>{prefix}{_esc(item.get('name'))}</span>"
            f"{_stale_bit(item, threshold)}"
            f"<span style='margin-left:auto'>{_deadline_bit(item.get('deadline'), threshold)}</span>"
            f"</div>" + (f"<div style='margin-top:2px'>{parent_bit}</div>" if parent_bit else ""),
            unsafe_allow_html=True,
        )

        c_status, c_note, c_save = st.columns([1.6, 5.4, 1.2])
        with c_status:
            opts = _STATUSES if status in _STATUSES else _STATUSES + [status]
            new_status = st.selectbox(
                "Stato", opts, index=opts.index(status),
                key=f"{key}_st", label_visibility="collapsed",
            )
        with c_note:
            note = st.text_input(
                "Aggiornamento", key=f"{key}_note", label_visibility="collapsed",
                placeholder="A che punto sei? (una riga — resta nelle note, con la data)",
            )
        with c_save:
            clicked = st.button("💾", key=f"{key}_save", use_container_width=True,
                                help="Salva stato e nota")

        if clicked:
            if new_status == status and not (note or "").strip():
                st.warning("Niente da salvare: cambia lo stato o scrivi una riga.")
            else:
                ok, err = quick_update(
                    table, item["id"],
                    status=new_status if new_status != status else None,
                    note_append=note,
                    current_notes=item.get("notes") or "",
                    project_id=proj.get("id"),
                    old_status=status,
                    user_email=ctx["email"],
                )
                if ok:
                    st.session_state[f"{key}_note"] = ""
                    st.toast(f"Aggiornato: {item.get('name','')[:40]}")
                    st.rerun()
                else:
                    st.error(f"Errore: {err}")


def show_my_week():
    st.title("🎯 La mia settimana")
    st.caption(
        "Tutto ciò di cui sei responsabile, aggiornabile qui senza aprire nulla. "
        "Una riga su dove sei vale più di un cambio di stato."
    )

    email = st.session_state.get("user_email")
    if not email:
        st.error("Devi effettuare l'accesso.")
        return

    threshold = stale_threshold()
    data = get_my_week(email)
    items = [{**t, "_kind": "task"} for t in data["tasks"]] + \
            [{**s, "_kind": "subtask"} for s in data["subtasks"]]

    if not items:
        st.success("✅ Non hai task attivi assegnati. Buona settimana!")
        return

    ctx = {
        "projects": data["projects"], "task_map": data["task_map"],
        "threshold": threshold, "email": email,
    }

    # ── Focus row ────────────────────────────────────────────────────────────
    today = datetime.date.today()
    overdue = [i for i in items if (d := _parse(i.get("deadline"))) and d < today]
    blocked = [i for i in items if (i.get("status") or "") == "Blocked"]
    stale = [i for i in items if (dd := days_since_update(i)) is not None and dd >= threshold]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Da aggiornare", len(items))
    m2.metric("🔴 Scaduti", len(overdue))
    m3.metric("🚫 Bloccati", len(blocked))
    m4.metric(f"⏳ Fermi ≥{threshold}g", len(stale))

    if stale:
        st.info(
            f"**{len(stale)}** elementi non vengono aggiornati da almeno {threshold} giorni. "
            "Per i task lunghi basta una riga su dove sei: è il segnale che conta più della scadenza."
        )

    # ── Ordering: what needs a word first ────────────────────────────────────
    def order(i):
        d = _parse(i.get("deadline")) or datetime.date(9999, 12, 31)
        stale_d = days_since_update(i) or 0
        blocked_first = 0 if (i.get("status") == "Blocked") else 1
        late = 0 if d < today else 1
        return (blocked_first, late, -stale_d, d,
                PRIORITY_ORDER.get((i.get("priority") or "none").lower(), 4))

    only_stale = st.checkbox(
        f"Mostra solo quelli fermi da ≥{threshold} giorni", value=False, key="mw_only_stale"
    )
    shown = [i for i in items if i in stale] if only_stale else items
    shown = sorted(shown, key=order)

    st.divider()
    for n, item in enumerate(shown):
        _row(item, item["_kind"], ctx, n)

    # ── Your own trend, as feedback rather than judgement ─────────────────────
    st.divider()
    stats = get_activity_stats(user_email=email, weeks=8)
    if not stats.get("available"):
        st.caption(
            "ℹ️ L'andamento personale sarà disponibile dopo la migration "
            "'Status history & trend'."
        )
        return
    if not stats["by_week"]:
        st.caption("Nessun aggiornamento registrato nelle ultime 8 settimane.")
        return

    import pandas as pd
    weeks = sorted(set(stats["by_week"]) | set(stats["completed_by_week"]))
    df = pd.DataFrame({
        "Aggiornamenti": [stats["by_week"].get(w, 0) for w in weeks],
        "Completati": [stats["completed_by_week"].get(w, 0) for w in weeks],
    }, index=weeks)
    done = sum(stats["completed_by_week"].values())
    st.markdown(
        f"**Il tuo andamento** — {stats['total']} aggiornamenti e "
        f"**{done} task completati** nelle ultime 8 settimane."
    )
    st.bar_chart(df, height=200)
