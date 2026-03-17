import streamlit as st
from core.supabase_client import supabase
from utils.helpers import fmt_date
from utils.modals import person_pill_html


def _fetch_deliverables_overview():
    try:
        projects = (
            supabase.table("projects")
            .select("*")
            .eq("is_archived", False)
            .order("name")
            .execute()
            .data
            or []
        )
        deliverables = (
            supabase.table("deliverables")
            .select("*")
            .eq("is_archived", False)
            .order("deadline")
            .execute()
            .data
            or []
        )
        users = (
            supabase.table("users")
            .select("email, name, avatar_color")
            .eq("is_approved", True)
            .order("name")
            .execute()
            .data
            or []
        )
        user_map = {u["email"]: u for u in users}
        return projects, deliverables, user_map
    except Exception as e:
        st.error(f"Error loading deliverables: {e}")
        return [], [], {}


def _owner_sup_html(d: dict, user_map: dict) -> str:
    owner_e = d.get("owner_email")
    sup_e = d.get("supervisor_email")
    pills = ""
    if owner_e:
        u = user_map.get(owner_e, {"name": owner_e, "avatar_color": "#534AB7"})
        pills += person_pill_html(
            u.get("name", owner_e),
            u.get("avatar_color", "#534AB7"),
            role="owner",
            compact=True,
        )
    if sup_e and sup_e != owner_e:
        u = user_map.get(sup_e, {"name": sup_e, "avatar_color": "#BA7517"})
        pills += person_pill_html(
            u.get("name", sup_e),
            u.get("avatar_color", "#BA7517"),
            role="sup",
            compact=True,
        )
    return pills or "—"


def show_deliverables():
    st.title("Deliverables Overview")

    projects, deliverables, user_map = _fetch_deliverables_overview()
    if not projects or not deliverables:
        st.info("No active deliverables found.")
        return

    proj_by_id = {p["id"]: p for p in projects}

    st.caption(
        "High-level list of deliverables by project, with owner, supervisor and deadlines."
    )
    st.write("")

    for proj in projects:
        pid = proj["id"]
        proj_delivs = [d for d in deliverables if d.get("project_id") == pid]
        if not proj_delivs:
            continue

        with st.expander(
            f"📁 {proj.get('name', 'Project')} ({proj.get('acronym') or proj.get('identifier', '')})",
            expanded=False,
        ):
            st.markdown(
                "**Deliverables**",
            )

            header_cols = st.columns([3, 1.5, 1.3, 1.5, 2.5])
            header_cols[0].markdown("**Name**")
            header_cols[1].markdown("**Type**")
            header_cols[2].markdown("**Status**")
            header_cols[3].markdown("**Deadline**")
            header_cols[4].markdown("**Owner / Supervisor**")

            st.markdown("---")

            for d in proj_delivs:
                c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.3, 1.5, 2.5])
                with c1:
                    st.write(d.get("name") or "—")
                with c2:
                    st.write(d.get("type") or "—")
                with c3:
                    st.write(d.get("status") or "Not started")
                with c4:
                    st.write(fmt_date(d.get("deadline")))
                with c5:
                    st.html(_owner_sup_html(d, user_map))

