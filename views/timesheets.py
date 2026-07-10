"""views/timesheets.py — Monthly timesheet for contractors.

A contractor picks a month, hits **Autofill** (daily hours booked on every
working day inside the contract period, split by the project's activity
shares), adjusts the grid by hand, saves, and downloads the Excel in the MIUR
format. Signing and sending are done outside the app.

Admins can open anybody's timesheet.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from core.supabase_client import supabase
from db import (
    get_contracts, get_timesheet_contracts, get_project_activities,
    get_timesheet, save_timesheet, contract_covers,
    CONTRACTS_MIGRATION_SQL,
)
from utils.timesheet import (
    MONTHS_IT, days_in_month, is_working_day, autofill_grid,
    grid_cell, day_total, month_total, row_total,
    activity_label, build_timesheet_excel, excel_filename,
)

_TOTAL_COL = "TOT"


def _parse(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _grid_to_df(activities: list[dict], grid: dict, year: int, month: int, cup: str) -> pd.DataFrame:
    n = days_in_month(year, month)
    data = {}
    for a in activities:
        data[activity_label(a, cup)] = [grid_cell(grid, a["id"], d) for d in range(1, n + 1)]
    df = pd.DataFrame.from_dict(data, orient="index", columns=[str(d) for d in range(1, n + 1)])
    return df


def _df_to_grid(df: pd.DataFrame, activities: list[dict], cup: str) -> dict:
    """Map the edited dataframe back to {activity_id: {day: hours}} by row order."""
    grid: dict[str, dict[str, float]] = {}
    for a, (_, row) in zip(activities, df.iterrows()):
        cells = {}
        for day_col, value in row.items():
            if day_col == _TOTAL_COL:
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if v > 0:
                cells[str(int(day_col))] = int(v) if float(v).is_integer() else round(v, 2)
        grid[str(a["id"])] = cells
    return grid


def _render_editor(activities, grid, year, month, cup, can_edit: bool) -> pd.DataFrame:
    df = _grid_to_df(activities, grid, year, month, cup)
    n = days_in_month(year, month)

    col_cfg = {}
    for d in range(1, n + 1):
        wd = is_working_day(datetime.date(year, month, d))
        col_cfg[str(d)] = st.column_config.NumberColumn(
            label=str(d), min_value=0.0, max_value=24.0, step=0.5, format="%g",
            help=None if wd else "Weekend",
        )

    if not can_edit:
        st.dataframe(df, use_container_width=True, column_config=col_cfg)
        return df

    return st.data_editor(
        df,
        use_container_width=True,
        column_config=col_cfg,
        num_rows="fixed",
        key=f"ts_editor_{year}_{month}",
    )


def show_timesheets():
    st.title("🧾 Time Sheets")

    email = st.session_state.get("user_email")
    is_admin = st.session_state.get("user_role") == "admin"
    if not email:
        st.error("You must be logged in.")
        return

    if get_contracts(user_email=email) is None:
        st.warning("The **contracts / timesheets** tables do not exist yet. Run the migration below.")
        st.code(CONTRACTS_MIGRATION_SQL, language="sql")
        return

    # ── Whose timesheet? ──────────────────────────────────────────────────────
    target_email = email
    if is_admin:
        try:
            users = supabase.table("users").select("email, name").eq(
                "is_approved", True
            ).order("name").execute().data or []
        except Exception:
            users = []
        opts = {f"{u['name']} ({u['email']})": u["email"] for u in users}
        me_label = next((k for k, v in opts.items() if v == email), None)
        if opts:
            choice = st.selectbox(
                "Person", list(opts.keys()),
                index=list(opts).index(me_label) if me_label else 0,
            )
            target_email = opts[choice]

    contracts = get_timesheet_contracts(target_email)
    if not contracts:
        st.info(
            "No active contractor contract for this person, so there is no timesheet to fill. "
            + ("Add one under **Contracts**." if is_admin else "Ask an administrator if you expect one.")
        )
        return

    # ── Contract + period ─────────────────────────────────────────────────────
    try:
        projects = supabase.table("projects").select("*").execute().data or []
        users_rows = supabase.table("users").select("*").eq("email", target_email).execute().data or []
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return
    proj_by_id = {p["id"]: p for p in projects}
    user = users_rows[0] if users_rows else {"name": target_email, "fiscal_code": ""}

    c1, c2, c3 = st.columns([3, 1.2, 1.6])
    with c1:
        c_opts = {
            f"{proj_by_id.get(c['project_id'], {}).get('acronym') or 'Project'} "
            f"({c.get('start_date')} → {c.get('end_date') or '…'})": c
            for c in contracts
        }
        contract = c_opts[st.selectbox("Contract", list(c_opts.keys()), key="ts_contract")]
    today = datetime.date.today()
    with c2:
        year = st.number_input("Year", min_value=2000, max_value=2100, value=today.year, step=1)
    with c3:
        month = st.selectbox(
            "Month", list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: MONTHS_IT[m],
        )
    year, month = int(year), int(month)

    project = proj_by_id.get(contract["project_id"], {})
    cup = (project.get("cup") or "").strip()
    activities = get_project_activities(contract["project_id"])

    # ── Preconditions ─────────────────────────────────────────────────────────
    problems = []
    if not activities:
        problems.append("the project has no timesheet rows (Contracts → Timesheet rows)")
    if not cup:
        problems.append("the project has no CUP (Contracts → Project metadata)")
    if not (user.get("fiscal_code") or "").strip():
        problems.append("the person has no fiscal code (Contracts → edit the contract)")
    if problems:
        st.warning("Before generating a valid timesheet, fix: " + "; ".join(problems) + ".")
    if not activities:
        return

    n_days = days_in_month(year, month)
    first, last = datetime.date(year, month, 1), datetime.date(year, month, n_days)
    if not (contract_covers(contract, first) or contract_covers(contract, last)):
        st.error(
            f"{MONTHS_IT[month]} {year} falls entirely outside this contract "
            f"({contract.get('start_date')} → {contract.get('end_date') or '…'})."
        )
        return

    can_edit = is_admin or target_email == email

    # ── Load / autofill ───────────────────────────────────────────────────────
    ts_row = get_timesheet(target_email, contract["project_id"], year, month)
    state_key = f"_ts_grid_{target_email}_{contract['id']}_{year}_{month}"
    if state_key not in st.session_state:
        st.session_state[state_key] = (ts_row or {}).get("grid") or {}

    daily = float(contract.get("daily_hours") or 8)
    a1, a2, a3, a4 = st.columns([1.4, 1.2, 1.2, 3])
    with a1:
        if st.button("⚡ Autofill", disabled=not can_edit, use_container_width=True,
                     help=f"Book {daily:g}h on each working day inside the contract period."):
            st.session_state[state_key] = autofill_grid(
                activities, daily, year, month,
                contract.get("start_date"), contract.get("end_date"),
            )
            st.rerun()
    with a2:
        if st.button("🧹 Clear", disabled=not can_edit, use_container_width=True):
            st.session_state[state_key] = {}
            st.rerun()

    status = (ts_row or {}).get("status", "missing")
    badge = {"completed": "🟢 completed", "draft": "🟡 draft", "missing": "⚪ not started"}[status]
    with a4:
        st.caption(
            f"Status: **{badge}** · contract {contract.get('start_date')} → "
            f"{contract.get('end_date') or '…'} · {daily:g}h/working day"
        )

    grid = st.session_state[state_key]

    # ── Grid ──────────────────────────────────────────────────────────────────
    st.caption(
        "Hours per activity and day. Weekends and days outside the contract are left "
        "empty by autofill — you can still type into them if you really worked."
    )
    edited = _render_editor(activities, grid, year, month, cup, can_edit)
    if can_edit:
        grid = _df_to_grid(edited, activities, cup)
        st.session_state[state_key] = grid

    # ── Totals + sanity checks ────────────────────────────────────────────────
    totals = [day_total(grid, activities, d) for d in range(1, n_days + 1)]
    m_total = month_total(grid, activities, year, month)
    over = [d for d, t in zip(range(1, n_days + 1), totals) if t > 24]
    weekend_worked = [
        d for d in range(1, n_days + 1)
        if not is_working_day(datetime.date(year, month, d)) and totals[d - 1] > 0
    ]
    outside = [
        d for d in range(1, n_days + 1)
        if totals[d - 1] > 0 and not contract_covers(contract, datetime.date(year, month, d))
    ]

    t1, t2, t3 = st.columns(3)
    t1.metric("Month total (h)", f"{m_total:g}")
    t1.caption("Sum of every activity row.")
    t2.metric("Days booked", sum(1 for t in totals if t > 0))
    t3.metric("Annual hours", contract.get("annual_hours") or "—")

    if over:
        st.error(f"More than 24h booked on day(s): {', '.join(map(str, over))}.")
    if outside:
        st.warning(f"Hours booked outside the contract period on day(s): {', '.join(map(str, outside))}.")
    if weekend_worked:
        st.info(f"Weekend hours booked on day(s): {', '.join(map(str, weekend_worked))}.")

    with st.expander("Row totals"):
        for a in activities:
            st.write(f"- **{activity_label(a, cup)}**: {row_total(grid, a['id'], year, month):g} h")

    # ── Save + download ───────────────────────────────────────────────────────
    st.divider()
    s1, s2, s3 = st.columns([1.5, 1.8, 2])
    with s1:
        if st.button("💾 Save draft", disabled=not can_edit, use_container_width=True):
            ok, err = save_timesheet(target_email, contract["project_id"], year, month,
                                     grid, "draft", email)
            st.success("Draft saved.") if ok else st.error(f"Save failed: {err}")
    with s2:
        if st.button("✅ Mark as completed", type="primary",
                     disabled=(not can_edit) or bool(over), use_container_width=True):
            ok, err = save_timesheet(target_email, contract["project_id"], year, month,
                                     grid, "completed", email)
            if ok:
                st.success("Marked as completed. Download it, sign the PDF and send it to your supervisor.")
                st.rerun()
            else:
                st.error(f"Save failed: {err}")
    with s3:
        try:
            buf = build_timesheet_excel(
                user=user, contract=contract, project=project,
                activities=activities, grid=grid, year=year, month=month,
            )
            st.download_button(
                "⬇️ Download Excel", data=buf,
                file_name=excel_filename(user.get("name", ""), year, month),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Excel error: {e}")
