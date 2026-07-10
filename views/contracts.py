"""views/contracts.py — Admin: contracts, reporting metadata, timesheet rows.

Three tabs:
  1. Contracts        — PhD students and contractors (period, project, hours).
  2. Project metadata — CUP / soggetto attuatore / tipo, printed on timesheets.
  3. Timesheet rows   — the configurable activity lines of each project.

Only contractors ('contract') fill monthly timesheets; PhD contracts just track
the start/end of the doctorate.
"""

from __future__ import annotations

import datetime
import html

import streamlit as st

from core.supabase_client import supabase
from db import (
    get_contracts, upsert_contract, delete_contract,
    get_project_activities, upsert_project_activity, delete_project_activity,
    CONTRACTS_MIGRATION_SQL,
)
from utils.helpers import fmt_date


def _parse(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _load_support():
    try:
        users = supabase.table("users").select(
            "email, name, fiscal_code, is_phd_student"
        ).eq("is_approved", True).order("name").execute().data or []
    except Exception:
        # fiscal_code column may not exist yet (migration not run)
        users = supabase.table("users").select("email, name").eq(
            "is_approved", True
        ).order("name").execute().data or []
    projects = supabase.table("projects").select("*").eq(
        "is_archived", False
    ).order("name").execute().data or []
    return users, projects


def _proj_label(p: dict) -> str:
    return f"{p.get('acronym') or p.get('identifier') or ''} — {p.get('name')}".strip(" —")


# ── Tab 1: contracts ──────────────────────────────────────────────────────────

def _contract_form(existing: dict | None, users: list, projects: list, key: str):
    ex = existing or {}
    is_edit = existing is not None

    user_opts = {f"{u['name']} ({u['email']})": u["email"] for u in users}
    proj_opts = {"— none —": None}
    proj_opts.update({_proj_label(p): p["id"] for p in projects})

    with st.form(f"contract_form_{key}"):
        c1, c2 = st.columns([2, 1])
        with c1:
            cur_user = next((k for k, v in user_opts.items() if v == ex.get("user_email")), None)
            u_label = st.selectbox(
                "Person*", list(user_opts.keys()),
                index=list(user_opts).index(cur_user) if cur_user else 0,
            )
        with c2:
            ctype = st.selectbox(
                "Type*", ["contract", "phd"],
                index=0 if ex.get("contract_type", "contract") == "contract" else 1,
                format_func=lambda t: "Contractor (timesheet)" if t == "contract" else "PhD student",
            )

        cur_proj = next((k for k, v in proj_opts.items() if v == ex.get("project_id")), "— none —")
        p_label = st.selectbox(
            "Project", list(proj_opts.keys()),
            index=list(proj_opts).index(cur_proj),
            help="Required for contractors: it drives the timesheet (CUP, activity rows).",
        )

        d1, d2 = st.columns(2)
        with d1:
            start = st.date_input("Start date", value=_parse(ex.get("start_date")), format="DD/MM/YYYY")
        with d2:
            end = st.date_input("End date", value=_parse(ex.get("end_date")), format="DD/MM/YYYY")

        h1, h2, h3 = st.columns(3)
        with h1:
            annual = st.number_input(
                "Annual hours", min_value=0, max_value=5000, step=50,
                value=int(ex.get("annual_hours") or 1500),
                help="'Monte ore lavorative annuo previsto' printed on the timesheet.",
            )
        with h2:
            daily = st.number_input(
                "Daily hours", min_value=0.0, max_value=24.0, step=0.5,
                value=float(ex.get("daily_hours") or 8),
                help="Autofill books these hours on each working day of the contract.",
            )
        with h3:
            cost = st.number_input(
                "Hourly cost (€)", min_value=0.0, step=1.0,
                value=float(ex.get("hourly_cost") or 0),
            )

        fiscal = st.text_input(
            "Fiscal code (of the person)",
            value=next((u.get("fiscal_code") or "" for u in users if u["email"] == user_opts[u_label]), ""),
            help="Stored on the user; printed in the timesheet header.",
        )
        active = st.checkbox("Active", value=bool(ex.get("is_active", True)))
        notes = st.text_area("Notes", value=ex.get("notes") or "", height=70)

        if st.form_submit_button("💾 Save contract" if is_edit else "➕ Add contract", type="primary"):
            email = user_opts[u_label]
            pid = proj_opts[p_label]
            if ctype == "contract" and not pid:
                st.error("A contractor needs a project (the timesheet depends on it).")
                return
            payload = {
                "user_email": email,
                "contract_type": ctype,
                "project_id": pid,
                "start_date": start.isoformat() if start else None,
                "end_date": end.isoformat() if end else None,
                "annual_hours": int(annual),
                "daily_hours": float(daily),
                "hourly_cost": float(cost) if cost else None,
                "is_active": bool(active),
                "notes": notes or None,
            }
            ok, err = upsert_contract(payload, contract_id=ex.get("id") if is_edit else None)
            if not ok:
                st.error(f"Error: {err}")
                return
            if fiscal.strip():
                try:
                    supabase.table("users").update(
                        {"fiscal_code": fiscal.strip().upper()}
                    ).eq("email", email).execute()
                except Exception as ex2:
                    st.warning(f"Contract saved, but fiscal code not stored: {ex2}")
            st.success("Saved.")
            st.session_state.pop(f"_contract_edit_{ex.get('id')}", None)
            st.rerun()


def _tab_contracts(users: list, projects: list):
    rows = get_contracts()
    if rows is None:
        st.warning("The **contracts** table does not exist yet. Run the migration below.")
        st.code(CONTRACTS_MIGRATION_SQL, language="sql")
        return

    with st.expander("➕ Add a contract", expanded=not rows):
        _contract_form(None, users, projects, key="new")

    if not rows:
        st.info("No contracts yet.")
        return

    name_by_email = {u["email"]: u["name"] for u in users}
    proj_by_id = {p["id"]: p for p in projects}
    today = datetime.date.today()

    st.caption(f"{len(rows)} contract(s).")
    for c in rows:
        cid = c["id"]
        person = name_by_email.get(c["user_email"], c["user_email"])
        proj = proj_by_id.get(c.get("project_id"), {})
        is_contractor = c.get("contract_type") == "contract"
        end = _parse(c.get("end_date"))
        start = _parse(c.get("start_date"))

        if not c.get("is_active"):
            state, colour = "inactive", "#9E9E9E"
        elif end and end < today:
            state, colour = "expired", "#C62828"
        elif start and start > today:
            state, colour = "not started", "#E65100"
        elif end and (end - today).days <= 30:
            state, colour = f"ends in {(end - today).days}d", "#E65100"
        else:
            state, colour = "active", "#2E7D32"

        kind = "🧾 Contractor" if is_contractor else "🎓 PhD"
        proj_txt = html.escape(_proj_label(proj)) if proj else "no project"
        daily_txt = f" · {c.get('daily_hours')}h/day" if is_contractor else ""

        info, b_edit, b_del = st.columns([7, 1.2, 1.2])
        with info:
            st.markdown(
                f"<div style='padding:4px 0'>"
                f"<span style='font-weight:700;font-size:14px'>{html.escape(person)}</span> "
                f"<span style='font-size:12px;color:#555'>· {kind}</span> "
                f"<span style='background:{colour}22;color:{colour};border-radius:4px;"
                f"padding:1px 8px;font-size:11px;font-weight:700'>{state}</span><br>"
                f"<span style='font-size:12px;color:#666'>"
                f"{proj_txt} · {fmt_date(c.get('start_date'))} → {fmt_date(c.get('end_date'))}"
                f"{daily_txt}</span></div>",
                unsafe_allow_html=True,
            )
        with b_edit:
            ek = f"_contract_edit_{cid}"
            if st.button("✏️", key=f"c_edit_{cid}", use_container_width=True):
                st.session_state[ek] = not st.session_state.get(ek, False)
                st.rerun()
        with b_del:
            ck = f"_contract_del_{cid}"
            if st.session_state.get(ck):
                if st.button("✅", key=f"c_delok_{cid}", type="primary", use_container_width=True):
                    delete_contract(cid)
                    st.session_state.pop(ck, None)
                    st.rerun()
            else:
                if st.button("🗑️", key=f"c_del_{cid}", use_container_width=True):
                    st.session_state[ck] = True
                    st.rerun()
        if st.session_state.get(f"_contract_del_{cid}"):
            st.caption(f"⚠️ Delete the contract of **{person}**? Click ✅ to confirm.")
        if st.session_state.get(f"_contract_edit_{cid}"):
            _contract_form(c, users, projects, key=str(cid))


# ── Tab 2: project reporting metadata ─────────────────────────────────────────

def _tab_project_metadata(projects: list):
    if not projects:
        st.info("No active projects.")
        return
    labels = {_proj_label(p): p for p in projects}
    p = labels[st.selectbox("Project", list(labels.keys()), key="cm_proj")]

    with st.form(f"proj_meta_{p['id']}"):
        cup = st.text_input("CUP", value=p.get("cup") or "")
        soggetto = st.text_input("Soggetto attuatore", value=p.get("soggetto_attuatore") or "")
        ptype = st.text_input(
            "Tipo del progetto", value=p.get("project_type") or "",
            help="e.g. 'Ricerca Industriale e Sviluppo Sperimentale'",
        )
        st.caption(f"The timesheet prints **{p.get('name')}** as 'Titolo del progetto'.")
        if st.form_submit_button("💾 Save metadata", type="primary"):
            try:
                supabase.table("projects").update({
                    "cup": cup.strip() or None,
                    "soggetto_attuatore": soggetto.strip() or None,
                    "project_type": ptype.strip() or None,
                }).eq("id", p["id"]).execute()
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


# ── Tab 3: timesheet activity rows ────────────────────────────────────────────

_DEFAULT_ROWS = [
    ("Ricerca Industriale", True, 70),
    ("Sviluppo sperimentale", True, 30),
    ("Altri progetti", False, 0),
    ("Attività didattica", False, 0),
    ("Altro", False, 0),
]


def _tab_activities(projects: list):
    if not projects:
        st.info("No active projects.")
        return
    labels = {_proj_label(p): p for p in projects}
    p = labels[st.selectbox("Project", list(labels.keys()), key="ca_proj")]
    pid = p["id"]
    cup = (p.get("cup") or "").strip()

    acts = get_project_activities(pid)

    st.caption(
        "Rows printed on the timesheet, in order. Rows flagged **imputable** get "
        "` - <CUP>` appended to their label. **Share %** drives the autofill split "
        "of the daily hours; rows at 0% are left empty for manual entry."
    )

    if not acts:
        st.info("This project has no timesheet rows yet.")
        if st.button("Create the standard MIUR rows", type="primary", key="ca_seed"):
            for i, (name, imputable, share) in enumerate(_DEFAULT_ROWS):
                upsert_project_activity({
                    "project_id": pid, "name": name, "sort_order": i,
                    "counts_to_project": imputable, "default_share_pct": share,
                })
            st.rerun()

    total_share = sum(float(a.get("default_share_pct") or 0) for a in acts)
    if acts:
        if abs(total_share - 100) > 0.01:
            st.warning(
                f"Shares add up to **{total_share:g}%**, not 100%. Autofill will "
                "normalise them, but the split may not be what you expect."
            )
        else:
            st.success("Shares add up to 100%.")

    for a in acts:
        aid = a["id"]
        with st.form(f"act_{aid}"):
            c1, c2, c3, c4, c5 = st.columns([3.5, 1.2, 1.4, 1, 1])
            with c1:
                name = st.text_input("Name", value=a.get("name") or "", key=f"an_{aid}")
            with c2:
                order = st.number_input("Order", value=int(a.get("sort_order") or 0), step=1, key=f"ao_{aid}")
            with c3:
                share = st.number_input(
                    "Share %", value=float(a.get("default_share_pct") or 0),
                    min_value=0.0, max_value=100.0, step=5.0, key=f"as_{aid}",
                )
            with c4:
                imputable = st.checkbox("Imputable", value=bool(a.get("counts_to_project")), key=f"ai_{aid}")
            with c5:
                st.caption("")
                saved = st.form_submit_button("💾")
        if saved:
            ok, err = upsert_project_activity({
                "project_id": pid, "name": name, "sort_order": int(order),
                "counts_to_project": bool(imputable), "default_share_pct": float(share),
            }, activity_id=aid)
            if ok:
                st.rerun()
            else:
                st.error(err)
        preview = f"{name} - {cup}" if imputable and cup else name
        d1, d2 = st.columns([6, 1])
        d1.caption(f"Prints as: **{preview}**")
        if d2.button("🗑️", key=f"ad_{aid}", help="Delete row"):
            delete_project_activity(aid)
            st.rerun()

    with st.expander("➕ Add a row"):
        with st.form(f"new_act_{pid}"):
            n1, n2, n3, n4 = st.columns([3.5, 1.2, 1.4, 1])
            with n1:
                nname = st.text_input("Name")
            with n2:
                norder = st.number_input("Order", value=len(acts), step=1)
            with n3:
                nshare = st.number_input("Share %", value=0.0, min_value=0.0, max_value=100.0, step=5.0)
            with n4:
                nimp = st.checkbox("Imputable", value=True)
            if st.form_submit_button("Add", type="primary"):
                ok, err = upsert_project_activity({
                    "project_id": pid, "name": nname, "sort_order": int(norder),
                    "counts_to_project": bool(nimp), "default_share_pct": float(nshare),
                })
                if ok:
                    st.rerun()
                else:
                    st.error(err)


# ── Entry point ───────────────────────────────────────────────────────────────

def show_contracts():
    st.title("🧾 Contracts")

    if st.session_state.get("user_role") != "admin":
        st.error("Admins only.")
        return

    try:
        users, projects = _load_support()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return

    t1, t2, t3 = st.tabs(["📄 Contracts", "🏷️ Project metadata", "🧮 Timesheet rows"])
    with t1:
        _tab_contracts(users, projects)
    with t2:
        _tab_project_metadata(projects)
    with t3:
        _tab_activities(projects)
