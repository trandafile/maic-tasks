"""utils/scopus_fetcher.py

Thin wrapper around the Elsevier/Scopus Search API.

The API key is read from Streamlit secrets (`SCOPUS_API_KEY`) and never
hard-coded. Results are cached for 24 hours per `scopus_id` to avoid hammering
the Scopus quota when several views (e.g. People dashboard) ask for the same
authors during a single day.
"""

from __future__ import annotations

import streamlit as st
import requests

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
PAGE_SIZE = 25
MAX_PAGES = 40  # hard cap = 1000 papers per author, well above realistic needs
REQUEST_TIMEOUT = 20

JOURNAL_TYPE = "Journal"
CONFERENCE_TYPE = "Conference Proceeding"


def _get_api_key() -> str:
    """Read the Scopus API key from Streamlit secrets."""
    try:
        key = st.secrets["SCOPUS_API_KEY"]
    except (KeyError, FileNotFoundError):
        raise RuntimeError(
            "SCOPUS_API_KEY is not configured. Add it to .streamlit/secrets.toml."
        )
    if not key or key == "your_scopus_api_key_here":
        raise RuntimeError(
            "SCOPUS_API_KEY is empty or still set to the placeholder value."
        )
    return key


def _empty_result(error: str | None = None) -> dict:
    return {
        "all": [],
        "journals_by_year": {},
        "conferences_by_year": {},
        "totals": {"journal": 0, "conference": 0, "other": 0, "all": 0},
        "error": error,
    }


def _parse_year(cover_date: str | None) -> int | None:
    if not cover_date or len(cover_date) < 4:
        return None
    try:
        return int(cover_date[:4])
    except ValueError:
        return None


def _scopus_link(entry: dict) -> str | None:
    for link in entry.get("link", []) or []:
        if link.get("@ref") == "scopus":
            return link.get("@href")
    return None


def _format_paper(entry: dict) -> dict:
    agg_type = entry.get("prism:aggregationType") or "Other"
    return {
        "title": entry.get("dc:title") or "(untitled)",
        "year": _parse_year(entry.get("prism:coverDate")),
        "venue": entry.get("prism:publicationName") or "",
        "doi": entry.get("prism:doi"),
        "authors": entry.get("dc:creator") or "",
        "type": agg_type,
        "subtype": entry.get("subtypeDescription") or "",
        "cited_by": int(entry.get("citedby-count") or 0),
        "scopus_id": (entry.get("dc:identifier") or "").replace("SCOPUS_ID:", ""),
        "scopus_link": _scopus_link(entry),
    }


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_publications(scopus_id: str) -> dict:
    """Return all publications for a Scopus author ID.

    Output structure:
        {
            "all": [paper, ...],
            "journals_by_year": {year: [paper, ...], ...},
            "conferences_by_year": {year: [paper, ...], ...},
            "totals": {"journal": int, "conference": int, "other": int, "all": int},
            "error": str | None,
        }
    """
    if not scopus_id:
        return _empty_result("Missing Scopus ID")

    scopus_id = str(scopus_id).strip()
    if not scopus_id:
        return _empty_result("Missing Scopus ID")

    try:
        api_key = _get_api_key()
    except RuntimeError as ex:
        return _empty_result(str(ex))

    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
    }

    all_entries: list[dict] = []
    start = 0

    for _ in range(MAX_PAGES):
        params = {
            "query": f"AU-ID({scopus_id})",
            "count": PAGE_SIZE,
            "start": start,
            "sort": "-coverDate",
        }
        try:
            resp = requests.get(
                SCOPUS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as ex:
            return _empty_result(f"Network error: {ex}")

        if resp.status_code == 401:
            return _empty_result("Scopus API key is invalid or unauthorized.")
        if resp.status_code == 429:
            return _empty_result("Scopus rate limit reached. Try again later.")
        if resp.status_code != 200:
            return _empty_result(
                f"Scopus API returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            payload = resp.json().get("search-results", {}) or {}
        except ValueError:
            return _empty_result("Scopus returned a non-JSON response.")

        entries = payload.get("entry", []) or []

        # Scopus returns a single dummy entry with `error` when there are no results.
        if len(entries) == 1 and entries[0].get("error"):
            break

        if not entries:
            break

        all_entries.extend(entries)

        try:
            total_results = int(payload.get("opensearch:totalResults", 0))
        except (TypeError, ValueError):
            total_results = len(all_entries)

        start += PAGE_SIZE
        if start >= total_results:
            break

    papers = [_format_paper(e) for e in all_entries]

    journals_by_year: dict[int, list[dict]] = {}
    conferences_by_year: dict[int, list[dict]] = {}
    totals = {"journal": 0, "conference": 0, "other": 0, "all": len(papers)}

    for paper in papers:
        year = paper["year"]
        if paper["type"] == JOURNAL_TYPE:
            totals["journal"] += 1
            if year is not None:
                journals_by_year.setdefault(year, []).append(paper)
        elif paper["type"] == CONFERENCE_TYPE:
            totals["conference"] += 1
            if year is not None:
                conferences_by_year.setdefault(year, []).append(paper)
        else:
            totals["other"] += 1

    return {
        "all": papers,
        "journals_by_year": dict(sorted(journals_by_year.items(), reverse=True)),
        "conferences_by_year": dict(sorted(conferences_by_year.items(), reverse=True)),
        "totals": totals,
        "error": None,
    }
