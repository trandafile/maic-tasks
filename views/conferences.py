"""views/conferences.py — Conference calendar.

Master list of target conferences with their key dates (submission,
notification, camera-ready, event). Data lives in the ``conferences`` table
(see CONFERENCES_MIGRATION_SQL). Entries can be added by hand or bulk-imported
from JSON — and the view generates a ready-to-paste Gemini deep-research prompt
whose output matches the import schema.

Editing (add / edit / archive / import) is admin-only; everyone can view the
calendar and the deadlines, since conferences are shared reference data.
"""

from __future__ import annotations

import datetime
import html
import json

import streamlit as st

from db import (
    get_conferences,
    upsert_conference,
    import_conferences_json,
    set_conference_archived,
    CONFERENCE_FIELDS,
    CONFERENCES_MIGRATION_SQL,
)
from utils.helpers import fmt_date

try:
    from streamlit_calendar import calendar as _st_calendar
except Exception:  # streamlit_calendar always in requirements, but be defensive
    _st_calendar = None


# Colours for the different conference milestones shown on the calendar.
_MILESTONE_COLOUR = {
    "submission":    "#C62828",  # red — the one that really matters
    "notification":  "#1565C0",
    "camera_ready":  "#6A1B9A",
    "event":         "#2E7D32",
}

# The lab research areas seeded into the Gemini prompt (editable in the UI).
_DEFAULT_TOPICS = (
    "RF/microwave/mm-wave integrated circuits and antennas; MMIC (SiGe BiCMOS, "
    "GaN, FD-SOI CMOS); antenna-on-chip (AoC) and antenna-in-package (AiP); "
    "phased arrays, transmitarrays, reflectarrays; K/Ka/E/W/D-band front-ends; "
    "5G/6G, SatCom and radar front-ends"
)


