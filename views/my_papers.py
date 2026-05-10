"""views/my_papers.py — Personal publication dashboard.

Displays the Scopus publications of the currently logged-in user, split into
Journal articles and Conference proceedings, with per-year bar charts and a
detailed paper list. PhD students additionally see a progress summary based on
their start/end dates.
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


def _load_user(email: str) -> dict | None:
    try:
        rows = (
            supabase.table("users")
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
            .data
        )
    except Exception as ex:
        st.error(f"Error loading user profile: {ex}")
        return None
    return rows[0] if rows else None


def _phd_progress_block(user: dict) -> None:
    start = _parse_date(user.get("phd_start_date"))
    end = _parse_date(user.get("phd_end_date"))
    if not start or not end or end <= start:
        st.info(
            "PhD start/end dates are not configured. Ask an administrator to set them in the Admin Panel."
        )
        return

    today = datetime.date.today()
    total_days = (end - start).days
    elapsed = (today - start).days
    pct = max(0.0, min(1.0, elapsed / total_days)) if total_days else 0.0

    total_years = max(1, round(total_days / 365.25))
    if today < start:
        current_year = 0
    elif today >= end:
        current_year = total_years
    else:
        current_year = min(total_years, max(1, int((today - start).days // 365.25) + 1))

    with st.container(border=True):
        st.markdown("#### 🎓 PhD progress")
        m1, m2, m3 = st.columns(3)
        m1.metric("Year", f"{current_year} of {total_years}")
        m2.metric("Start", start.strftime("%Y/%m/%d"))
        m3.metric("End", end.strftime("%Y/%m/%d"))
        st.progress(pct, text=f"{pct * 100:.0f}% of the PhD timeline elapsed")


def _papers_section(label: str, papers_by_year: dict[int, list[dict]]) -> None:
    if not papers_by_year:
        st.info(f"No {label.lower()} found for this author on Scopus.")
        return

    counts = {year: len(items) for year, items in papers_by_year.items()}
    chart_df = (
        pd.DataFrame({"Year": list(counts.keys()), "Publications": list(counts.values())})
        .sort_values("Year")
        .set_index("Year")
    )
    st.bar_chart(chart_df, height=240)

    for year in sorted(papers_by_year.keys(), reverse=True):
        items = papers_by_year[year]
        with st.expander(f"{year} — {len(items)} publication(s)", expanded=False):
            for paper in items:
                title = paper.get("title") or "(untitled)"
                venue = paper.get("venue") or ""
                authors = paper.get("authors") or ""
                doi = paper.get("doi")
                link = paper.get("scopus_link")
                cited = paper.get("cited_by") or 0

                head = f"**{title}**"
                if link:
                    head = f"[{title}]({link})"
                st.markdown(head)

                meta_bits = []
                if venue:
                    meta_bits.append(f"*{venue}*")
                if authors:
                    meta_bits.append(authors)
                meta_bits.append(f"cited by {cited}")
                st.caption("  ·  ".join(meta_bits))

                if doi:
                    st.caption(f"DOI: [{doi}](https://doi.org/{doi})")
                st.markdown("")


def show_my_papers() -> None:
    st.title("📚 My Publications")

    email = st.session_state.get("user_email")
    if not email:
        st.error("You must be logged in to view this page.")
        return

    user = _load_user(email)
    if not user:
        st.error("Could not load your profile.")
        return

    if user.get("is_phd_student"):
        _phd_progress_block(user)
        st.markdown("")

    scopus_id = (user.get("scopus_id") or "").strip()
    if not scopus_id:
        st.info(
            "Your Scopus Author ID is not configured. Ask an administrator to add it in the Admin Panel "
            "(Users → Edit → Scopus Author ID)."
        )
        return

    with st.spinner("Fetching publications from Scopus..."):
        result = fetch_publications(scopus_id)

    if result.get("error"):
        st.error(f"Scopus error: {result['error']}")
        return

    totals = result["totals"]
    if totals["all"] == 0:
        st.warning("No publications found for this Scopus ID.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total publications", totals["all"])
    m2.metric("Journal articles", totals["journal"])
    m3.metric("Conference papers", totals["conference"])
    m4.metric("Other", totals["other"])

    st.markdown("")
    tab_journals, tab_conferences = st.tabs(
        [f"📰 Journal Articles ({totals['journal']})", f"🎤 Conference Papers ({totals['conference']})"]
    )
    with tab_journals:
        _papers_section("Journal articles", result["journals_by_year"])
    with tab_conferences:
        _papers_section("Conference papers", result["conferences_by_year"])

    st.caption(
        "Data cached for 24 hours per Scopus ID. Source: Elsevier/Scopus Search API."
    )
