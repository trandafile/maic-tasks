"""views/people.py — Admin-only people / publications dashboard.

Lists all approved users with publication counts pulled from Scopus. Relies on
`fetch_publications` per-author cache (24h TTL) to amortise the API cost across
sessions and across the rendering of this page.
"""

from __future__ import annotations

import datetime
import streamlit as st
import pandas as pd

from core.supabase_client import supabase
from utils.scopus_fetcher import fetch_publications


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _year_breakdown(result: dict) -> pd.DataFrame:
    """Build a per-year DataFrame with three series: Total, Journal, Conference."""
    counts: dict[int, dict[str, int]] = {}
    for paper in result.get("all", []):
        year = paper.get("year")
        if year is None:
            continue
        bucket = counts.setdefault(year, {"Total": 0, "Journal": 0, "Conference": 0})
        bucket["Total"] += 1
        if paper.get("type") == "Journal":
            bucket["Journal"] += 1
        elif paper.get("type") == "Conference Proceeding":
            bucket["Conference"] += 1

    if not counts:
        return pd.DataFrame()

    min_year = min(counts.keys())
    max_year = max(counts.keys())
    full_index = list(range(min_year, max_year + 1))
    rows = [
        {
            "Year": y,
            "Total": counts.get(y, {}).get("Total", 0),
            "Journal": counts.get(y, {}).get("Journal", 0),
            "Conference": counts.get(y, {}).get("Conference", 0),
        }
        for y in full_index
    ]
    return pd.DataFrame(rows).set_index("Year")


def _phd_status_label(user: dict) -> str:
    if not user.get("is_phd_student"):
        return "—"
    start = _parse_date(user.get("phd_start_date"))
    end = _parse_date(user.get("phd_end_date"))
    if not start or not end or end <= start:
        return "PhD (dates missing)"

    today = datetime.date.today()
    total_days = (end - start).days
    total_years = max(1, round(total_days / 365.25))

    if today < start:
        return f"PhD (starts {start.strftime('%Y/%m/%d')})"
    if today >= end:
        return f"PhD completed ({end.strftime('%Y/%m/%d')})"

    current_year = min(total_years, max(1, int((today - start).days // 365.25) + 1))
    return f"PhD year {current_year}/{total_years}"


def show_people() -> None:
    if st.session_state.get("user_role") != "admin":
        st.error("⛔ Restricted area — administrators only.")
        return

    st.title("👥 People — Publications Dashboard")
    st.caption(
        "Aggregated Scopus metrics for all approved users with a configured Scopus Author ID. "
        "Data is cached for 24 hours per author."
    )

    try:
        users = (
            supabase.table("users")
            .select("*")
            .eq("is_approved", True)
            .order("name")
            .execute()
            .data
        )
    except Exception as ex:
        st.error(f"Error loading users: {ex}")
        return

    if not users:
        st.info("No approved users found.")
        return

    with_scopus = [u for u in users if (u.get("scopus_id") or "").strip()]
    without_scopus = [u for u in users if not (u.get("scopus_id") or "").strip()]

    m1, m2, m3 = st.columns(3)
    m1.metric("Approved users", len(users))
    m2.metric("With Scopus ID", len(with_scopus))
    m3.metric("PhD students", sum(1 for u in users if u.get("is_phd_student")))

    if not with_scopus:
        st.info("No user has a Scopus Author ID configured yet.")
        return

    rows: list[dict] = []
    api_errors: list[str] = []
    unique_papers: dict[str, dict] = {}
    author_results: dict[str, dict] = {}

    progress = st.progress(0.0, text="Fetching publication metrics...")
    for idx, user in enumerate(with_scopus, start=1):
        scopus_id = (user.get("scopus_id") or "").strip()
        result = fetch_publications(scopus_id)
        author_results[user["email"]] = result

        if result.get("error"):
            api_errors.append(f"{user.get('name', user['email'])}: {result['error']}")

        for paper in result.get("all", []):
            key = paper.get("scopus_id") or paper.get("doi") or f"{paper.get('title')}|{paper.get('year')}"
            if key:
                unique_papers.setdefault(key, paper)

        totals = result["totals"]
        rows.append({
            "Name": user.get("name") or user["email"],
            "Email": user["email"],
            "Scopus ID": scopus_id,
            "PhD status": _phd_status_label(user),
            "Journals": totals.get("journal", 0),
            "Conferences": totals.get("conference", 0),
            "Other": totals.get("other", 0),
            "Total": totals.get("all", 0),
        })
        progress.progress(idx / len(with_scopus), text=f"Fetched {idx}/{len(with_scopus)}")
    progress.empty()

    df = pd.DataFrame(rows).sort_values("Total", ascending=False)

    unique_journal = sum(1 for p in unique_papers.values() if p.get("type") == "Journal")
    unique_conference = sum(1 for p in unique_papers.values() if p.get("type") == "Conference Proceeding")
    unique_total = len(unique_papers)

    cumulative_total = int(df["Total"].sum())
    duplicates = cumulative_total - unique_total

    sum1, sum2, sum3 = st.columns(3)
    sum1.metric(
        "Unique publications",
        unique_total,
        delta=f"-{duplicates} co-authored" if duplicates > 0 else None,
        delta_color="off",
    )
    sum2.metric("Unique journal articles", unique_journal)
    sum3.metric("Unique conference papers", unique_conference)
    st.caption(
        "Totals are deduplicated across authors: a paper co-authored by N people in this list "
        "counts once here, but appears in each of their per-row counts."
    )

    st.markdown("")
    st.caption("👉 Click a row to see the publications-per-year chart for that author.")
    df_display = df.reset_index(drop=True)
    event = st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="people_table",
        column_config={
            "Scopus ID": st.column_config.TextColumn("Scopus ID", width="small"),
            "Journals": st.column_config.NumberColumn("Journals", format="%d"),
            "Conferences": st.column_config.NumberColumn("Conferences", format="%d"),
            "Other": st.column_config.NumberColumn("Other", format="%d"),
            "Total": st.column_config.NumberColumn("Total", format="%d"),
        },
    )

    selected_rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if selected_rows:
        sel_idx = selected_rows[0]
        sel_row = df_display.iloc[sel_idx]
        sel_email = sel_row["Email"]
        sel_name = sel_row["Name"]

        st.markdown("---")
        st.markdown(f"### 📈 Publications per year — {sel_name}")

        chart_df = _year_breakdown(author_results.get(sel_email, {}))
        if chart_df.empty:
            st.info("No publications with a known year for this author.")
        else:
            st.line_chart(
                chart_df,
                height=340,
                color=["#1565C0", "#188038", "#D93025"],
            )
            st.caption(
                f"Range: {int(chart_df.index.min())}–{int(chart_df.index.max())}  ·  "
                f"Total {int(chart_df['Total'].sum())}  ·  "
                f"Journal {int(chart_df['Journal'].sum())}  ·  "
                f"Conference {int(chart_df['Conference'].sum())}"
            )

    if api_errors:
        with st.expander(f"⚠️ Scopus warnings ({len(api_errors)})", expanded=False):
            for err in api_errors:
                st.write(f"- {err}")

    if without_scopus:
        with st.expander(
            f"Users without a Scopus Author ID ({len(without_scopus)})", expanded=False
        ):
            for u in without_scopus:
                st.write(f"- {u.get('name') or u['email']}  ·  {u['email']}")