def _iso(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _safe_ics_text(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


# ── Gemini deep-research prompt ────────────────────────────────────────────────

def _json_schema_hint() -> str:
    return json.dumps(
        [
            {
                "name": "IEEE International Microwave Symposium",
                "acronym": "IMS",
                "year": 2026,
                "location": "San Francisco, CA, USA",
                "url": "https://ims-ieee.org",
                "topics": "microwave, RF, MMIC, antennas",
                "rank": "A",
                "submission_deadline": "2026-01-15",
                "notification_date": "2026-03-20",
                "camera_ready_date": "2026-04-30",
                "start_date": "2026-06-14",
                "end_date": "2026-06-19",
                "notes": "Flagship microwave conference.",
            }
        ],
        indent=2,
    )


def _build_gemini_prompt(topics: str, horizon_months: int) -> str:
    today = datetime.date.today()
    return (
        "You are a research assistant for the MAIC Lab (University of Calabria, DIMES). "
        "Perform a deep web search and compile a calendar of upcoming academic "
        "conferences relevant to our research areas.\n\n"
        f"RESEARCH AREAS:\n{topics.strip()}\n\n"
        "REQUIREMENTS:\n"
        f"- Only conferences whose paper submission deadline is between {today.isoformat()} "
        f"and {(today + datetime.timedelta(days=30 * horizon_months)).isoformat()} "
        f"(next {horizon_months} months).\n"
        "- Prefer IEEE/EuMA/URSI and other reputable venues; include the venue rank "
        "(CORE/GGS/Qualis) when known.\n"
        "- Verify every date against the official conference website; do not invent dates. "
        "If a date is unknown, use null.\n"
        "- Use ISO dates (YYYY-MM-DD).\n\n"
        "OUTPUT:\n"
        "Return ONLY a valid JSON array (no prose, no markdown fences) where each "
        "element has exactly these keys:\n"
        '["name", "acronym", "year", "location", "url", "topics", "rank", '
        '"submission_deadline", "notification_date", "camera_ready_date", '
        '"start_date", "end_date", "notes"].\n\n'
        "EXAMPLE (format only — replace with real, verified data):\n"
        f"{_json_schema_hint()}\n"
    )


# ── Add / edit form ────────────────────────────────────────────────────────────

def _conference_form(existing: dict | None, key_suffix: str) -> None:
    is_edit = existing is not None
    ex = existing or {}
    with st.form(f"conf_form_{key_suffix}"):
        c1, c2, c3 = st.columns([3, 1.4, 1])
        with c1:
            name = st.text_input("Name*", value=ex.get("name", ""))
        with c2:
            acronym = st.text_input("Acronym", value=ex.get("acronym", "") or "")
        with c3:
            year = st.number_input(
                "Year", min_value=2000, max_value=2100, step=1,
                value=int(ex.get("year")) if ex.get("year") else datetime.date.today().year,
            )
        c4, c5 = st.columns([2, 1])
        with c4:
            location = st.text_input("Location", value=ex.get("location", "") or "")
        with c5:
            rank = st.text_input("Rank", value=ex.get("rank", "") or "", help="e.g. CORE A / B, Q1…")
        url = st.text_input("URL", value=ex.get("url", "") or "")
        topics = st.text_input("Topics", value=ex.get("topics", "") or "")

        d1, d2, d3 = st.columns(3)
        with d1:
            submission = st.date_input(
                "Submission deadline", value=_iso(ex.get("submission_deadline")),
                format="DD/MM/YYYY",
            )
        with d2:
            notification = st.date_input(
                "Notification", value=_iso(ex.get("notification_date")),
                format="DD/MM/YYYY",
            )
        with d3:
            camera = st.date_input(
                "Camera-ready", value=_iso(ex.get("camera_ready_date")),
                format="DD/MM/YYYY",
            )
        e1, e2 = st.columns(2)
        with e1:
            start = st.date_input("Event start", value=_iso(ex.get("start_date")), format="DD/MM/YYYY")
        with e2:
            end = st.date_input("Event end", value=_iso(ex.get("end_date")), format="DD/MM/YYYY")
        notes = st.text_area("Notes", value=ex.get("notes", "") or "", height=80)

        submitted = st.form_submit_button(
            "💾 Save conference" if is_edit else "➕ Add conference", type="primary"
        )
        if submitted:
            payload = {
                "name": name,
                "acronym": acronym,
                "year": int(year) if year else None,
                "location": location,
                "url": url,
                "topics": topics,
                "rank": rank,
                "submission_deadline": submission.isoformat() if submission else None,
                "notification_date": notification.isoformat() if notification else None,
                "camera_ready_date": camera.isoformat() if camera else None,
                "start_date": start.isoformat() if start else None,
                "end_date": end.isoformat() if end else None,
                "notes": notes,
            }
            ok, err = upsert_conference(payload, conference_id=ex.get("id") if is_edit else None)
            if ok:
                st.success("Saved." if is_edit else "Conference added.")
                st.session_state.pop(f"_conf_edit_{ex.get('id')}", None)
                st.rerun()
            else:
                st.error(f"Error: {err}")


# ── Calendar + timeline ────────────────────────────────────────────────────────

def _build_events(conferences: list[dict], milestones: set[str]) -> list[dict]:
    events: list[dict] = []
    for c in conferences:
        label = c.get("acronym") or c.get("name") or "Conference"
        pairs = [
            ("submission", "submission_deadline", "📝 Submission"),
            ("notification", "notification_date", "📣 Notification"),
            ("camera_ready", "camera_ready_date", "🖨️ Camera-ready"),
            ("event", "start_date", "🎤 Event"),
        ]
        for kind, field, prefix in pairs:
            if kind not in milestones:
                continue
            dstr = _iso(c.get(field))
            if not dstr:
                continue
            end_field = c.get("end_date") if kind == "event" else None
            ev = {
                "id": f"conf_{c.get('id')}_{kind}",
                "title": f"{prefix}: {label}",
                "start": dstr.isoformat(),
                "allDay": True,
                "color": _MILESTONE_COLOUR[kind],
                "extendedProps": {
                    "kind": kind,
                    "conference": c.get("name"),
                    "location": c.get("location"),
                    "url": c.get("url"),
                },
            }
            if kind == "event" and _iso(end_field):
                # FullCalendar end is exclusive → +1 day to include the last day.
                ev["end"] = (_iso(end_field) + datetime.timedelta(days=1)).isoformat()
            events.append(ev)
    return events


def _build_ics(conferences: list[dict]) -> bytes:
    now = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//MAIC LAB//Conference Calendar//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    ]
    for c in conferences:
        label = c.get("acronym") or c.get("name") or "Conference"
        for field, tag in (
            ("submission_deadline", "Submission deadline"),
            ("notification_date", "Notification"),
            ("camera_ready_date", "Camera-ready"),
            ("start_date", "Event start"),
        ):
            d = _iso(c.get(field))
            if not d:
                continue
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:conf-{c.get('id')}-{field}@maic-lab",
                f"DTSTAMP:{now}",
                f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                f"SUMMARY:{_safe_ics_text(f'{tag}: {label}')}",
                f"DESCRIPTION:{_safe_ics_text(c.get('name') or '')}",
                "END:VEVENT",
            ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")


def _conferences_to_json(conferences: list[dict]) -> str:
    out = []
    for c in conferences:
        out.append({k: c.get(k) for k in CONFERENCE_FIELDS})
    return json.dumps(out, indent=2, ensure_ascii=False)


# ── Main view ──────────────────────────────────────────────────────────────────

def show_conference_calendar() -> None:
    st.title("🗓️ Conference Calendar")

    is_admin = st.session_state.get("user_role") == "admin"

    conferences = get_conferences(show_archived=False)
    if conferences is None:
        st.warning(
            "The **conferences** table does not exist yet. Run the migration below "
            "in the Supabase SQL Editor (also available under Admin → SQL Migrations)."
        )
        st.code(CONFERENCES_MIGRATION_SQL, language="sql")
        return

    # ── Admin tools: add / import / prompt ────────────────────────────────────
    if is_admin:
        with st.expander("➕ Add a conference", expanded=False):
            _conference_form(existing=None, key_suffix="new")

        with st.expander("📥 Import from JSON", expanded=False):
            st.caption(
                "Paste a JSON array of conferences (or upload a .json file). Missing "
                "keys are allowed; each entry needs at least a `name`."
            )
            up = st.file_uploader("Upload .json", type=["json"], key="conf_json_up")
            pasted = st.text_area("…or paste JSON here", height=160, key="conf_json_paste")
            if st.button("Import conferences", key="conf_import_btn"):
                raw = None
                if up is not None:
                    try:
                        raw = up.getvalue().decode("utf-8")
                    except Exception as ex:
                        st.error(f"Could not read file: {ex}")
                if raw is None:
                    raw = pasted
                if not (raw or "").strip():
                    st.error("Provide a JSON file or paste JSON text.")
                else:
                    try:
                        data = json.loads(raw)
                    except Exception as ex:
                        st.error(f"Invalid JSON: {ex}")
                    else:
                        inserted, skipped, errors = import_conferences_json(data)
                        if inserted:
                            st.success(f"Imported {inserted} conference(s). Skipped {skipped}.")
                        for e in errors[:8]:
                            st.warning(e)
                        if inserted:
                            st.rerun()

        with st.expander("🔍 Generate Gemini deep-research prompt", expanded=False):
            st.caption(
                "Copy this prompt into Gemini (deep research). Paste the JSON it "
                "returns into *Import from JSON* above."
            )
            topics = st.text_area("Research areas", value=_DEFAULT_TOPICS, height=90, key="conf_prompt_topics")
            horizon = st.slider("Horizon (months)", 3, 24, 12, key="conf_prompt_horizon")
            prompt = _build_gemini_prompt(topics, horizon)
            st.code(prompt, language="text")
            st.download_button(
                "⬇️ Download prompt (.txt)", data=prompt,
                file_name="gemini_conference_prompt.txt", mime="text/plain",
                key="conf_prompt_dl",
            )

    if not conferences:
        st.info(
            "No conferences yet."
            + ("" if is_admin else " Ask an administrator to add or import some.")
        )
        return

    # ── Milestone filter + exports ────────────────────────────────────────────
    fc1, fc2 = st.columns([3, 2])
    with fc1:
        milestone_labels = {
            "submission": "📝 Submission",
            "notification": "📣 Notification",
            "camera_ready": "🖨️ Camera-ready",
            "event": "🎤 Event dates",
        }
        chosen = st.multiselect(
            "Milestones on calendar",
            options=list(milestone_labels.keys()),
            default=["submission", "event"],
            format_func=lambda k: milestone_labels[k],
            key="conf_milestones",
        )
    with fc2:
        st.download_button(
            "⬇️ Export .ics", data=_build_ics(conferences),
            file_name=f"conferences_{datetime.date.today().strftime('%Y%m%d')}.ics",
            mime="text/calendar", key="conf_ics",
        )
        st.download_button(
            "⬇️ Export JSON", data=_conferences_to_json(conferences),
            file_name=f"conferences_{datetime.date.today().strftime('%Y%m%d')}.json",
            mime="application/json", key="conf_json_export",
        )

    events = _build_events(conferences, set(chosen))
    if _st_calendar is not None and events:
        cal_opts = {
            "initialView": "dayGridMonth",
            "height": 680,
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,listYear,multiMonthYear",
            },
        }
        _st_calendar(events=events, options=cal_opts, key="conf_calendar")

    # ── Upcoming submission deadlines (highlighted list) ──────────────────────
    st.subheader("Upcoming submission deadlines")
    today = datetime.date.today()
    with_sub = [
        (c, _iso(c.get("submission_deadline")))
        for c in conferences
        if _iso(c.get("submission_deadline"))
    ]
    with_sub.sort(key=lambda x: x[1])

    if not with_sub:
        st.caption("No submission deadlines recorded.")
    for c, sub in with_sub:
        days = (sub - today).days
        if days < 0:
            badge = "<span style='background:#ECEFF1;color:#607D8B;padding:1px 8px;border-radius:4px;font-size:11px'>passed</span>"
        elif days <= 30:
            badge = f"<span style='background:#FDECEC;color:#C62828;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:700'>in {days}d</span>"
        elif days <= 90:
            badge = f"<span style='background:#FFF3E0;color:#E65100;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:700'>in {days}d</span>"
        else:
            badge = f"<span style='background:#E8F5E9;color:#2E7D32;padding:1px 8px;border-radius:4px;font-size:11px'>in {days}d</span>"

        label = c.get("acronym") or c.get("name")
        rank = f" · rank {html.escape(str(c.get('rank')))}" if c.get("rank") else ""
        loc = f" · {html.escape(str(c.get('location')))}" if c.get("location") else ""
        url = c.get("url")
        title_html = html.escape(str(label))
        if url:
            title_html = f"<a href='{html.escape(str(url))}' target='_blank'>{title_html}</a>"

        row_html = (
            f"<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:3px 0'>"
            f"<span style='font-weight:700'>{title_html}</span>"
            f"<span style='color:#555;font-size:12px'>submission {fmt_date(sub.isoformat())}{rank}{loc}</span>"
            f"{badge}</div>"
        )

        if not is_admin:
            st.markdown(row_html, unsafe_allow_html=True)
            continue

        row_l, row_r = st.columns([8, 1.6])
        with row_l:
            st.markdown(row_html, unsafe_allow_html=True)
        with row_r:
            edit_key = f"_conf_edit_{c.get('id')}"
            b1, b2 = st.columns(2)
            with b1:
                if st.button("✏️", key=f"conf_edit_btn_{c.get('id')}", help="Edit"):
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                    st.rerun()
            with b2:
                if st.button("🗄️", key=f"conf_arch_btn_{c.get('id')}", help="Archive"):
                    set_conference_archived(c.get("id"), True)
                    st.rerun()

        if st.session_state.get(f"_conf_edit_{c.get('id')}"):
            _conference_form(existing=c, key_suffix=str(c.get("id")))
